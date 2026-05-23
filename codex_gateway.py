# codex_qwen_gateway.py
import json
import os
import re
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# =========================================================
# CONFIG
# =========================================================

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://yourserver:7980/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-397B-A17B-FP8")
app = FastAPI()

# =========================================================
# REGEX
# =========================================================

THINK_RE = re.compile(r"<think>.*?</think>", re.S)
TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*<function=(?P<name>[^>]+)>\s*(?P<body>.*?)</function>\s*</tool_call>",
    re.S,
)
PARAM_RE = re.compile(r"<parameter=(?P<name>[^>]+)>\s*(?P<value>.*?)</parameter>", re.S)

# =========================================================
# MEMORY
# =========================================================
RESPONSES: dict[str, dict[str, Any]] = {}

# =========================================================
# HELPERS
# =========================================================

def strip_think(text: str) -> str:
    return THINK_RE.sub("", text).strip()

def get_emit_text(text: str) -> str:
    """
    流式安全文本提取器：完美屏蔽 <think> 和 <tool_call> 标签及其残缺部分。
    """
    text = THINK_RE.sub("", text)
    
    # 屏蔽未闭合的 <think>
    think_idx = text.rfind("<think>")
    if think_idx != -1 and "</think>" not in text[think_idx:]:
        text = text[:think_idx]
        
    # 屏蔽开始的 <tool_call> 及后续全部内容
    tool_idx = text.find("<tool_call")
    if tool_idx != -1:
        text = text[:tool_idx]
        
    # 屏蔽可能出现在末尾的截断标签
    partials = [
        "<", "<t", "<to", "<too", "<tool", "<tool_", "<tool_c", "<tool_ca", "<tool_cal", "<tool_call",
        "<th", "<thi", "<thin", "<think"
    ]
    for p in partials:
        if text.endswith(p):
            text = text[:-len(p)]
            break
            
    return text

def flatten_tools(tools):
    if not tools:
        return []
    out = []
    for tool in tools:
        if tool.get("type") == "namespace":
            out.extend(tool.get("tools", []))
        else:
            out.append(tool)
    return out

def parse_xml_tool_call(text: str):
    m = TOOL_CALL_RE.search(text)
    if not m:
        return None
    fn_name = m.group("name").strip()
    body = m.group("body")
    args = {}
    for p in PARAM_RE.finditer(body):
        args[p.group("name").strip()] = p.group("value").strip()
    return {
        "id": f"call_{uuid.uuid4().hex[:8]}",
        "type": "function",
        "function": {
            "name": fn_name,
            "arguments": json.dumps(args, ensure_ascii=False),
        },
    }

def build_xml_tool_call(name: str, arguments: dict[str, Any]):
    out = ["<tool_call>", f"<function={name}>"]
    for k, v in arguments.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        out.extend([f"<parameter={k}>", str(v), "</parameter>"])
    out.extend(["</function>", "</tool_call>"])
    return "\n".join(out)

# =========================================================
# TOOL PROMPT
# =========================================================

def build_tool_system_prompt(tools):
    tools = flatten_tools(tools)
    if not tools:
        return ""

    out = [
        "# Tools",
        "",
        "You have access to the following functions:",
        "",
        "<tools>"
    ]
    for tool in tools:
        out.append(json.dumps(tool, ensure_ascii=False))
        
    out.extend([
        "</tools>",
        "",
        "When calling a tool, output one or more XML blocks in exactly this format and nothing after the final </tool_call>:",
        "",
        "<tool_call>",
        "<function=example_function_name>",
        "<parameter=example_parameter_1>",
        "value_1",
        "</parameter>",
        "<parameter=example_parameter_2>",
        "This is the value for the second parameter",
        "that can span",
        "multiple lines",
        "</parameter>",
        "</function>",
        "</tool_call>",
        "",
        "CRITICAL RULES FOR ASSISTANT:",
        "1. YOU ARE CONNECTED TO A REAL SYSTEM VIA TOOLS. YOU MUST USE THEM!",
        "2. DO NOT HALLUCINATE OR GUESS file contents or command outputs. Always call 'read_file_content' or 'execute_shell_command' first.",
        "3. You must copy the exact tool name from the JSON above. If the tool name has a prefix (e.g., 'codex-tools__execute_shell_command'), you MUST include the prefix in the <function=...> tag.",
        "4. Put any reasoning or natural language BEFORE the first <tool_call>, never after the last </tool_call>.",
        "5. For object or array parameter values, write valid JSON inside the parameter body.",
        "6. ONLY answer from memory if the user is asking a general knowledge question unrelated to the workspace.",
        "",
        "CRITICAL FILE OPERATION RULES (IRON LAW):",
        "- NEVER use shell/terminal commands (like PowerShell Get-Content/Set-Content, awk, sed, cat, echo, Out-File) to read or edit files.",
        "- YOU MUST ALWAYS use the dedicated file tools (e.g., 'read_file_content', 'modify_file_code', 'write_new_file') for ALL file operations.",
        "- Using shell commands for file modification is FORBIDDEN and will cause errors!"
    ])
    return "\n".join(out)

