# codex.py - 完整重写
#!/usr/bin/env python3
"""
Codex CLI - Chat + Agent 持续对话模式
支持多轮上下文保留的 AI 聊天，以及自动工具调用。

用法:
    python codex.py                          # 交互式 REPL（默认）
    python codex.py "帮我重构 main.py"        # 单次任务后进入 REPL
    python codex.py -y "修复所有 TODO"        # 自动审批模式
    python codex.py --dir /path/to/project   # 指定工作目录
    python codex.py --no-agent               # 纯聊天模式（不加载工具）
"""

import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from typing import Any, AsyncIterator, Optional

# 用于 Esc 键取消生成的平台特定导入
if sys.platform.startswith("win"):
    import msvcrt
else:
    import termios
    import tty

import click
import httpx
from prompt_toolkit import PromptSession
from prompt_toolkit.clipboard.base import Clipboard, ClipboardData
from prompt_toolkit.filters import has_selection
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from src.codex.config import CONFIG
from src.codex.file_editor import list_directory, read_file
from src.codex.tools import TOOLS, ToolExecutor
from src.codex.mcp.manager import McpManager


    
# ──────────────────────────────────────────────
# 全局 Console
# ──────────────────────────────────────────────
console = Console()

# ──────────────────────────────────────────────
# 兼容性：UTF-8 + 控制字符清理
# ──────────────────────────────────────────────

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CTRL_RE = re.compile(r"[\r\b\x0c\x0e-\x1f\x7f]")

MAX_VISIBLE_STREAM_CHARS = 5000
MAX_PANEL_CHARS = 8000

def _sanitize_stream_text(text: str) -> str:
    text = ANSI_RE.sub("", text)
    return CTRL_RE.sub("", text)


def _char_width(ch: str) -> int:
    """
    估算终端显示宽度：
    - 中文 / 全角 / 大多数字符表情：2
    - 普通 ASCII：1
    - 组合附加符：0
    """
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("F", "W", "A"):
        return 2
    return 1


def _display_width(text: str) -> int:
    return sum(_char_width(ch) for ch in text)


def _slice_by_display_width(text: str, max_width: int) -> str:
    out = []
    width = 0
    for ch in text:
        w = _char_width(ch)
        if width + w > max_width:
            break
        out.append(ch)
        width += w
    return "".join(out)


def compact_text(text: str, limit: int = MAX_PANEL_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit // 2
    return (
        f"（内容过长，已折叠，总长度 {len(text):,} 字符）\n\n"
        f"{text[:head]}\n\n"
        f"... 省略中间内容 ...\n\n"
        f"{text[-tail:]}"
    )

def _panel(renderable, **kwargs):
    kwargs.setdefault("box", box.ASCII)
    return Panel(renderable, **kwargs)

# ──────────────────────────────────────────────
# Prompt Toolkit 样式
# ──────────────────────────────────────────────
PT_STYLE = Style.from_dict({
    "prompt":       "bold #00d7ff",
    "prompt.arrow": "bold #00d7ff",
    "":             "#cccccc",
})

HISTORY_FILE = os.path.expanduser("~/.codex_chat_history")


def _is_cmder() -> bool:
    return bool(
        os.environ.get("CMDER_ROOT")
        or os.environ.get("ConEmuPID")
        or os.environ.get("ConEmuANSI")
    )


IS_CMDER = _is_cmder()




# 强制禁用 VT100 输出，使用传统的 Win32 API
if sys.platform == "win32" and _is_cmder():
    print("禁用VT100")
    os.environ["PROMPT_TOOLKIT_NO_VT100"] = "1"
    
    

# ==================== 新增以下几行 ====================
if IS_CMDER:
    # 强制让 prompt_toolkit 不使用 ConEmu 的 ANSI 注入器
    # 这通常能解决 Cmder 下中文光标乱跳的问题
    os.environ["PROMPT_TOOLKIT_NO_CONEMU_ANSI"] = "1"
    

def _copy_to_system_clipboard(text: str) -> None:
    """尽量把文本写入系统剪贴板。"""
    if not text:
        return

    # 优先 pyperclip（如果你装了）
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return
    except Exception:
        pass

    # 兜底：tkinter
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return
    except Exception:
        pass


def _read_from_system_clipboard() -> str:
    """尽量从系统剪贴板读取文本。"""
    try:
        import pyperclip  # type: ignore
        return pyperclip.paste() or ""
    except Exception:
        pass

    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.update()
        try:
            return root.clipboard_get() or ""
        finally:
            root.destroy()
    except Exception:
        return ""


class SystemClipboard(Clipboard):
    """prompt_toolkit 剪贴板后端，连接系统剪贴板。"""

    def __init__(self):
        self._cache = ""

    def set_data(self, data: ClipboardData) -> None:
        text = data.text or ""
        self._cache = text
        _copy_to_system_clipboard(text)

    def get_data(self) -> ClipboardData:
        text = _read_from_system_clipboard()
        if not text:
            text = self._cache
        else:
            self._cache = text
        return ClipboardData(text=text)


SYSTEM_CLIPBOARD = SystemClipboard()

# ──────────────────────────────────────────────
# 正则
# ──────────────────────────────────────────────
THINK_RE = re.compile(r".*?", re.S)
TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*<function=(?P<name>[^>]+)>\s*(?P<body>.*?)</function>\s*</tool_call>",
    re.S,
)
PARAM_RE = re.compile(r"<parameter=(?P<name>[^>]+)>\s*(?P<value>.*?)</parameter>", re.S)


def _strip_think(text: str) -> str:
    return THINK_RE.sub("", text).strip()


def _safe_emit(accumulated: str) -> str:
    """
    流式安全文本提取：去掉 think 块，屏蔽未闭合的 <think>/<tool_call> 残缺片段。
    """
    text = THINK_RE.sub("", accumulated)

    # 屏蔽未闭合的 <think>
    idx = text.rfind("<think>")
    if idx != -1 and "</think>" not in text[idx:]:
        text = text[:idx]

    # 屏蔽 <tool_call> 及之后的全部内容
    tool_idx = text.find("<tool_call")
    if tool_idx != -1:
        text = text[:tool_idx]

    # 屏蔽末尾截断的标签片段
    partials = [
        "<tool_call", "<tool_cal", "<tool_ca", "<tool_c", "<tool_",
        "<tool", "<too", "<to", "<t",
        "<think", "<thin", "<thi", "<th",
    ]
    for p in partials:
        if text.endswith(p):
            text = text[:-len(p)]
            break

    return text


def _normalize_api_base(api_base: str) -> str:
    base = (api_base or "").rstrip("/")
    for suffix in ("/v1/responses", "/v1/chat/completions", "/responses", "/chat/completions"):
        if base.endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break
    if not base.endswith("/v1"):
        base += "/v1"
    return base


def _parse_tool_call(text: str) -> Optional[dict]:
    m = TOOL_CALL_RE.search(text)
    if not m:
        return None
    name = m.group("name").strip()
    body = m.group("body")
    args: dict[str, Any] = {}
    for p in PARAM_RE.finditer(body):
        raw = p.group("value").strip()
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


