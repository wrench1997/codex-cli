# codex_qwen_gateway.py
import json
import os
import re
import time
import threading
import urllib.request
import uuid
from datetime import datetime
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# =========================================================
# CONFIG
# =========================================================

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://yourserver:7980")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-397B-A17B-FP8")
# vLLM Metrics 端点 URL（从基础 URL 派生）
METRICS_URL = VLLM_BASE_URL.rstrip("/") + "/metrics"
# 数据刷新频率（秒）
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "5"))
app = FastAPI()

# =========================================================
# BILLING STATS - 当天计费统计
# =========================================================

def fetch_metrics(url):
    """从 vLLM metrics 端点获取数据"""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            metrics_text = response.read().decode('utf-8')
            
            # 打印所有包含 vllm 的行
            # print("\n" + "="*60)
            # print("[Metrics] vLLM 相关指标:")
            # print("="*60)
            # for line in metrics_text.split('\n'):
            #     if 'vllm' in line.lower():
            #         print(line)
            # print("="*60 + "\n")
            
            return metrics_text
    except Exception as e:
        print(f"[Metrics] 获取失败：{e}")
        return None

def extract_metric(metrics_text, metric_name, label_value=None):
    """
    正则匹配 Prometheus 格式数据，支持 label 过滤
    例如：vllm:gpu_prefix_cache_hit_rate{model="Qwen/Qwen3.5-397B-A17B-FP8"} 0.452
    或：vllm:prefix_cache_hits_total{engine="0",model_name="Qwen/Qwen3.5-397B-A17B-FP8"} 102432.0
    """
    if label_value:
        # 带 label 过滤的匹配
        pattern = rf'{metric_name}\{{[^}}]*{label_value}[^}}]*\}}\s+([0-9.eE+-]+)'
    else:
        pattern = rf'{metric_name}(?:{{[^}}]*}})?\s+([0-9.eE+-]+)'
    match = re.search(pattern, metrics_text)
    if match:
        return float(match.group(1))
    return None

def calculate_cache_hit_rate(metrics_text):
    """
    根据 vLLM metrics 计算前缀缓存命中率
    命中率 = prefix_cache_hits_total / prefix_cache_queries_total
    """
    hits = extract_metric(metrics_text, 'vllm:prefix_cache_hits_total')
    queries = extract_metric(metrics_text, 'vllm:prefix_cache_queries_total')
    
    if hits is not None and queries is not None and queries > 0:
        return hits / queries
    return None

