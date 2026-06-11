# ============================================================
# RJCut Studio MCP Server - PowerShell 启动脚本
# ============================================================
# 使用说明：
#   1. 在另一个 PowerShell 窗口运行此脚本
#   2. 保持此窗口打开，MCP 服务器将持续运行
#   3. Codex CLI 将通过 WebSocket 连接到此服务器
#
# 使用方式：
#   .\scripts\start_rjcut_studio.ps1
#   .\scripts\start_rjcut_studio.ps1 -studioPath "D:\workspace\rjcut\studio"
#
# 配置：
#   项目路径建议在 config/mcp_config.yaml 中配置
#   或通过 -studioPath 参数传入
# ============================================================

param(
    [string]$studioPath = "D:\workspace\rjcut\studio"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  RJCut Studio MCP Server" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[INFO] Studio Path: $studioPath" -ForegroundColor Gray
Write-Host ""

# 检查路径是否存在
if (-not (Test-Path $studioPath)) {
    Write-Host "[ERROR] RJCut Studio 路径不存在：$studioPath" -ForegroundColor Red
    Write-Host "[INFO] 请检查路径配置或先克隆项目" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# 切换到项目目录
Set-Location $studioPath
Write-Host "[INFO] Working directory: $studioPath" -ForegroundColor Gray
Write-Host ""

# 检查 Node.js 是否可用
Write-Host "[INFO] Checking Node.js..." -ForegroundColor Yellow
try {
    $nodeVersion = node --version 2>&1
    Write-Host "[OK] Node.js found: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Node.js not found! Please install Node.js 18+" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# 检查 npm 是否可用
Write-Host "[INFO] Checking npm..." -ForegroundColor Yellow
try {
    $npmVersion = npm --version 2>&1
    Write-Host "[OK] npm found: $npmVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] npm not found!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host ""

# 检查 node_modules 是否存在
if (-not (Test-Path "node_modules")) {
    Write-Host "[INFO] Installing dependencies..." -ForegroundColor Yellow
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install dependencies" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK] Dependencies installed." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "[OK] Dependencies already installed." -ForegroundColor Green
    Write-Host ""
}

# 启动开发服务器
Write-Host "[INFO] Starting RJCut Studio MCP Server..." -ForegroundColor Cyan
Write-Host "[INFO] WebSocket: ws://localhost:8001/ws" -ForegroundColor Gray
Write-Host "[INFO] Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 启动 npm run dev
npm run dev

# 脚本结束后等待用户按键（通常不会执行到这里，因为 npm run dev 会阻塞）
Read-Host "Press Enter to exit"