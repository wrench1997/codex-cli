param(
    [string]$BaseUrl = "http://112.111.7.91:7980/v1",
    [string]$Model = "DeepSeek-V4-Flash-0731",
    [string]$ApiKey = "",
    [ValidateSet("native", "prompt", "hybrid")]
    [string]$ToolTransport = "prompt",
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)

# Resolve the API key sent as "Authorization: Bearer <key>" by the CLI.
# Priority: -ApiKey param > GENVIDEOS_API_KEY env > CODEX_API_KEY env
# (non-dummy value) > unset (fall through to the project .env, or the CLI
# default "dummy" which omits the Authorization header for plain vLLM
# servers that require no auth).
# Recommended: keep the real key in the user-level GENVIDEOS_API_KEY
# environment variable (setx GENVIDEOS_API_KEY <key>) so it never lands in
# shell history or the process command line.
if (-not [string]::IsNullOrWhiteSpace($ApiKey)) {
    $KeySource = "-ApiKey param"
} elseif ($env:GENVIDEOS_API_KEY) {
    $ApiKey = $env:GENVIDEOS_API_KEY
    $KeySource = "GENVIDEOS_API_KEY"
} elseif ($env:CODEX_API_KEY -and $env:CODEX_API_KEY -ne "dummy") {
    $ApiKey = $env:CODEX_API_KEY
    $KeySource = "CODEX_API_KEY"
} else {
    # Leave CODEX_API_KEY unset so the project .env (loaded by config.py
    # with CODEX_ENV_OVERRIDE=false) can supply the real key; otherwise the
    # CLI falls back to "dummy" and omits the Authorization header.
    $ApiKey = ""
    $KeySource = ".env / no-auth fallback"
}
if ($KeySource -ne "-ApiKey param") {
    Write-Host ("[INFO] API key source: {0}" -f $KeySource)
}

# Prevent the project .env from replacing this launcher's profile values.
$env:CODEX_ENV_OVERRIDE = "false"
$env:CODEX_API_BASE = $BaseUrl
$env:CODEX_API_MODE = "chat"
if ($ApiKey) {
    $env:CODEX_API_KEY = $ApiKey
} elseif ($env:CODEX_API_KEY) {
    # Clear any stale session value so .env can supply the key.
    Remove-Item Env:\CODEX_API_KEY -ErrorAction SilentlyContinue
}
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

$ChildScript = Join-Path $PSScriptRoot "mcodex.ps1"
# 在企业机/加固环境中当前会话可能是 AllSigned。这个启动器是用户
# 明确调用的本地入口，子脚本仍需显式绕过策略才能运行；不要依赖
# 外层 powershell 的执行策略继承行为。
$PowerShellCommand = Get-Command pwsh -ErrorAction SilentlyContinue
if (-not $PowerShellCommand) {
    $PowerShellCommand = Get-Command powershell.exe -ErrorAction Stop
}
& $PowerShellCommand.Source -NoProfile -ExecutionPolicy Bypass -File $ChildScript @Arguments
exit $LASTEXITCODE