class BillingStats:
    """
    当天计费统计类 - 基于 vLLM Metrics 的精确缓存命中计费
    
    计费逻辑：
    1. 从 vLLM metrics 获取累计的缓存命中 tokens 和计算 tokens
    2. 记录启动时的基准值，计算增量作为当前会话的统计
    3. 缓存命中的 tokens 按优惠价格计费，普通 tokens 按标准价格计费
    """
    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.cached_input_tokens = 0
        self.normal_input_tokens = 0
        self.request_count = 0
        self.cache_hit_count = 0
        # TTFT 缓存命中判断：如果 TTFT < 阈值，认为缓存命中（作为备用方案）
        self.ttft_cache_hit_threshold = float(os.getenv("TTFT_CACHE_HIT_THRESHOLD", "0.5"))  # 秒
        # 动态基准：记录最近 N 次请求的 TTFT 用于比较
        self.ttft_history = []
        self.ttft_history_max = 10
        # 价格配置 (每 1M tokens，人民币)
        self.input_price_per_1m = float(os.getenv("INPUT_PRICE_PER_1M", "3.0"))
        self.output_price_per_1m = float(os.getenv("OUTPUT_PRICE_PER_1M", "6.0"))
        self.cached_input_price_per_1m = float(os.getenv("CACHED_INPUT_PRICE_PER_1M", "0.025"))
        
        # vLLM Metrics 缓存命中率（从 /metrics 端点获取）
        self.gpu_prefix_cache_hit_rate = 0.0
        self.cpu_prefix_cache_hit_rate = 0.0
        self.gpu_kv_cache_usage = 0.0
        self.last_metrics_update = None
        
        # Metrics 基准值（启动时的累计值，用于计算增量）
        self.metrics_baseline_cached = None  # vllm:prompt_tokens_by_source_total{source="local_cache_hit"}
        self.metrics_baseline_compute = None  # vllm:prompt_tokens_by_source_total{source="local_compute"}
        self.metrics_baseline_queries = None  # vllm:prefix_cache_queries_total
        self.metrics_baseline_hits = None     # vllm:prefix_cache_hits_total
        
        # 是否已初始化基准值
        self.metrics_baseline_initialized = False
        
        # 启动后台线程定期刷新 metrics
        self._start_metrics_polling()
    
    def _init_metrics_baseline(self, metrics_text):
        """初始化 metrics 基准值（启动时的累计值）"""
        self.metrics_baseline_cached = extract_metric(metrics_text, 'vllm:prompt_tokens_by_source_total', 'local_cache_hit')
        self.metrics_baseline_compute = extract_metric(metrics_text, 'vllm:prompt_tokens_by_source_total', 'local_compute')
        self.metrics_baseline_queries = extract_metric(metrics_text, 'vllm:prefix_cache_queries_total')
        self.metrics_baseline_hits = extract_metric(metrics_text, 'vllm:prefix_cache_hits_total')
        self.metrics_baseline_initialized = True
        print(f"[BillingStats] Metrics 基准值已初始化:")
        print(f"  - 缓存命中 tokens 基准：{self.metrics_baseline_cached}")
        print(f"  - 计算 tokens 基准：{self.metrics_baseline_compute}")
    
    def _update_from_metrics(self, metrics_text):
        """根据 metrics 增量更新缓存命中统计"""
        if not self.metrics_baseline_initialized:
            self._init_metrics_baseline(metrics_text)
            return
        
        # 获取当前累计值
        current_cached = extract_metric(metrics_text, 'vllm:prompt_tokens_by_source_total', 'local_cache_hit')
        current_compute = extract_metric(metrics_text, 'vllm:prompt_tokens_by_source_total', 'local_compute')
        current_queries = extract_metric(metrics_text, 'vllm:prefix_cache_queries_total')
        current_hits = extract_metric(metrics_text, 'vllm:prefix_cache_hits_total')
        
        if current_cached is not None and self.metrics_baseline_cached is not None:
            # 计算增量：当前会话的缓存命中 tokens
            delta_cached = current_cached - self.metrics_baseline_cached
            delta_compute = current_compute - self.metrics_baseline_compute
            
            if delta_cached > 0 or delta_compute > 0:
                # 更新统计
                self.cached_input_tokens = int(delta_cached)
                self.normal_input_tokens = int(delta_compute)
                self.total_input_tokens = self.cached_input_tokens + self.normal_input_tokens
                
                # 计算缓存命中率
                if current_queries is not None and self.metrics_baseline_queries is not None:
                    delta_queries = current_queries - self.metrics_baseline_queries
                    delta_hits = current_hits - self.metrics_baseline_hits if current_hits and self.metrics_baseline_hits else 0
                    if delta_queries > 0:
                        self.gpu_prefix_cache_hit_rate = delta_hits / delta_queries if delta_hits else 0
                
                # 估算请求次数（基于 queries 增量）
                if delta_queries > 0:
                    # 假设每次请求平均查询一定数量的 tokens
                    self.request_count = max(self.request_count, int(delta_queries / 1000))  # 粗略估算
                
                print(f"[BillingStats] Metrics 更新：cached={self.cached_input_tokens}, compute={self.normal_input_tokens}, hit_rate={self.gpu_prefix_cache_hit_rate:.2%}")
    
    def _start_metrics_polling(self):
        """启动后台线程定期刷新 metrics"""
        def poll_metrics():
            while True:
                metrics_text = fetch_metrics(METRICS_URL)
                if metrics_text:
                    # 获取 KV 缓存使用率
                    gpu_kv = extract_metric(metrics_text, 'vllm:kv_cache_usage_perc')
                    if gpu_kv is not None:
                        self.gpu_kv_cache_usage = gpu_kv
                    
                    # 更新缓存命中统计（基于 metrics 增量）
                    self._update_from_metrics(metrics_text)
                    
                    self.last_metrics_update = datetime.now()
                
                time.sleep(POLL_INTERVAL)
        
        thread = threading.Thread(target=poll_metrics, daemon=True)
        thread.start()
    
    def get_current_cache_hit_rate(self) -> float:
        """获取当前 GPU 前缀缓存命中率"""
        return self.gpu_prefix_cache_hit_rate
    
    def get_metrics_status(self) -> dict:
        """获取当前 metrics 状态"""
        return {
            "gpu_prefix_cache_hit_rate": f"{self.gpu_prefix_cache_hit_rate * 100:.2f}%",
            "cpu_prefix_cache_hit_rate": f"{self.cpu_prefix_cache_hit_rate * 100:.2f}%",
            "gpu_kv_cache_usage": f"{self.gpu_kv_cache_usage * 100:.2f}%",
            "last_update": self.last_metrics_update.strftime("%Y-%m-%d %H:%M:%S") if self.last_metrics_update else "N/A",
            "baseline_initialized": self.metrics_baseline_initialized,
            "baseline_cached_tokens": self.metrics_baseline_cached,
            "baseline_compute_tokens": self.metrics_baseline_compute,
        }
    
    def is_cache_hit_by_ttft(self, ttft: float) -> bool:
        """基于 TTFT 判断是否缓存命中（备用方案）"""
        # 方法 1：绝对阈值
        if ttft < self.ttft_cache_hit_threshold:
            return True
        # 方法 2：与历史平均比较（如果有足够数据）
        if len(self.ttft_history) >= 3:
            avg_ttft = sum(self.ttft_history) / len(self.ttft_history)
            # 如果当前 TTFT 显著低于平均值（比如 50%），认为缓存命中
            if ttft < avg_ttft * 0.5:
                return True
        return False
    
    def record_ttft(self, ttft: float):
        """记录 TTFT 到历史"""
        self.ttft_history.append(ttft)
        if len(self.ttft_history) > self.ttft_history_max:
            self.ttft_history.pop(0)
    
    def add_request(self, input_tokens: int, output_tokens: int, ttft: float = None):
        """
        添加一次请求的统计数据
        
        注意：当 metrics 可用时，tokens 统计由 metrics 增量驱动，
        此方法主要用于统计 request_count 和 output_tokens
        """
        self.request_count += 1
        self.total_output_tokens += output_tokens
        
        # 如果 metrics 尚未初始化，使用 TTFT 估算（临时方案）
        if not self.metrics_baseline_initialized:
            self.total_input_tokens += input_tokens
            
            cache_hit = False
            cached_tokens = 0
            
            if ttft is not None:
                self.record_ttft(ttft)
                cache_hit = self.is_cache_hit_by_ttft(ttft)
                if cache_hit:
                    cached_tokens = int(input_tokens * 0.9)
                    self.cache_hit_count += 1
            
            self.cached_input_tokens += cached_tokens
            self.normal_input_tokens += (input_tokens - cached_tokens)
        # 如果 metrics 已初始化，tokens 由 _update_from_metrics 更新，这里只更新 output
    
    def calculate_cost(self) -> dict:
        """计算总费用"""
        normal_input_cost = (self.normal_input_tokens / 1_000_000) * self.input_price_per_1m
        cached_input_cost = (self.cached_input_tokens / 1_000_000) * self.cached_input_price_per_1m
        output_cost = (self.total_output_tokens / 1_000_000) * self.output_price_per_1m
        
        total_input_cost = normal_input_cost + cached_input_cost
        total_cost = total_input_cost + output_cost
        original_input_cost = (self.total_input_tokens / 1_000_000) * self.input_price_per_1m
        original_total = original_input_cost + output_cost
        saved_cost = original_total - total_cost
        
        return {
            "input_cost": total_input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
            "saved_cost": saved_cost,
            "original_total": original_total,
        }
    
    def to_dict(self) -> dict:
        """返回统计字典"""
        costs = self.calculate_cost()
        
        # 计算基于 metrics 的缓存命中率
        metrics_hit_rate = "N/A"
        if self.total_input_tokens > 0:
            metrics_hit_rate = f"{self.cached_input_tokens / self.total_input_tokens * 100:.1f}%"
        
        return {
            "request_count": self.request_count,
            "cache_hit_count": self.cache_hit_count,
            "cache_hit_rate": f"{self.cache_hit_count/self.request_count*100:.1f}%" if self.request_count > 0 else "N/A",
            "metrics_cache_hit_rate": metrics_hit_rate,
            "total_input_tokens": self.total_input_tokens,
            "normal_input_tokens": self.normal_input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "input_cost": f"{costs['input_cost']:.6f}",
            "output_cost": f"{costs['output_cost']:.6f}",
            "total_cost": f"{costs['total_cost']:.6f}",
            "original_total": f"{costs['original_total']:.6f}",
            "saved_cost": f"{costs['saved_cost']:.6f}",
            "saved_rate": f"{costs['saved_cost']/costs['original_total']*100:.1f}%" if costs['original_total'] > 0 else "0%",
            # vLLM Metrics 详细信息
            "metrics": self.get_metrics_status(),
        }