# =========================================================
# MESSAGE CONVERTER
# =========================================================

def convert_openai_messages(messages, tools=None):
    tool_prompt = build_tool_system_prompt(tools)
    out = []
    inserted_system = False

    for msg in messages:
        role = msg.get("role", "")
        if role == "system":
            content = msg.get("content", "")
            if tool_prompt:
                content += "\n\n" + tool_prompt
            out.append({"role": "system", "content": content})
            inserted_system = True
            continue

        if role == "tool":
            content = msg.get("content", "")
            out.append({
                "role": "user",
                "content": f"<tool_response>\n{content}\n</tool_response>"
            })
            continue

        if role == "assistant" and msg.get("tool_calls"):
            xml_blocks = []
            for tc in msg["tool_calls"]:
                fn = tc["function"]
                args = json.loads(fn["arguments"])
                xml_blocks.append(build_xml_tool_call(fn["name"], args))
            out.append({"role": "assistant", "content": "\n".join(xml_blocks)})
            continue

        out.append(msg)

    if not inserted_system and tool_prompt:
        out.insert(0, {"role": "system", "content": tool_prompt})
    return out

def convert_responses_input(input_items, tools=None):
    tool_prompt = build_tool_system_prompt(tools)
    messages = []
    inserted_system = False

    for item in input_items:
        item_type = item.get("type", "message")
        if item_type == "function_call_output":
            messages.append({
                "role": "tool",
                "content": item.get("output", ""),
            })
            continue

        if item_type == "message":
            role = item.get("role", "user")
            texts = []
            content = item.get("content", [])
            if isinstance(content, str):
                texts = [content]
            elif isinstance(content, list):
                for c in content:
                    if c.get("type") in ("input_text", "output_text", "text"):
                        texts.append(c.get("text", ""))
            
            text_content = "\n".join(texts)
            if role == "system":
                if tool_prompt:
                    text_content += "\n\n" + tool_prompt
                messages.append({"role": "system", "content": text_content})
                inserted_system = True
                continue
            
            messages.append({"role": role, "content": text_content})

    if not inserted_system and tool_prompt:
        messages.insert(0, {"role": "system", "content": tool_prompt})
    return messages

# =========================================================
# VLLM STREAM
# =========================================================

async def vllm_stream(payload):
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{VLLM_BASE_URL}/chat/completions", json=payload) as r:
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"): continue
                data = line[5:].strip()
                if data == "[DONE]":
                    yield "[DONE]"
                    return
                try:
                    yield json.loads(data)
                except:
                    continue

# =========================================================
# MODELS
# =========================================================

@app.get("/v1/models")
async def models():
    return {
        "object": "list",
        "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "qwen", "permission": [], "context_length": 262144}],
    }

# =========================================================
# RESPONSES API
# =========================================================

