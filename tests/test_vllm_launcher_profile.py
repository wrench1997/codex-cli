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


def test_vllm_launcher_supports_api_key_auth():
    script = (ROOT / "scripts" / "mcodex-vllm.ps1").read_text(encoding="utf-8")

    # The launcher must expose an -ApiKey parameter and forward it through
    # CODEX_API_KEY; the CLI sends it as "Authorization: Bearer <key>" for any
    # value other than "dummy".
    assert re.search(r"\[string\]\$ApiKey\s*=\s*\"\"", script) is not None
    assert re.search(r"if \(\$ApiKey\) \{\s*\r?\n\s*\$env:CODEX_API_KEY = \$ApiKey", script) is not None
    # Resolution order: -ApiKey > GENVIDEOS_API_KEY > CODEX_API_KEY (non-dummy)
    # > unset, so the project .env (CODEX_ENV_OVERRIDE=false) can supply the
    # real key; a stale session CODEX_API_KEY must be cleared in that case.
    assert "$env:GENVIDEOS_API_KEY" in script
    assert re.search(r"\$ApiKey = \"\"", script) is not None
    assert "Remove-Item Env:\\CODEX_API_KEY" in script
    # The project .env must not clobber the explicitly resolved key.
    assert '$env:CODEX_ENV_OVERRIDE = "false"' in script
