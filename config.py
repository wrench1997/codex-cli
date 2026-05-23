# config.py
import os
from dataclasses import dataclass, field


@dataclass
class Config:
    api_base: str = os.environ.get("CODEX_API_BASE", "http://112.111.7.91:7980/v1")
    model: str = os.environ.get("CODEX_MODEL", "Qwen/Qwen3.5-397B-A17B-FP8")
    api_key: str = os.environ.get("CODEX_API_KEY", "dummy")
    temperature: float = float(os.environ.get("CODEX_TEMPERATURE", "0.6"))
    max_turns: int = int(os.environ.get("CODEX_MAX_TURNS", "50"))
    auto_approve: bool = os.environ.get("CODEX_AUTO_APPROVE", "false").lower() == "true"
    workspace: str = os.environ.get("CODEX_WORKSPACE", os.getcwd())


CONFIG = Config()