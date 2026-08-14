import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_direct_vllm_launcher_defaults_to_prompt_tool_transport():
    script = (ROOT / "scripts" / "mcodex-vllm.ps1").read_text(encoding="utf-8")

    match = re.search(
        r'\[string\]\$ToolTransport\s*=\s*"(?P<transport>[^"]+)"',
        script,
    )

    assert match is not None
    assert match.group("transport") == "prompt"
    assert '$env:CODEX_TOOL_TRANSPORT = $ToolTransport' in script