billing_stats = BillingStats()

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
    """流式请求 vLLM，并测量 TTFT 用于缓存命中判断"""
    # 添加 stream_options 以请求 vLLM 返回 usage 信息
    payload_with_usage = payload.copy()
    payload_with_usage["stream_options"] = {"include_usage": True}
    
    start_time = time.perf_counter()
    ttft_measured = None
    first_token_received = False
    
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", f"{VLLM_BASE_URL}/v1/chat/completions", json=payload_with_usage) as r:
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"): continue
                data = line[5:].strip()
                if data == "[DONE]":
                    yield "[DONE]"
                    return
                try:
                    chunk = json.loads(data)
                    
                    # 测量 TTFT：检测到第一个有内容的 delta 时记录时间
                    if not first_token_received:
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            if delta.get("content") or delta.get("reasoning_content"):
                                ttft_measured = time.perf_counter() - start_time
                                first_token_received = True
                                # 将 TTFT 注入到 chunk 中，供后续使用
                                if "usage" not in chunk:
                                    chunk["usage"] = {}
                                chunk["usage"]["ttft"] = ttft_measured
                    
                    # 统计 token 使用
                    if "usage" in chunk and chunk["usage"]:
                        usage = chunk["usage"]
                        input_tokens = usage.get("prompt_tokens", 0)
                        output_tokens = usage.get("completion_tokens", 0)
                        # 优先使用 vLLM 返回的 TTFT，否则使用测量的 TTFT
                        ttft = usage.get("ttft", ttft_measured)
                        if input_tokens > 0 or output_tokens > 0:
                            billing_stats.add_request(input_tokens, output_tokens, ttft)
                    yield chunk
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

                choices = chunk.get("choices", [])
                if not choices:
                    continue  # Skip chunks with no choices
                delta_obj = choices[0].get("delta", {})
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
        r = await client.post(f"{VLLM_BASE_URL}/v1/chat/completions", json=payload)
    data = r.json()
    
    # 统计 token 使用（非流式模式）
    usage = data.get("usage")
    if usage:
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        # 基于 TTFT 的缓存命中统计
        ttft = usage.get("ttft", None)
        if input_tokens > 0 or output_tokens > 0:
            billing_stats.add_request(input_tokens, output_tokens, ttft)
    
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


# =========================================================
# BILLING API - 计费查询
# =========================================================

@app.get("/v1/billing")
async def get_billing():
    """获取当天计费统计"""
    return billing_stats.to_dict()


@app.post("/v1/billing/reset")
async def reset_billing():
    """重置计费统计"""
    global billing_stats
    billing_stats = BillingStats()
    return {"status": "ok", "message": "计费统计已重置"}