def _extract_function_call(item: dict) -> tuple[str, dict[str, Any], Optional[str]]:
    name = item.get("name")
    if not name and isinstance(item.get("function"), dict):
        name = item["function"].get("name")

    raw_args = item.get("arguments", "{}")
    if not raw_args and isinstance(item.get("function"), dict):
        raw_args = item["function"].get("arguments", "{}")

    call_id = item.get("call_id") or item.get("id")

    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
        except json.JSONDecodeError:
            args = {}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}

    return name or "", args, call_id


# ──────────────────────────────────────────────
# UI 工具函数
# ──────────────────────────────────────────────

BANNER = """
+--------------------------------------------------+
| Codex Chat - AI Coding Assistant                 |
| 持续对话 · 上下文记忆 · 工具调用                 |
| /help 查看命令   Ctrl+D 退出                     |
+--------------------------------------------------+
"""

HELP_TEXT = """
## 可用命令

| 命令 | 说明 |
|------|------|
| `/help`         | 显示此帮助 |
| `/reset`        | 清空对话历史（保留系统提示） |
| `/history`      | 查看对话历史摘要 |
| `/ls [path]`    | 列出目录结构 |
| `/cat <file>`   | 查看文件内容 |
| `/cd <dir>`     | 切换工作目录 |
| `/approve`      | 切换自动审批模式 |
| `/model`        | 显示当前模型和配置 |
| `/tokens`       | 估算当前上下文 token 数 |
| `/mode`         | 切换 chat/agent 模式 |
| `/tools`        | 显示可用工具列表 |
| `/mcp`          | 显示 MCP 服务加载状态 |
| `/billing`      | 显示当天计费统计 |
| `/memory`       | 查看当前提炼的核心记忆点 |
| `/compress`     | 手动压缩并归纳历史上下文 |
| `/exit`         | 退出 |

## 输入技巧

- **多行输入**: 按 `Esc+Enter` 换行，`Enter` 发送
- **粘贴多行**: 按 `Ctrl+V` 粘贴剪贴板内容（支持多行）
- **历史**: 上下箭头翻历史
- **取消生成**: `Ctrl+C`

## 模式说明

- **agent 模式**（默认）: AI 可以读写文件、执行命令
- **chat 模式**: 纯对话，不调用工具，适合讨论思路
"""


def print_separator(title: str = "", style: str = "dim"):
    if title:
        console.print(f"\n--- {title} ---", style=style)
    else:
        console.print("\n" + "-" * 80, style=style)


def print_user_bubble(text: str):
    """显示用户消息气泡。"""
    console.print()
    console.print(_panel(
        Text(text, style="white"),
        title="You",
        title_align="right",
        border_style="#00d7ff",
        padding=(0, 1),
    ))


def print_tool_call_panel(name: str, args: dict):
    """显示工具调用卡片。"""
    args_lines = []
    for k, v in args.items():
        v_str = repr(v) if not isinstance(v, str) else v
        v_str = _sanitize_stream_text(v_str)
        if len(v_str) > 120:
            v_str = v_str[:117] + "..."
        args_lines.append(f"  {k} = {v_str}")
    body = "\n".join(args_lines) if args_lines else "  (no args)"
    console.print(_panel(
        body,
        title=f"Tool: {name}",
        border_style="yellow",
        padding=(0, 1),
    ))


def print_tool_result_panel(name: str, success: bool, output: str):
    """显示工具结果卡片。"""
    icon = "SUCCESS" if success else "FAILED"
    border = "green" if success else "red"
    output = compact_text(output)

    # 检测是否含 diff
    if "@@" in output and ("---" in output or "+++" in output):
        lines = output.split("\n")
        pre = []
        diff_lines = []
        in_diff = False
        for line in lines:
            if not in_diff and (line.startswith("---") or line.startswith("@@")):
                in_diff = True
            (diff_lines if in_diff else pre).append(line)

        if pre:
            console.print(_panel(
                "\n".join(pre),
                title=f"{icon}: {name}",
                border_style=border,
                padding=(0, 1),
            ))
        if diff_lines:
            syntax = Syntax(compact_text("\n".join(diff_lines)), "diff", theme="monokai")
            console.print(_panel(syntax, title="Diff preview", border_style="yellow"))
        return

    # 截断过长输出
    lines = output.splitlines()
    if len(lines) > 50:
        shown = (
            "\n".join(lines[:25])
            + f"\n\n[dim]... 省略 {len(lines) - 50} 行 ...[/dim]\n\n"
            + "\n".join(lines[-25:])
        )
    else:
        shown = output

    console.print(_panel(
        shown,
        title=f"{icon}: {name}",
        border_style=border,
        padding=(0, 1),
    ))


def print_diff_panel(path_line: str, diff_text: str):
    console.print(_panel(
        Text(path_line, style="bold"),
        title="Pending file",
        border_style="yellow",
    ))
    if diff_text.strip():
        syntax = Syntax(compact_text(diff_text), "diff", theme="monokai")
        console.print(_panel(syntax, title="Diff preview", border_style="yellow"))


async def ask_approval(path_line: str, diff_text: str) -> tuple[bool, Optional[str]]:
    """交互式询问用户是否批准文件修改。
    返回 (是否批准，拒绝原因)。
    """
    print_diff_panel(path_line, diff_text)
    console.print(
        "\n  [bold]是否应用此修改？[/bold] "
        "[[green]y[/green]]es / [[red]n[/red]]o / [[yellow]a[/yellow]]ll(全部同意): ",
        end="",
    )
    try:
        loop = asyncio.get_running_loop()
        answer = await loop.run_in_executor(None, sys.stdin.readline)
        answer = answer.strip().lower()
        
        if answer in ("y", "yes", "a", ""):
            return True, None
        elif answer in ("n", "no"):
            # 用户拒绝，询问原因
            console.print(
                "\n  [bold yellow]请输入拒绝原因（可选，直接回车跳过）：[/bold yellow] ",
                end="",
            )
            reason = await loop.run_in_executor(None, sys.stdin.readline)
            reason = reason.strip()
            return False, reason if reason else None
        else:
            return True, None
    except (EOFError, KeyboardInterrupt):
        return False, None


# ──────────────────────────────────────────────
# 流式输出渲染器
# ──────────────────────────────────────────────

