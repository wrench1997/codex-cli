# ============================================================
# Codex Gateway - PowerShell 启动脚本
# ============================================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Codex Gateway - Starting Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 加载 .env 文件中的环境变量
$envFile = Join-Path $PSScriptRoot "..\.env"
if (Test-Path $envFile) {
    Write-Host "[INFO] Loading environment variables from .env..." -ForegroundColor Yellow
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        # 跳过空行和注释
        if ($line -and $line -notmatch "^#") {
            $key, $value = $line -split "=", 2
            if ($key -and $value) {
                # 移除值两边的引号
                $value = $value.Trim('"').Trim("'")
                [Environment]::SetEnvironmentVariable($key, $value, "Process")
            }
        }
    }
    Write-Host "[OK] Environment variables loaded." -ForegroundColor Green
} else {
    Write-Host "[WARN] .env file not found, using default values." -ForegroundColor Yellow
}
Write-Host ""

# 打印关键环境变量
Write-Host "[INFO] Environment Variables:" -ForegroundColor Yellow
Write-Host "  VLLM_BASE_URL = $([Environment]::GetEnvironmentVariable('VLLM_BASE_URL', 'Process'))" -ForegroundColor Gray
Write-Host "  MODEL_NAME    = $([Environment]::GetEnvironmentVariable('MODEL_NAME', 'Process'))" -ForegroundColor Gray
Write-Host ""

# 检查 Python 是否可用
Write-Host "[INFO] Checking Python..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[OK] Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python not found! Please install Python 3.9+" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# 检查并安装依赖
Write-Host "[INFO] Checking dependencies..." -ForegroundColor Yellow
$requiredPackages = @("fastapi", "httpx", "uvicorn")
$missingPackages = @()

foreach ($pkg in $requiredPackages) {
    try {
        python -c "import $pkg" 2>$null
        if ($LASTEXITCODE -ne 0) {
            $missingPackages += $pkg
        }
    } catch {
        $missingPackages += $pkg
    }
}

if ($missingPackages.Count -gt 0) {
    Write-Host "[INFO] Installing missing packages: $($missingPackages -join ', ')" -ForegroundColor Yellow
    python -m pip install $missingPackages --quiet
    Write-Host "[OK] Packages installed." -ForegroundColor Green
} else {
    Write-Host "[OK] All dependencies OK." -ForegroundColor Green
}
Write-Host ""

# 启动服务器
Write-Host "[INFO] Starting Codex Gateway on http://localhost:8080" -ForegroundColor Cyan
Write-Host "[INFO] Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

python -m uvicorn gateway.app:app --host 0.0.0.0 --port 8080

Read-Host "Press Enter to exit"
