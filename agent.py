# agent.py
"""
Agent 核心：维护对话历史，驱动工具调用循环。
"""

import json
import re
import uuid
from typing import Any, AsyncIterator, Optional

import httpx

from config import CONFIG
from tools import TOOLS, ToolExecutor

THINK_RE = re.compile(r"<think>.*?</think>", re.S)
TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*<function=(?P<name>[^>]+)>\s*(?P<body>.*?)</function>\s*</tool_call>",
    re.S,
)
PARAM_RE = re.compile(r"<parameter=(?P<name>[^>]+)>\s*(?P<value>.*?)</parameter>", re.S)


def _strip_think(text: str) -> str:
    return THINK_RE.sub("", text).strip()


def _parse_tool_call(text: str) -> Optional[dict]:
    m = TOOL_CALL_RE.search(text)
    if not m:
        return None
    name = m.group("name").strip()
    body = m.group("body")
    args: dict[str, Any] = {}
    for p in PARAM_RE.finditer(body):
        raw = p.group("value").strip()
        # 尝试将参数解析为 JSON（处理对象/数组/布尔值/数字）
        try:
            args[p.group("name").strip()] = json.loads(raw)
        except json.JSONDecodeError:
            args[p.group("name").strip()] = raw
    return {"name": name, "arguments": args}


def _build_xml_tool_call(name: str, arguments: dict) -> str:
    parts = [f"<tool_call>\n<function={name}>"]
    for k, v in arguments.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        parts.append(f"<parameter={k}>\n{v}\n</parameter>")
    parts.append("</function>\n</tool_call>")
    return "\n".join(parts)


def _build_tool_system_prompt() -> str:
    tool_descs = json.dumps(TOOLS, ensure_ascii=False, indent=2)
    return f"""# Tools

You have access to the following tools:

<tools>
{tool_descs}
</tools>

When you need to call a tool, output EXACTLY this XML format:

<tool_call>
<function=TOOL_NAME>
<parameter=PARAM_NAME>
value
</parameter>
</function>
</tool_call>

RULES:
1. Call ONE tool per response. Wait for the result before calling the next.
2. Put reasoning BEFORE the <tool_call>. Nothing after </tool_call>.
3. Use exact tool names from the schema above.
4. For file edits, ALWAYS read the file first, then use search_replace or replace_lines.
5. Prefer search_replace for targeted edits; use write_file only for new files or full rewrites.
6. After completing all tasks, provide a clear summary WITHOUT calling any more tools.
"""


# ──────────────────────────────────────────────────────────────────
# Streaming call to vLLM / gateway
# ──────────────────────────────────────────────────────────────────

async def _stream_completion(messages: list[dict]) -> AsyncIterator[str]:
    """向 vLLM 发流式请求，逐 token yield 原始 content 字符串。"""
    payload = {
        "model": CONFIG.model,
        "messages": messages,
        "stream": True,
        "temperature": CONFIG.temperature,
        "extra_body": {"enable_thinking": True},
    }
    headers = {"Authorization": f"Bearer {CONFIG.api_key}"}

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{CONFIG.api_base}/chat/completions",
            json=payload,
            headers=headers,
        ) as resp:
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except Exception:
                    continue


# ──────────────────────────────────────────────────────────────────
# Agent
# ──────────────────────────────────────────────────────────────────

class Agent:
    def __init__(self, workdir: str, auto_approve: bool = False):
        self.workdir = workdir
        self.executor = ToolExecutor(workdir, auto_approve=auto_approve)
        self.auto_approve = auto_approve
        self.messages: list[dict] = [
            {
                "role": "system",
                "content": (
                    "You are Codex, an expert AI coding assistant. "
                    "You can read, write, search, and modify code files. "
                    "Always prefer minimal, targeted edits. "
                    "Explain what you're doing in Chinese.\n\n"
                    + _build_tool_system_prompt()
                ),
            }
        ]

    def reset(self):
        self.messages = self.messages[:1]  # 只保留 system prompt

    def add_user_message(self, text: str):
        self.messages.append({"role": "user", "content": text})

    async def run_turn(
        self,
        on_text: Any = None,        # async callback(str) -> None
        on_tool_call: Any = None,   # async callback(name, args) -> None
        on_tool_result: Any = None, # async callback(name, success, output) -> None
        on_pending: Any = None,     # async callback(path, diff) -> bool (approve?)
    ) -> str:
        """
        执行一个完整的 Agent turn（可能包含多次工具调用）。
        返回最终的文本回复。
        """
        for turn in range(CONFIG.max_turns):
            # ── 流式收集模型输出 ──────────────────────────
            accumulated = ""
            visible_buf = ""
            emitted_len = 0

            async for token in _stream_completion(self.messages):
                accumulated += token

                # 过滤 think 标签
                visible = THINK_RE.sub("", accumulated)

                # 屏蔽未完成的 <tool_call> 或 <think>
                for marker in ("<tool_call", "<think"):
                    idx = visible.rfind(marker)
                    if idx != -1 and ">" not in visible[idx:]:
                        visible = visible[:idx]

                tool_idx = visible.find("<tool_call>")
                if tool_idx != -1:
                    visible = visible[:tool_idx]

                new_text = visible[emitted_len:]
                if new_text and on_text:
                    await on_text(new_text)
                emitted_len = len(visible)

            # ── 检查是否有工具调用 ────────────────────────
            clean = _strip_think(accumulated)
            tc = _parse_tool_call(clean)

            if tc is None:
                # 没有工具调用 → 最终回复
                self.messages.append({"role": "assistant", "content": clean})
                return clean

            # ── 有工具调用 ────────────────────────────────
            name = tc["name"]
            args = tc["arguments"]

            if on_tool_call:
                await on_tool_call(name, args)

            # 将 assistant 消息（含 XML tool call）加入历史
            self.messages.append({"role": "assistant", "content": clean})

            # 执行工具（dry-run 模式下先审批）
            success, output = self.executor.execute(name, args)

            # 处理待审批的写操作
            if output.startswith("__PENDING_WRITE__"):
                lines = output.split("\n", 2)
                path_line = lines[1] if len(lines) > 1 else ""
                diff_text = lines[2] if len(lines) > 2 else ""

                approved = True
                if on_pending:
                    approved = await on_pending(path_line, diff_text)

                if approved:
                    # 实际执行写操作
                    self.executor.auto_approve = True
                    success, output = self.executor.execute(name, args)
                    self.executor.auto_approve = self.auto_approve
                else:
                    output = "用户拒绝了此操作。"
                    success = False

            if on_tool_result:
                await on_tool_result(name, success, output)

            # 将工具结果加入历史
            self.messages.append({
                "role": "user",
                "content": f"<tool_response>\n{output}\n</tool_response>",
            })

        return "（已达到最大工具调用轮次）"