class StreamRenderer:
    """
    管理 AI 回复的流式渲染。
    重点优化：
    - 批量输出，减少 prompt_toolkit 重绘频率
    - cmder 下更稳
    """

    def __init__(
        self,
        max_visible_chars: int = MAX_VISIBLE_STREAM_CHARS,
        flush_chars: int = 48 if not IS_CMDER else 96,
        flush_interval: float = 0.03 if not IS_CMDER else 0.08,
    ):
        self._buf = []
        self._started = False
        self._visible_width = 0
        self._total_len = 0
        self._truncated = False
        self._max_visible_chars = max_visible_chars

        self._pending_text = ""
        self._pending_width = 0
        self._last_flush = time.monotonic()
        self._flush_chars = flush_chars
        self._flush_interval = flush_interval

    def start(self):
        if not self._started:
            console.print()
            console.print("[bold green]Codex[/bold green] ", end="")
            self._started = True

    def _flush_pending(self):
        if not self._pending_text:
            return

        # 用 prompt_toolkit 友好的方式输出，避免和输入行抢光标
        print_formatted_text(self._pending_text, end="")

        self._buf.append(self._pending_text)
        self._visible_width += self._pending_width

        self._pending_text = ""
        self._pending_width = 0
        self._last_flush = time.monotonic()

    def feed(self, token: str):
        token = _sanitize_stream_text(token)
        if not token:
            return

        self._total_len += len(token)

        if not self._started:
            self.start()

        if self._truncated:
            return

        remain = self._max_visible_chars - (self._visible_width + self._pending_width)
        if remain <= 0:
            self._flush_pending()
            self._truncated = True
            console.print()
            console.print(f"[dim]（输出过长，已折叠，总长度 {self._total_len:,} 字符）[/dim]")
            return

        chunk = _slice_by_display_width(token, remain)
        if not chunk:
            return

        self._pending_text += chunk
        self._pending_width += _display_width(chunk)

        now = time.monotonic()
        should_flush = (
            "\n" in chunk
            or len(self._pending_text) >= self._flush_chars
            or (now - self._last_flush) >= self._flush_interval
        )

        if should_flush:
            self._flush_pending()

        if _display_width(token) > remain:
            self._truncated = True
            self._flush_pending()
            console.print()
            console.print(f"[dim]（输出过长，已折叠，总长度 {self._total_len:,} 字符）[/dim]")

    def finish(self) -> str:
        self._flush_pending()
        if self._started:
            console.print()
        return "".join(self._buf).strip()

    def reset(self):
        self._buf = []
        self._started = False
        self._visible_width = 0
        self._total_len = 0
        self._truncated = False
        self._pending_text = ""
        self._pending_width = 0
        self._last_flush = time.monotonic()


# ──────────────────────────────────────────────
# Chat Agent
# ──────────────────────────────────────────────

