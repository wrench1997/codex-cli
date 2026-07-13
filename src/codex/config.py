# config.py
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    # 让直接执行 `codex` / `mcodex.ps1` 时也能读取项目根目录的 .env。
    # override=False：命令行或系统环境变量仍然拥有更高优先级。
    project_env = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(project_env, override=False)
except ImportError:
    # 保持对旧环境兼容；安装新版依赖后会自动启用 .env 加载。
    pass


@dataclass
class Config:
    api_base: str = os.environ.get("CODEX_API_BASE", "http://127.0.0.1:8080/v1")
    model: str = os.environ.get("CODEX_MODEL", "Qwen/Qwen3.5-397B-A17B-FP8")
    api_key: str = os.environ.get("CODEX_API_KEY", "dummy")
    temperature: float = float(os.environ.get("CODEX_TEMPERATURE", "0.6"))
    max_turns: int = int(os.environ.get("CODEX_MAX_TURNS", "50"))
    auto_approve: bool = os.environ.get("CODEX_AUTO_APPROVE", "false").lower() == "true"
    workspace: str = os.environ.get("CODEX_WORKSPACE", os.getcwd())

    # API 兼容模式：
    # - responses: 原生 OpenAI Responses API（中转站/官方接口）
    # - gateway:   旧 vLLM XML 工具网关
    # - auto:      优先尝试 responses，协议不兼容时回退 gateway
    api_mode: str = os.environ.get("CODEX_API_MODE", "auto").strip().lower()

    # GPT-5 系列及部分中转站不接受 temperature。默认在原生 Responses
    # 模式中不发送；旧 gateway 模式仍保持原行为。
    send_temperature: bool = os.environ.get("CODEX_SEND_TEMPERATURE", "false").lower() == "true"

    # 工具传输方式：
    # - native: 仅使用 Responses 原生 function calling
    # - prompt: 仅把工具 schema 注入提示词，并解析 XML 工具调用
    # - hybrid: 两者同时启用；适合会吞掉 tools 字段的中转站（推荐）
    tool_transport: str = os.environ.get("CODEX_TOOL_TRANSPORT", "hybrid").strip().lower()
    tool_choice: str = os.environ.get("CODEX_TOOL_CHOICE", "auto").strip().lower()
    debug_requests: bool = os.environ.get("CODEX_DEBUG_REQUESTS", "false").lower() == "true"
    
    # 新增：上下文压缩相关的配置
    max_context_tokens: int = int(os.environ.get("CODEX_MAX_CONTEXT_TOKENS", "140000"))  # 触发压缩的阈值
    keep_recent_turns: int = int(os.environ.get("CODEX_KEEP_RECENT_TURNS", "6"))      # 压缩时保留最近几轮对话不压缩

    def __post_init__(self):
        aliases = {
            "native": "responses",
            "openai": "responses",
            "legacy": "gateway",
            "vllm": "gateway",
        }
        self.api_mode = aliases.get(self.api_mode, self.api_mode)
        if self.api_mode not in {"auto", "responses", "gateway"}:
            raise ValueError(
                "CODEX_API_MODE 必须是 auto、responses 或 gateway，"
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
        if self.tool_choice not in {"auto", "required", "none"}:
            raise ValueError(
                "CODEX_TOOL_CHOICE 必须是 auto、required 或 none，"
                f"当前值：{self.tool_choice!r}"
            )


CONFIG = Config()