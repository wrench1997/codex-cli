param(
    [string]$BaseUrl = "http://112.111.7.91:7980/v1",
    [string]$Model = "DeepSeek-V4-Flash-0731",
    [ValidateSet("native", "prompt", "hybrid")]
    [string]$ToolTransport = "prompt",
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)

# Prevent the project .env from replacing this launcher's profile values.
$env:CODEX_ENV_OVERRIDE = "false"
$env:CODEX_API_BASE = $BaseUrl
$env:CODEX_API_MODE = "chat"
$env:CODEX_API_KEY = "dummy"
$env:CODEX_MODEL = $Model
$env:CODEX_TOOL_TRANSPORT = $ToolTransport
$env:CODEX_SEND_TEMPERATURE = "true"

# Context limits calibrated against the vLLM server.
# Server: max_model_len=131072 (128K actual tokens), KV cache ~499K tokens.
# The CLI's token estimate (len(json)//2) overestimates by ~4x for ASCII and
# ~1.5x for mixed Chinese+code content.  With CODEX_MAX_CONTEXT_TOKENS=100000,
# compression triggers at ~80K estimated = ~20-50K actual tokens, leaving
# plenty of room for output within the 128K limit.
$env:CODEX_MAX_CONTEXT_TOKENS = "100000"
$env:CODEX_CONTEXT_RESERVE_TOKENS = "20000"
$env:CODEX_KEEP_RECENT_TURNS = "8"

# Cap output tokens.  DeepSeek-V4-Flash is a thinking model: <think> uses
# output tokens.  16384 gives room for reasoning + response + tool call.
$env:CODEX_MAX_OUTPUT_TOKENS = "16384"

# Auto-retry streaming connection drops (incomplete chunked read, peer closed,
# or stream ending without [DONE] / finish_reason).
$env:CODEX_STREAM_RETRY_COUNT = "4"
$env:CODEX_STREAM_RETRY_DELAY = "1.0"

# Read timeout: if no data arrives for 120s, treat as dead connection and retry.
$env:CODEX_STREAM_READ_TIMEOUT = "120"

& (Join-Path $PSScriptRoot "mcodex.ps1") @Arguments
exit $LASTEXITCODE