class ChatAgent:
    """
    持续对话的 Chat + Agent。
    - 维护完整对话历史（input_items）
    - 支持工具调用循环
    - 支持 agent/chat 两种模式
    """

    def __init__(
        self,
        workdir: str,
        auto_approve: bool = False,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        agent_mode: bool = True,
        mcp_manager: Optional[McpManager] = None,
        vfs_mode: bool = False,
    ):
        self.workdir = workdir
        self.auto_approve = auto_approve
        self.agent_mode = agent_mode
        self.mcp_manager = mcp_manager
        self.vfs_mode = vfs_mode  # 虚拟文件系统模式
        self.executor = ToolExecutor(workdir, auto_approve=auto_approve, mcp_manager=mcp_manager, vfs_mode=vfs_mode)

        self.api_base = _normalize_api_base(api_base or CONFIG.api_base)
        self.model = model or CONFIG.model

        # 统计
        self.turn_count = 0
        self.tool_call_count = 0

        # 系统提示
        system_content_parts = [
            f"You are Codex, an expert AI coding assistant embedded in a developer's terminal. "
            f"You have access to the user's codebase and can read, write, search, and modify files. "
            f"You maintain context across the entire conversation. "
            f"Always prefer minimal, targeted edits over full rewrites. "
            f"Explain your reasoning and actions in Chinese. "
            f"Be concise but thorough. "
            f"When the user asks follow-up questions, refer to the previous context naturally. "
            f"IMPORTANT: Your current working directory is: {workdir}. "
            f"All file operations and shell commands should use this directory as the root. "
            f"When executing shell commands, you do NOT need to specify the working directory - "
            f"commands will automatically run in {workdir}. "
            f"If you encounter a question you cannot answer or a task you cannot complete, "
            f"be honest and say so directly. Do not make up answers or give vague responses. "
            f"Instead, clearly state what you don't know, and invite the user to provide more context "
            f"or offer their own solution. It's okay to admit limitations."
        ]

        # 读取 agent/skills.md 作为额外的技能提示词（如果存在）
        skills_path = os.path.join(workdir, "agent", "skills.md")
        if os.path.exists(skills_path):
            try:
                with open(skills_path, "r", encoding="utf-8") as f:
                    skills_content = f.read()
                if skills_content.strip():
                    system_content_parts.append(
                        f"\n\n## Additional Skills and Instructions\n\n{skills_content}"
                    )
            except Exception:
                # 如果读取失败，静默忽略
                pass

        self._system_content = "".join(system_content_parts)

        self.system_item = {
            "type": "message",
            "role": "system",
            "content": self._system_content,
        }

        # 完整对话历史（包含 system）
        self.input_items: list[dict] = [self.system_item]
        
        # 长期记忆（上下文压缩后生成的核心记忆点）
        self.memory_summary = ""

    # ── 历史管理 ──────────────────────────────────────────

    def reset(self):
        """清空历史，保留 system 消息。"""
        self.input_items = [self.system_item]
        self.turn_count = 0
        self.tool_call_count = 0

    def add_user(self, text: str):
        self.input_items.append({
            "type": "message",
            "role": "user",
            "content": text,
        })

    def add_assistant(self, text: str):
        self.input_items.append({
            "type": "message",
            "role": "assistant",
            "content": text,
        })

    def add_tool_result(self, call_id: Optional[str], output: str):
        self.input_items.append({
            "type": "function_call_output",
            "call_id": call_id or f"call_{int(time.time())}",
            "output": output,
        })

    def history_summary(self) -> str:
        """返回对话历史摘要。"""
        lines = [f"共 {len(self.input_items)} 条消息，{self.turn_count} 轮对话，{self.tool_call_count} 次工具调用\n"]
        for i, item in enumerate(self.input_items):
            role = item.get("role", item.get("type", "?"))
            content = item.get("content", item.get("output", ""))
            if isinstance(content, str):
                preview = content[:60].replace("\n", " ")
            else:
                preview = str(content)[:60]
            lines.append(f"  [{i:02d}] {role:20s} {preview!r}")
        return "\n".join(lines)

    def estimate_tokens(self) -> int:
        """粗略估算 token 数（按字符数/2 估算中文场景）。"""
        total_chars = sum(
            len(str(item.get("content", item.get("output", ""))))
            for item in self.input_items
        )
        return total_chars // 2

    # ── 记忆与上下文压缩 ──────────────────────────────────────

    async def _generate_summary(self, old_messages_text: str) -> str:
        """调用大模型，生成结构化记忆总结"""
        prompt = f"""你是一个 AI 架构师的记忆管理模块。请总结以下历史对话记录，提取对后续编程任务有用的核心信息。
要求尽可能简练，保留关键的文件路径、函数名、已经验证的结论和当前的报错信息。

请按以下结构输出：
1. 🎯 核心目标：用户最终想实现什么
2. ✅ 已完成工作：我们已经修改了哪些文件，执行了什么重要命令
3. 🚧 当前状态/卡点：最新的报错是什么，或者当前卡在哪个步骤
4. 🧠 关键记忆点：重要的全局变量、约定规则、环境信息

以下是需要压缩的历史记录：
--------------------
{old_messages_text}
--------------------
"""
        payload = {
            "model": self.model,
            "input": [{"type": "message", "role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.1,  # 总结任务需要低温度，保证客观真实
        }
        
        headers = {}
        if CONFIG.api_key and CONFIG.api_key != "dummy":
            headers["Authorization"] = f"Bearer {CONFIG.api_key}"

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{self.api_base}/responses",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                # 提取返回文本
                output_items = data.get("output", [])
                if output_items and output_items[0].get("content"):
                    return output_items[0]["content"][0]["text"]
        except Exception as e:
            return f"（压缩上下文失败，错误：{e}）"
            
        return "（未生成有效总结）"

    async def compress_context(self):
        """执行上下文压缩"""
        # 1. 至少要有一定数量的消息才进行压缩
        # 系统提示 (1) + 历史记忆 (1, 可选) + 要压缩的旧消息 + 保留的新消息
        keep_items = CONFIG.keep_recent_turns * 2  # 一轮对话通常包含一问一答，甚至包含工具结果
        if len(self.input_items) <= keep_items + 2:
            return

        # 2. 分离消息
        system_msg = self.input_items[0]
        # 找到最近的消息
        recent_msgs = self.input_items[-keep_items:]
        # 中间的是需要被压缩的旧消息
        old_msgs = self.input_items[1:-keep_items]
        
        # 将历史记忆转为文本格式供模型阅读
        history_lines = []
        for item in old_msgs:
            role = item.get("role", item.get("type", "unknown"))
            content = item.get("content", item.get("output", ""))
            # 过滤掉过长的 diff 和原始内容，只保留思路
            content_str = str(content)
            if len(content_str) > 1000:
                content_str = content_str[:1000] + "\n...(内容过长截断)..."
            history_lines.append(f"[{role}]: {content_str}")
        
        history_text = "\n\n".join(history_lines)

        # 3. 调用模型生成新的总结
        new_summary = await self._generate_summary(history_text)
        
        # 4. 如果之前已经有记忆了，把旧记忆合并到新记忆的开头（滚动迭代）
        if self.memory_summary:
            self.memory_summary = f"{new_summary}\n\n(上期残留记忆:\n{self.memory_summary[:500]})"
        else:
            self.memory_summary = new_summary

        # 5. 重构 input_items，将记忆作为一条特殊 System 消息注入
        memory_msg = {
            "type": "message",
            "role": "system",
            "content": f"【系统提示：之前的历史对话已压缩为核心记忆】\n\n{self.memory_summary}\n\n请在后续回答中基于上述记忆推进工作。"
        }
        
        self.input_items = [system_msg, memory_msg] + recent_msgs

    # ── HTTP 流式调用 ──────────────────────────────────────

    async def _stream_request(
        self,
        on_token: Any = None,   # async callback(str)
        cancel_event: Any = None,  # asyncio.Event - 用于取消生成
    ) -> tuple[str, Optional[dict]]:
        """
        调用 gateway /v1/responses，流式接收。
        返回 (visible_stream_text, final_response_dict)
        """
        payload = {
            "model": self.model,
            "input": self.input_items,
            "stream": True,
            "temperature": CONFIG.temperature,
        }

        if self.agent_mode:
            # 动态合并原生工具和 MCP 工具
            combined_tools = TOOLS.copy()
            if self.mcp_manager:
                mcp_tools = self.mcp_manager.get_all_tools()
                if mcp_tools:
                    combined_tools.extend(mcp_tools)
            payload["tools"] = combined_tools

        headers = {}
        if CONFIG.api_key and CONFIG.api_key != "dummy":
            headers["Authorization"] = f"Bearer {CONFIG.api_key}"

        stream_parts: list[str] = []
        final_response: Optional[dict] = None

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.api_base}/responses",
                    json=payload,
                    headers=headers,
                ) as resp:
                    resp.raise_for_status()

                    async for line in resp.aiter_lines():
                        # 检查取消事件
                        if cancel_event and cancel_event.is_set():
                            raise asyncio.CancelledError("用户取消了生成")
                        
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            evt = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        etype = evt.get("type", "")

                        if etype == "response.output_text.delta":
                            delta = evt.get("delta", "")
                            if delta:
                                stream_parts.append(delta)
                                if on_token:
                                    await on_token(delta)

                        elif etype == "response.failed":
                            err = evt.get("error", "Unknown error")
                            raise RuntimeError(
                                json.dumps(err, ensure_ascii=False)
                                if isinstance(err, dict) else str(err)
                            )

                        elif etype == "response.completed":
                            final_response = evt.get("response")

        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"HTTP {e.response.status_code}: {e.response.text[:200]}")

        return "".join(stream_parts), final_response

    # ── 核心 turn 逻辑 ────────────────────────────────────

    async def run_turn(
        self,
        on_token: Any = None,         # async callback(str) - 流式 token
        on_tool_call: Any = None,     # async callback(name, args)
        on_tool_result: Any = None,   # async callback(name, success, output)
        on_pending: Any = None,       # async callback(path_line, diff_text) -> tuple[bool, Optional[str]]
        cancel_event: Any = None,     # asyncio.Event - 用于取消生成
    ) -> str:
        """
        执行一个完整的对话轮次。
        - 支持多次工具调用循环
        - 自动将工具结果追加进历史
        - 返回最终文本回复
        """
        # ==== 新增：在每轮开始前检查是否需要压缩上下文 ====
        current_tokens = self.estimate_tokens()
        if current_tokens > CONFIG.max_context_tokens:
            console.print(f"\n[bold yellow]⚠️ 当前上下文达到 {current_tokens:,} tokens，正在进行记忆压缩与归纳...[/bold yellow]")
            await self.compress_context()
            console.print("[bold green]✅ 记忆压缩完成，已释放多余上下文！[/bold green]\n")
        # ===================================================
        
        self.turn_count += 1

        for _loop in range(CONFIG.max_turns):
            # ── 流式调用模型 ──────────────────────────────
            stream_text, final_response = await self._stream_request(on_token=on_token, cancel_event=cancel_event)
            visible_text = _strip_think(stream_text)

            # ── 解析工具调用 ──────────────────────────────
            output_items = (final_response or {}).get("output", [])
            tool_calls = [
                item for item in output_items
                if item.get("type") == "function_call"
            ]

            # 没有工具调用 → 这轮结束
            if not tool_calls:
                # 把 assistant 回复加入历史
                self.add_assistant(visible_text)
                return visible_text

            # ── 有工具调用 ────────────────────────────────
            # 先把 assistant 消息（含 XML 表示的工具调用）加入历史
            xml_blocks = []
            for item in tool_calls:
                name, args, _cid = _extract_function_call(item)
                xml_blocks.append(_build_xml_tool_call(name, args))

            combined = visible_text.strip()
            xml_str = "\n\n".join(xml_blocks)
            if xml_str:
                combined = f"{combined}\n\n{xml_str}" if combined else xml_str
            self.add_assistant(combined)

            # ── 逐个执行工具 ──────────────────────────────
            user_rejected = False  # 标记是否有用户拒绝的操作
            for item in tool_calls:
                name, args, call_id = _extract_function_call(item)
                self.tool_call_count += 1

                if on_tool_call:
                    await on_tool_call(name, args)

                success, output = await self.executor.execute(name, args)

                # 处理需要审批的写操作
                if output.startswith("__PENDING_WRITE__"):
                    lines_out = output.split("\n", 2)
                    path_line = lines_out[1] if len(lines_out) > 1 else ""
                    diff_text = lines_out[2] if len(lines_out) > 2 else ""

                    approved = True
                    reject_reason = None
                    if on_pending:
                        approved, reject_reason = await on_pending(path_line, diff_text)

                    if approved:
                        old_auto = self.executor.auto_approve
                        self.executor.auto_approve = True
                        success, output = await self.executor.execute(name, args)
                        self.executor.auto_approve = old_auto
                    else:
                        # 用户拒绝：直接跳出工具循环，回到正常对话
                        user_rejected = True
                        if reject_reason:
                            output = f"用户拒绝了此操作：{reject_reason}"
                        else:
                            output = "用户拒绝了此操作。"
                        success = False
                        # 把已拒绝的结果加入历史后，立即停止后续工具调用
                        self.add_tool_result(call_id, output)
                        if on_tool_result:
                            await on_tool_result(name, success, output)
                        break  # 跳出工具循环

                if on_tool_result:
                    await on_tool_result(name, success, output)

                # 把工具结果加入历史
                self.add_tool_result(call_id, output)

            # 如果用户拒绝了操作，直接结束这轮对话，让 AI 给用户回复空间
            if user_rejected:
                return f"\n[操作已取消] 等待你的进一步指示。"

            # 继续循环，让模型根据工具结果继续思考
            # 注意：on_token 不需要重置，下一轮会继续追加
            # 但为了 UI 区分，在下一轮开始前不重新打印 "Codex:" 前缀
            # （由调用方通过 on_token 控制）

        return "（已达到最大工具调用轮次）"