@app.post("/v1/responses")
async def responses(req: Request):
    body = await req.json()
    stream = body.get("stream", False)
    model = body.get("model", MODEL_NAME)
    response_id = f"resp_{uuid.uuid4().hex[:8]}"
    tools = body.get("tools")
    
    messages = convert_responses_input(body.get("input", []), tools)
    
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "temperature": body.get("temperature", 0.2),
        "extra_body": {
            "enable_thinking": True,
        },
    }

    # =====================================
    # STREAM
    # =====================================
    if stream:
        async def stream_events():
            item_id = f"msg_{uuid.uuid4().hex[:8]}"
            
            # 帮助函数，强行使用 ensure_ascii=False 防止乱码
            def make_event(event_type, event_payload):
                payload_dict = {"type": event_type, **event_payload}
                return f"data: {json.dumps(payload_dict, ensure_ascii=False)}\n\n"

            yield make_event("response.created", {"response": {"id": response_id, "object": "response", "created_at": int(time.time()), "status": "in_progress", "model": model, "output": []}})
            yield make_event("response.in_progress", {"response": {"id": response_id, "object": "response", "status": "in_progress", "model": model}})

            accumulated = ""
            emitted_length = 0
            full_text = ""
            message_item_created = False
            content_part_created = False

            async for chunk in vllm_stream(payload):
                # ------------------------------------
                # 遇到 [DONE] 时统一结算：支持 纯文本 / 纯工具 / 文本+工具混合
                # ------------------------------------
                if chunk == "[DONE]":
                    tc = parse_xml_tool_call(accumulated)
                    
                    output_items = []
                    output_index = 0
                    
                    # 1. 结算阶段：如果有被打开的普通文本对话，安全关闭并提交
                    if message_item_created:
                        if content_part_created:
                            yield make_event("response.output_text.done", {"item_id": item_id, "output_index": output_index, "content_index": 0, "text": full_text})
                            yield make_event("response.content_part.done", {"item_id": item_id, "output_index": output_index, "content_index": 0, "part": {"type": "output_text", "text": full_text}})
                        
                        text_item = {"id": item_id, "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": full_text}]}
                        yield make_event("response.output_item.done", {"output_index": output_index, "item": text_item})
                        
                        output_items.append(text_item)
                        output_index += 1  # 关键修复：工具推移到下一个 Index，避免状态冲突

                    # 2. 结算阶段：如果解析出了工具调用，发送工具请求事件
                    if tc:
                        tool_item_id = f"fc_{uuid.uuid4().hex[:8]}"
                        tool_args = tc["function"]["arguments"]
                        tool_name = tc["function"]["name"]
                        
                        yield make_event("response.output_item.added", {"output_index": output_index, "item": {"id": tool_item_id, "type": "function_call", "status": "in_progress", "call_id": tc['id'], "name": tool_name, "arguments": ""}})
                        yield make_event("response.function_call_arguments.delta", {"item_id": tool_item_id, "output_index": output_index, "delta": tool_args})
                        yield make_event("response.function_call_arguments.done", {"item_id": tool_item_id, "output_index": output_index, "arguments": tool_args})
                        
                        func_item = {"id": tool_item_id, "type": "function_call", "status": "completed", "call_id": tc['id'], "name": tool_name, "arguments": tool_args}
                        yield make_event("response.output_item.done", {"output_index": output_index, "item": func_item})
                        
                        output_items.append(func_item)

                    # 3. 结算阶段：如果异常情况下没有任何输出，兜底发一个空回复以防止CLI报错
                    if not output_items:
                        text_item = {"id": item_id, "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": ""}]}
                        yield make_event("response.output_item.added", {"output_index": output_index, "item": {"id": item_id, "type": "message", "role": "assistant", "status": "in_progress", "content": []}})
                        yield make_event("response.output_item.done", {"output_index": output_index, "item": text_item})
                        output_items.append(text_item)

                    final_resp = {"id": response_id, "object": "response", "created_at": int(time.time()), "status": "completed", "model": model, "output": output_items}
                    RESPONSES[response_id] = final_resp
                    yield make_event("response.completed", {"response": final_resp})
                    yield "data: [DONE]\n\n"
                    return

                # ------------------------------------
                # 正常文本流处理（过滤XML及思考过程）
                # ------------------------------------
                if "__error__" in chunk:
                    yield make_event("response.failed", {"error": chunk.get('__error__')})
                    yield "data: [DONE]\n\n"
                    return

                delta_obj = chunk.get("choices", [{}])[0].get("delta", {})
                piece = (
                    delta_obj.get("content")
                    or delta_obj.get("reasoning_content")
                    or ""
                )

                if piece:
                    accumulated += piece
                # print("DELTA KEYS:", list(chunk.get("choices", [{}])[0].get("delta", {}).keys()))

                emit_text = get_emit_text(accumulated)
                new_text = emit_text[emitted_length:]
                
                if new_text:
                    if not message_item_created:
                        message_item_created = True
                        content_part_created = True
                        yield make_event("response.output_item.added", {"output_index": 0, "item": {"id": item_id, "type": "message", "role": "assistant", "status": "in_progress", "content": []}})
                        yield make_event("response.content_part.added", {"item_id": item_id, "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": ""}})
                    
                    yield make_event("response.output_text.delta", {"item_id": item_id, "output_index": 0, "content_index": 0, "delta": new_text})
                    emitted_length = len(emit_text)
                    full_text += new_text

        return StreamingResponse(stream_events(), media_type="text/event-stream")

    # =====================================
    # NON-STREAMING (兜底)
    # =====================================
    async with httpx.AsyncClient(timeout=1800) as client:
        r = await client.post(f"{VLLM_BASE_URL}/chat/completions", json=payload)
    data = r.json()
    text = data["choices"][0]["message"].get("content", "")
    tc = parse_xml_tool_call(text)
    
    if tc:
        out_item = {"id": f"fc_{uuid.uuid4().hex[:8]}", "type": "function_call", "status": "completed", "call_id": tc["id"], "name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}
    else:
        out_item = {"id": f"msg_{uuid.uuid4().hex[:8]}", "type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": strip_think(text)}]}
        
    response = {"id": response_id, "object": "response", "created_at": int(time.time()), "status": "completed", "model": model, "output": [out_item]}
    RESPONSES[response_id] = response
    return JSONResponse(response)

@app.get("/v1/responses/{response_id}")
async def get_response(response_id: str):
    if response_id in RESPONSES: return RESPONSES[response_id]
    return {"id": response_id, "object": "response", "status": "completed", "output": []}

@app.post("/v1/chat/completions")
async def chat_completions(req: Request):
    return JSONResponse({"error": "Please use /v1/responses API for streaming Agent."})