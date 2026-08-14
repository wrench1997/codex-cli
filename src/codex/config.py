# config.py
import os
from dataclasses import dataclass, field
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_codex_env() -> tuple[Path, ...]:
    """加载 mcodex 配置文件。

    默认让项目根目录 ``.env`` 覆盖 Windows 会话里残留的 CODEX_* 变量，
    这样修改文件后重新启动即可生效。需要保留系统环境变量优先级时，可在
    启动前设置 ``CODEX_ENV_OVERRIDE=false``。

    也可以通过 ``CODEX_ENV_FILE`` 指向另一份配置文件；显式文件最后加载，
    因而优先级最高。
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return ()

    project_root = Path(__file__).resolve().parents[2]
    candidates = [project_root / ".env"]

    explicit = os.environ.get("CODEX_ENV_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())

    override = _as_bool(os.environ.get("CODEX_ENV_OVERRIDE"), default=True)
    loaded: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate.absolute()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        load_dotenv(resolved, override=override)
        loaded.append(resolved)
    return tuple(loaded)


LOADED_ENV_FILES = _load_codex_env()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Config:
    api_base: str = field(default_factory=lambda: _env("CODEX_API_BASE", "http://127.0.0.1:8080/v1"))
    model: str = field(default_factory=lambda: _env("CODEX_MODEL", "DeepSeek-V4-Flash-0731"))
    api_key: str = field(default_factory=lambda: _env("CODEX_API_KEY", "dummy"))
    temperature: float = field(default_factory=lambda: float(_env("CODEX_TEMPERATURE", "0.6")))
    max_turns: int = field(default_factory=lambda: int(_env("CODEX_MAX_TURNS", "50")))
    auto_approve: bool = field(default_factory=lambda: _as_bool(os.environ.get("CODEX_AUTO_APPROVE")))
    workspace: str = field(default_factory=lambda: _env("CODEX_WORKSPACE", os.getcwd()))

    # API 兼容模式：
    # - responses: 原生 OpenAI Responses API
    # - chat:      OpenAI Chat Completions API
    # - gateway:   旧 vLLM XML 工具网关
    # - auto:      依次尝试 responses、chat、gateway
    api_mode: str = field(default_factory=lambda: _env("CODEX_API_MODE", "auto").strip().lower())

    # GPT-5 系列及部分中转站不接受 temperature。
    send_temperature: bool = field(default_factory=lambda: _as_bool(os.environ.get("CODEX_SEND_TEMPERATURE")))

    # 工具传输方式：
    # - native: 仅使用 API 原生 function calling
    # - prompt: 仅把工具 schema 注入提示词并解析文本工具调用（中转站推荐）
    # - hybrid: 两者同时启用
    tool_transport: str = field(default_factory=lambda: _env("CODEX_TOOL_TRANSPORT", "prompt").strip().lower())
    tool_choice: str = field(default_factory=lambda: _env("CODEX_TOOL_CHOICE", "auto").strip().lower())
    debug_requests: bool = field(default_factory=lambda: _as_bool(os.environ.get("CODEX_DEBUG_REQUESTS")))
    agent_refusal_retries: int = field(default_factory=lambda: int(_env("CODEX_AGENT_REFUSAL_RETRIES", "2")))

    max_context_tokens: int = field(default_factory=lambda: int(_env("CODEX_MAX_CONTEXT_TOKENS", "140000")))
    keep_recent_turns: int = field(default_factory=lambda: int(_env("CODEX_KEEP_RECENT_TURNS", "6")))
    # 给模型输出、工具 schema 和协议包装预留空间；达到这个预算前就压缩。
    context_reserve_tokens: int = field(default_factory=lambda: int(_env("CODEX_CONTEXT_RESERVE_TOKENS", "12000")))
    # 所有工具结果进入模型前的硬上限。UI 和模型看到相同的安全摘要。
    max_tool_output_chars: int = field(default_factory=lambda: int(_env("CODEX_MAX_TOOL_OUTPUT_CHARS", "24000")))
    max_tool_output_lines: int = field(default_factory=lambda: int(_env("CODEX_MAX_TOOL_OUTPUT_LINES", "500")))
    # read_file 默认分页，模型可用 start_line/end_line 继续读取后续内容。
    max_read_file_lines: int = field(default_factory=lambda: int(_env("CODEX_MAX_READ_FILE_LINES", "400")))
    tool_retry_budget: int = field(default_factory=lambda: int(_env("CODEX_TOOL_RETRY_BUDGET", "3")))

    def __post_init__(self):
        aliases = {
            "native": "responses",
            "openai": "responses",
            "chat_completions": "chat",
            "chat-completions": "chat",
            "completions": "chat",
            "legacy": "gateway",
            "vllm": "gateway",
        }
        self.api_mode = aliases.get(self.api_mode, self.api_mode)
        if self.api_mode not in {"auto", "responses", "chat", "gateway"}:
            raise ValueError(
                "CODEX_API_MODE 必须是 auto、responses、chat 或 gateway，"
                f"当前值：{self.api_mode!r}"
            )

        tool_aliases = {
            "xml": "prompt",
            "text": "prompt",
            "both": "hybrid",
            "compat": "hybrid",
        }
        self.tool_transport = tool_aliases.get(self.tool_transport, self.tool_transport)
        if self.tool_transport not in {"native", "prompt", "hybrid"}:
            raise ValueError(
                "CODEX_TOOL_TRANSPORT 必须是 native、prompt 或 hybrid，"
                f"当前值：{self.tool_transport!r}"
            )
        for name in (
            "max_context_tokens", "context_reserve_tokens", "max_tool_output_chars",
            "max_tool_output_lines", "max_read_file_lines",
            "tool_retry_budget",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} 必须是正整数")
        if self.tool_choice not in {"auto", "required", "none"}:
            raise ValueError(
                "CODEX_TOOL_CHOICE 必须是 auto、required 或 none，"
                f"当前值：{self.tool_choice!r}"
            )
        if self.agent_refusal_retries < 0:
            raise ValueError("CODEX_AGENT_REFUSAL_RETRIES 不能小于 0")


CONFIG = Config()