# ──────────────────────────────────────────────
# 内置命令处理
# ──────────────────────────────────────────────

async def handle_builtin(cmd: str, agent: ChatAgent) -> bool:
    """
    处理 / 开头的内置命令。
    返回 True 表示已处理，False 表示未识别。
    """
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        console.print(Markdown(HELP_TEXT))
        return True

    if command == "/reset":
        agent.reset()
        console.print(Panel(
            "对话历史已清空，开始全新对话。",
            title="重置完成",
            border_style="green",
        ))
        return True

    if command == "/history":
        console.print(Panel(
            agent.history_summary(),
            title="对话历史",
            border_style="cyan",
        ))
        return True

    if command == "/tokens":
        tokens = agent.estimate_tokens()
        console.print(Panel(
            f"估算 token 数（中文场景）: [bold]{tokens:,}[/bold]\n"
            f"历史消息条数: {len(agent.input_items)}\n"
            f"对话轮次: {agent.turn_count}",
            title="📊 上下文统计",
            border_style="cyan",
        ))
        return True

    if command in ("/exit", "/quit", "/q"):
        console.print("\n[bold cyan] 再见！感谢使用 Codex Chat。[/bold cyan]\n")
        sys.exit(0)

    if command == "/ls":
        path = os.path.join(agent.workdir, arg) if arg else agent.workdir
        try:
            tree = list_directory(path, depth=3)
            console.print(Panel(tree, title=f" {path}", border_style="cyan"))
        except Exception as e:
            console.print(f"  error {e}", style="red")
        return True

    if command == "/cat":
        if not arg:
            console.print("  error 用法: /cat <文件路径>", style="red")
            return True
        try:
            path = os.path.join(agent.workdir, arg)
            content = read_file(path)
            lines = content.splitlines()
            numbered = "\n".join(f"{i+1:4d} │ {l}" for i, l in enumerate(lines))
            syntax = Syntax(numbered, "text", theme="monokai", word_wrap=True)
            console.print(Panel(syntax, title=f"📄 {arg} ({len(lines)} 行)"))
        except FileNotFoundError as e:
            console.print(f"  error {e}", style="red")
        return True

    if command == "/cd":
        if not arg:
            console.print(f"  当前目录: [cyan]{agent.workdir}[/cyan]")
            return True
        new_dir = os.path.abspath(os.path.join(agent.workdir, arg))
        if os.path.isdir(new_dir):
            agent.workdir = new_dir
            agent.executor.workdir = new_dir
            console.print(f"工作目录: [cyan]{new_dir}[/cyan]")
        else:
            console.print(f"目录不存在: {new_dir}", style="red")
        return True

    if command == "/approve":
        agent.auto_approve = not agent.auto_approve
        agent.executor.auto_approve = agent.auto_approve
        status = "[green]开启[/green]" if agent.auto_approve else "[yellow]关闭[/yellow]"
        console.print(f"自动审批: {status}")
        return True

    if command == "/mode":
        if arg in ("agent", "chat"):
            agent.agent_mode = arg == "agent"
        mode_str = "[bold green]Agent[/bold green]（工具调用）" if agent.agent_mode else "[bold yellow]Chat[/bold yellow]（纯对话）"
        console.print(f"当前模式: {mode_str}")
        if not arg:
            console.print("  提示: /mode agent 或 /mode chat 切换")
        return True

    if command == "/model":
            console.print(Panel(
                f"模型：[bold]{agent.model}[/bold]\n"
                f"API:  [bold]{agent.api_base}[/bold]\n"
                f"温度：[bold]{CONFIG.temperature}[/bold]\n"
                f"最大轮次：[bold]{CONFIG.max_turns}[/bold]\n"
                f"自动审批：[bold]{'开启' if agent.auto_approve else '关闭'}[/bold]\n"
                f"模式：[bold]{'Agent' if agent.agent_mode else 'Chat'}[/bold]",
                title="配置信息",
                border_style="cyan",
            ))
            return True

    if command == "/tools":
        from tools import list_tools
        console.print(Panel(
            list_tools(),
            title="🛠️ 可用工具",
            border_style="green",
        ))
        return True

    if command == "/mcp":
        if agent.mcp_manager:
            servers = agent.mcp_manager.servers
            tools = agent.mcp_manager.get_all_tools()
            console.print(Panel(
                f"MCP 管理器：[green]已加载[/green]\n"
                f"服务器数量：[bold]{len(servers)}[/bold]\n"
                f"工具数量：[bold]{len(tools)}[/bold]\n\n"
                f"服务器列表:\n"
                + "\n".join(f"  • {name}: {'[green]运行中[/green]' if server.is_started() else '[red]已停止[/red]'}" 
                           for name, server in servers.items())
                + (f"\n\nMCP 工具列表:\n" + "\n".join(f"  • {tool.get('function', {}).get('name', 'unknown')}" for tool in tools) if tools else "\n[dim]暂无 MCP 工具[/dim]"),
                title="🔌 MCP 状态",
                border_style="cyan",
            ))
        else:
            console.print(Panel(
                "MCP 管理器：[red]未加载[/red]\n\n"
                "[dim]提示：使用 --mcp 或 --mcp-config 参数启动 MCP 服务[/dim]",
                title="🔌 MCP 状态",
                border_style="yellow",
            ))
        return True

    if command == "/billing":
        # 从本地 gateway 获取计费统计（固定从 localhost:8080 获取）
        try:
            import httpx
            gateway_base = "http://localhost:8080/v1"
            resp = httpx.get(f"{gateway_base}/billing", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                console.print(Panel(
                    f"请求次数：      [bold]{data.get('request_count', 0)}[/bold]\n"
                    f"缓存命中：      [bold]{data.get('cache_hit_count', 0)}[/bold] ({data.get('cache_hit_rate', 'N/A')})\n"
                    f"─ 输入 Token ─\n"
                    f"  总计：        [bold]{data.get('total_input_tokens', 0):,}[/bold]\n"
                    f"  普通输入：    {data.get('normal_input_tokens', 0):,}\n"
                    f"  缓存命中：    {data.get('cached_input_tokens', 0):,}\n"
                    f"─ 输出 Token ─\n"
                    f"  总计：        [bold]{data.get('total_output_tokens', 0):,}[/bold]\n"
                    f"─ 费用明细 ─\n"
                    f"  输入费用：    ¥{data.get('input_cost', '0.000000')}\n"
                    f"  输出费用：    ¥{data.get('output_cost', '0.000000')}\n"
                    f"  ───────────────────\n"
                    f"  实际总费用：  [bold green]¥{data.get('total_cost', '0.000000')}[/bold green]\n"
                    f"  原始总费用：  ¥{data.get('original_total', '0.000000')}\n"
                    f"  💵 缓存节省： [bold green]¥{data.get('saved_cost', '0.000000')}[/bold green] ({data.get('saved_rate', '0%')})",
                    title="💰 当天计费统计",
                    border_style="yellow",
                ))
            else:
                console.print(f"  [red]获取计费信息失败：HTTP {resp.status_code}[/red]")
        except Exception as e:
            console.print(f"  [red]获取计费信息失败：{e}[/red]")
            console.print("  [dim]提示：确保 codex_gateway.py 正在运行（python -m uvicorn codex_gateway:app --host 0.0.0.0 --port 8080）[/dim]")
        return True

    if command == "/memory":
        if agent.memory_summary:
            console.print(Panel(
                agent.memory_summary,
                title="🧠 当前核心记忆",
                border_style="magenta"
            ))
        else:
            console.print("  [dim]当前没有记录长期记忆。[/dim]")
        return True

    if command == "/compress":
        console.print("[yellow]手动触发记忆压缩中...[/yellow]")
        await agent.compress_context()
        console.print("[green]压缩完成！使用 /memory 查看提取的关键记忆点。[/green]")
        return True

    return False


# ──────────────────────────────────────────────
# REPL 主循环
# ──────────────────────────────────────────────

async def repl(agent: ChatAgent, initial_task: Optional[str] = None):
    """
    持续对话的 REPL 主循环。
    支持多行输入（Esc+Enter 换行）和 Ctrl+V 粘贴多行。
    """
    # 配置 prompt_toolkit key bindings
    # 默认 Enter 发送，Esc+Enter 换行（类似 ChatGPT web 界面）
    kb = KeyBindings()
    
    # 状态标志：跟踪用户是否移动过光标（用于决定上下键是切换历史还是移动光标）
    cursor_moved = False
    last_key_was_arrow = False

    @kb.add("enter", filter=~has_selection)
    def _submit(event):
        """Enter 键提交消息。"""
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event):
        """escape-enter 换行。"""
        event.current_buffer.insert_text("\n")

    @kb.add("c-v")
    def _paste(event):
        """支持 Ctrl+V 粘贴多行文本。"""
        data = event.app.clipboard.get_data()
        event.current_buffer.paste_clipboard_data(data)

    @kb.add("up")
    def _history_up(event):
        """上键：
        - 如果光标没移动过：切换历史
        - 如果光标移动过但在第一行：切换历史
        - 否则：在文本内向上移动光标
        """
        nonlocal cursor_moved, last_key_was_arrow
        buffer = event.current_buffer
        
        # 检查是否在第一行（使用 cursor_position 和 document 计算）
        # cursor_position 是字符索引，需要通过 document 转换为行号
        doc = buffer.document
        at_first_line = doc.cursor_position_row == 0
        
        if not cursor_moved or at_first_line:
            # 切换到上一条历史
            buffer.history_backward(count=1)
            # 重置标志，因为已经切换到历史了
            cursor_moved = False
            last_key_was_arrow = True
        else:
            # 在文本内向上移动光标
            buffer.cursor_up()
            last_key_was_arrow = True

    @kb.add("down")
    def _history_down(event):
        """下键：
        - 如果光标没移动过：切换历史
        - 如果光标移动过但在最后一行：切换历史
        - 否则：在文本内向下移动光标
        """
        nonlocal cursor_moved, last_key_was_arrow
        buffer = event.current_buffer
        
        # 检查是否在最后一行（使用 document 获取行号）
        doc = buffer.document
        at_last_line = doc.cursor_position_row == doc.line_count - 1
        
        if not cursor_moved or at_last_line:
            # 切换到下一条历史
            buffer.history_forward(count=1)
            # 重置标志，因为已经切换到历史了
            cursor_moved = False
            last_key_was_arrow = True
        else:
            # 在文本内向下移动光标
            buffer.cursor_down()
            last_key_was_arrow = True

    @kb.add("left")
    def _cursor_left(event):
        """左键：移动光标，并标记已移动。"""
        nonlocal cursor_moved, last_key_was_arrow
        event.current_buffer.cursor_left()
        cursor_moved = True
        last_key_was_arrow = True

    @kb.add("right")
    def _cursor_right(event):
        """右键：移动光标，并标记已移动。"""
        nonlocal cursor_moved, last_key_was_arrow
        event.current_buffer.cursor_right()
        cursor_moved = True
        last_key_was_arrow = True

    @kb.add("home")
    def _cursor_home(event):
        """Home 键：移动到行首，并标记已移动。"""
        nonlocal cursor_moved
        event.current_buffer.cursor_home()
        cursor_moved = True

    @kb.add("end")
    def _cursor_end(event):
        """End 键：移动到行尾，并标记已移动。"""
        nonlocal cursor_moved
        event.current_buffer.cursor_end()
        cursor_moved = True

    def _reset_cursor_flag():
        """重置光标移动标志（在每次新输入开始时调用）。"""
        nonlocal cursor_moved, last_key_was_arrow
        cursor_moved = False
        last_key_was_arrow = False

    session = PromptSession(
        history=FileHistory(HISTORY_FILE),
        style=PT_STYLE,
        key_bindings=kb,
        multiline=True,           # 支持多行输入和粘贴
        wrap_lines=True,
        enable_history_search=False,  # 禁用默认历史搜索，使用自定义逻辑
        clipboard=SYSTEM_CLIPBOARD,  # 使用系统剪贴板
    )

    # 全局取消事件 - 用于在 AI 生成期间按 Esc 取消
    cancel_event: Optional[asyncio.Event] = None

    async def wait_for_cancel():
        """等待取消事件，当用户按下 Esc 时触发。"""
        nonlocal cancel_event
        if cancel_event:
            await cancel_event.wait()

    # 关键：让 prompt_toolkit 正确重绘 prompt，避免流式输出把输入行冲乱
    with patch_stdout(raw=True):
        # 打印欢迎界面
        console.print(BANNER, style="bold cyan")
        console.print(Panel(
            f"工作目录: [cyan]{agent.workdir}[/cyan]\n"
            f"模型:     [cyan]{agent.model}[/cyan]\n"
            f"API:      [cyan]{agent.api_base}[/cyan]\n"
            f"自动审批: {'[green]开启[/green]' if agent.auto_approve else '[yellow]关闭[/yellow]'}\n"
            f"模式:     [cyan]{'Agent（工具调用）' if agent.agent_mode else 'Chat（纯对话）'}[/cyan]\n\n"
            "[dim]Esc+Enter 换行  ·  Enter 发送  ·  Esc 取消生成  ·  /help 查看命令[/dim]",
            border_style="dim",
        ))
        console.print()

        # 如果有初始任务，先执行它
        if initial_task:
            await _process_message(session, agent, initial_task, from_arg=True)

