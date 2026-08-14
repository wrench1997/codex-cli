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

& (Join-Path $PSScriptRoot "mcodex.ps1") @Arguments
exit $LASTEXITCODE