# 主循环
        while True:
            try:
                # 显示提示符
                prompt_text = ">>> " if agent.agent_mode else "chat> "
                
                # 重置光标移动标志（每次新输入开始时）
                _reset_cursor_flag()
                
                # ================= 核心修改区域 =================
                if IS_CMDER:
                    # 降级方案：在 Cmder 下放弃 prompt_toolkit，使用原生 input
                    console.print(f"[bold #00d7ff]{prompt_text}[/bold #00d7ff]", end="")
                    loop = asyncio.get_running_loop()
                    # 规避阻塞，使用线程池运行原生 input
                    user_input = await loop.run_in_executor(None, input)
                else:
                    # 正常方案：其他终端继续使用高级多行输入
                    user_input = await session.prompt_async(prompt_text, style=PT_STYLE)
                # ================================================
                
            except KeyboardInterrupt:
                console.print("\n  [dim](Ctrl+C - 使用 /exit 或 Ctrl+D 退出)[/dim]")
                continue
            except EOFError:
                console.print("\n[bold cyan] 再见！[/bold cyan]\n")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # 内置命令处理：只有 "/ "（斜杠加空格）才当作命令，否则当作文本
            # 这样 "/help" 是命令，但 "/ 这个想法不错" 是普通文本
            if user_input.startswith("/ "):
                # 去掉开头的 "/ " 后作为命令处理
                cmd = user_input[1:].strip()  # 变成 "help" 或其他
                handled = await handle_builtin(cmd, agent)
                if not handled:
                    # 没有找到命令，当作文本处理
                    agent.add_user(user_input)
                    await _process_message(session, agent, user_input)
            elif user_input.startswith("/"):
                # 没有空格的 "/xxx" 形式，直接当命令处理
                handled = await handle_builtin(user_input, agent)
                if not handled:
                    console.print(
                        "  [yellow] 未知命令，输入 /help 查看所有命令[/yellow]"
                    )
            else:
                # AI 对话
                await _process_message(session, agent, user_input)


async def _process_message(
    session: PromptSession,
    agent: ChatAgent,
    user_input: str,
    from_arg: bool = False,
):
    """处理单条用户消息，驱动 Agent 完成回复。"""
    # 显示用户消息
    if not from_arg:
        print_user_bubble(user_input)
    else:
        console.print(Panel(
            user_input,
            title="[bold #00d7ff]任务[/bold #00d7ff]",
            border_style="#00d7ff",
        ))

    # 加入历史
    agent.add_user(user_input)

    # 流式渲染器
    renderer = StreamRenderer()
    # 标记是否在工具调用循环中（工具调用后不再重打前缀）
    in_tool_loop = False
    # 取消事件 - 用于 Esc 键取消生成
    cancel_event = asyncio.Event()
    # 标记是否正在生成
    is_generating = True

    async def listen_for_esc():
        """后台监听 Esc 键，用户按下时触发取消事件。"""
        nonlocal is_generating
        if sys.platform.startswith("win"):
            # Windows 平台
            while is_generating:
                if msvcrt.kbhit():
                    key = msvcrt.getwch()
                    if key == '\x1b' or key == '':  # Esc 键
                        cancel_event.set()
                        console.print("\n[yellow]  已取消生成[/yellow]")
                        break
                await asyncio.sleep(0.05)
        else:
            # Unix/Linux/Mac 平台
            import select
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                while is_generating:
                    if sys.stdin in select.select([sys.stdin], [], [], 0.05)[0]:
                        key = sys.stdin.read(1)
                        if key == '\x1b':  # Esc 键
                            cancel_event.set()
                            console.print("\n[yellow]  已取消生成[/yellow]")
                            break
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    async def on_token(token: str):
        nonlocal in_tool_loop
        if in_tool_loop:
            # 工具调用完成后，模型继续输出，重新开一个段落
            renderer.feed(token)
        else:
            renderer.feed(token)

    async def on_tool_call(name: str, args: dict):
        nonlocal in_tool_loop
        # 结束当前流式输出段
        partial = renderer.finish()
        renderer.reset()
        in_tool_loop = True
        # 打印工具调用卡片
        console.print()
        print_tool_call_panel(name, args)

    async def on_tool_result(name: str, success: bool, output: str):
        print_tool_result_panel(name, success, output)
        # 工具结果后，模型继续生成，重启渲染器
        renderer.reset()
        renderer.start()

    async def on_pending(path_line: str, diff_text: str) -> tuple[bool, Optional[str]]:
        return await ask_approval(path_line, diff_text)

    try:
        # 启动后台任务监听 Esc 键
        esc_listener_task = asyncio.create_task(listen_for_esc())
        
        final_text = await agent.run_turn(
            on_token=on_token,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
            on_pending=on_pending,
            cancel_event=cancel_event,
        )
        
        # 生成完成，停止监听
        is_generating = False
        esc_listener_task.cancel()
        try:
            await esc_listener_task
        except asyncio.CancelledError:
            pass

        # 结束流式输出
        renderer.finish()
        console.print()

        # 打印统计
        console.print(
            f"  [dim]第 {agent.turn_count} 轮 · "
            f"历史 {len(agent.input_items)} 条 · "
            f"~{agent.estimate_tokens():,} tokens[/dim]"
        )

    except asyncio.CancelledError:
        # 用户按 Esc 取消了生成
        renderer.finish()
        console.print()
        console.print("  [yellow]  已取消生成（历史仍保留）[/yellow]")
        # 停止监听
        is_generating = False
        # 移除最后加入的 user 消息
        if agent.input_items and agent.input_items[-1].get("role") == "user":
            last = agent.input_items[-1].get("content", "")
            if last == user_input:
                agent.input_items.pop()

    except KeyboardInterrupt:
        renderer.finish()
        console.print()
        console.print("  [yellow]  已中断生成（历史仍保留）[/yellow]")
        # 停止监听
        is_generating = False
        # 注意：被中断的回复不加入历史，避免历史污染
        # 移除最后加入的 user 消息
        if agent.input_items and agent.input_items[-1].get("role") == "user":
            # 检查是否是我们刚加的
            last = agent.input_items[-1].get("content", "")
            if last == user_input:
                agent.input_items.pop()

    except Exception as e:
        renderer.finish()
        console.print()
        console.print(Panel(
            f"[red]{e}[/red]",
            title=" 错误",
            border_style="red",
        ))
        # 停止监听
        is_generating = False
        # 同样移除污染的 user 消息
        if agent.input_items and agent.input_items[-1].get("role") == "user":
            last = agent.input_items[-1].get("content", "")
            if last == user_input:
                agent.input_items.pop()

    console.print()


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────

@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("task", nargs=-1)
@click.option("--dir", "-d", "workdir", default=None,
              help="工作目录（默认当前目录）")
@click.option("--yes", "-y", "auto_approve", is_flag=True, default=False,
              help="自动审批所有文件修改")
@click.option("--model", "-m", default=None,
              help="指定模型名称")
@click.option("--api", default="http://127.0.0.1:8080/v1",
              help="API 基地址（例如 http://127.0.0.1:8080/v1）")
@click.option("--no-agent", "no_agent", is_flag=True, default=False,
              help="纯聊天模式，不使用工具")
@click.option("--temperature", "-t", default=None, type=float,
              help="采样温度（默认 0.6）")
@click.option("--mcp", is_flag=True, default=False,
              help="从配置文件加载 MCP 服务（使用 mcp_config.yaml）")
@click.option("--mcp-config", type=str, default=None,
              help="指定 MCP 配置文件路径（默认：./mcp_config.yaml）")
@click.option("--vfs", "vfs_mode", is_flag=True, default=False,
              help="虚拟文件系统模式：自动启动 RJCut Studio Electron 应用并连接 MCP 服务器，屏蔽本地文件操作工具")
@click.option("--vfs-port", type=int, default=8001,
              help="VFS MCP 服务器端口（默认：8001）")
def main(task, workdir, auto_approve, model, api, no_agent, temperature, mcp, mcp_config, vfs_mode, vfs_port):
    """
    Codex Chat — 持续对话的 AI 编程助手

    支持多轮上下文记忆、工具调用（读写文件、执行命令）。
    不传 task 时进入交互式 REPL，传入 task 则先执行后继续对话。
    """
    # 更新配置
    if model:
        CONFIG.model = model
    if api:
        CONFIG.api_base = api
    if temperature is not None:
        CONFIG.temperature = temperature

    workdir = os.path.abspath(workdir or os.getcwd())

    async def _main_async():
        mcp_manager = None
        
        # ==================== VFS 模式：从配置文件加载并自动启动 Electron ====================
        if vfs_mode:
            console.print(f"\n[bold cyan]🚀 正在启动 VFS 模式（虚拟文件系统专业模式）...[/bold cyan]")
            console.print(f"[dim]  配置：从 mcp_config.yaml 加载 rjcut_vfs 服务器[/dim]")
            console.print(f"[dim]  功能：自动启动 Electron 应用 + 连接 MCP 服务器 + 屏蔽本地文件工具[/dim]\n")
            
            # 确定配置文件路径
            config_path = mcp_config
            if not config_path:
                # 优先查找项目根目录的 config 文件夹
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                config_path = os.path.join(project_root, "config", "mcp_config.yaml")
                if not os.path.exists(config_path):
                    # 尝试当前工作目录
                    config_path = os.path.join(workdir, "mcp_config.yaml")
                if not os.path.exists(config_path):
                    # 尝试脚本所在目录
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    config_path = os.path.join(script_dir, "mcp_config.yaml")
            
            if os.path.exists(config_path):
                console.print(f"[dim]  加载配置文件：{config_path}[/dim]")
                # 使用 VFS 模式加载配置（只加载 rjcut_vfs 服务器）
                mcp_manager = McpManager.from_config(config_path, vfs_mode=True)
                
                if mcp_manager.servers:
                    # 启动 MCP 服务器（会自动启动 Electron 应用）
                    console.print(f"[dim]  正在启动 MCP 服务器...[/dim]")
                    results = await mcp_manager.start_all()
                    success_count = sum(1 for v in results.values() if v)
                    
                    if success_count > 0:
                        all_tools = mcp_manager.get_all_tools()
                        console.print(f"\n[green]✅ VFS MCP 服务器已连接，加载了 {len(all_tools)} 个虚拟文件系统工具[/green]")
                        console.print(f"\n[bold green]📁 VFS 模式已激活！[/bold green]")
                        console.print(f"[dim]  - 本地文件操作工具已被屏蔽[/dim]")
                        console.print(f"[dim]  - 所有文件操作将通过虚拟文件系统执行[/dim]")
                        console.print(f"[dim]  - 可用工具：vfs_list, vfs_read, vfs_write, vfs_delete, vfs_move, vfs_copy, vfs_mkdir 等[/dim]\n")
                    else:
                        console.print("[yellow]⚠️  VFS MCP 服务器连接失败，将回退到普通模式[/yellow]")
                        mcp_manager = None
                else:
                    console.print("[yellow]⚠️  配置文件中未找到 rjcut_vfs 服务器配置[/yellow]")
            else:
                console.print(f"[red]❌ 配置文件不存在：{config_path}[/red]")
        
        # ==================== 普通 MCP 模式 ====================
        elif mcp or mcp_config:
            config_path = mcp_config
            if not config_path:
                # 优先查找项目根目录的 config 文件夹
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                config_path = os.path.join(project_root, "config", "mcp_config.yaml")
                if not os.path.exists(config_path):
                    # 尝试当前工作目录
                    config_path = os.path.join(workdir, "mcp_config.yaml")
                if not os.path.exists(config_path):
                    # 尝试脚本所在目录
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    config_path = os.path.join(script_dir, "mcp_config.yaml")
            
            console.print(f"[dim]正在从配置文件加载 MCP 服务：{config_path}[/dim]")
            mcp_manager = McpManager.from_config(config_path)
            
            if mcp_manager.servers:
                results = await mcp_manager.start_all()
                success_count = sum(1 for v in results.values() if v)
                if success_count > 0:
                    all_tools = mcp_manager.get_all_tools()
                    console.print(f"[green]✅ 成功启动 {success_count}/{len(mcp_manager.servers)} 个 MCP 服务器，共加载 {len(all_tools)} 个工具[/green]")
                else:
                    console.print("[yellow]⚠️  所有 MCP 服务器启动失败，将继续运行但不使用 MCP 功能[/yellow]")
                    mcp_manager = None
            else:
                console.print("[yellow]⚠️  配置文件中未找到启用的 MCP 服务器[/yellow]")

        try:
            agent = ChatAgent(
                workdir=workdir,
                auto_approve=auto_approve or CONFIG.auto_approve,
                api_base=CONFIG.api_base,
                model=CONFIG.model,
                agent_mode=not no_agent,
                mcp_manager=mcp_manager,
                vfs_mode=vfs_mode,  # 传递 VFS 模式标志
            )

            initial = " ".join(task) if task else None
            await repl(agent, initial_task=initial)
            
        finally:
            if mcp_manager:
                await mcp_manager.close_all()

    asyncio.run(_main_async())


if __name__ == "__main__":
    main()