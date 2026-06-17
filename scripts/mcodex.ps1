# mcodex.ps1 - Smart Codex CLI Launcher

param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)

# Capture script location at top level (works reliably)
$ScriptLocation = $PSScriptRoot
Write-Host "[DEBUG] Script location (PSScriptRoot): $ScriptLocation" -ForegroundColor Cyan
Write-Host "[DEBUG] Current dir: $((Get-Location).Path)" -ForegroundColor Cyan

# 1. Smart Project Directory Resolution
function Get-ProjectDir {
    param(
        [string]$ScriptRoot
    )
    
    $currentDir = (Get-Location).Path
    
    # Priority 1: Environment Variable
    if ($env:CODEX_PROJECT_DIR -and $env:CODEX_PROJECT_DIR -ne "") {
        if (Test-Path -Path $env:CODEX_PROJECT_DIR -PathType Container) {
            Write-Host "[INFO] Using project dir from env: $env:CODEX_PROJECT_DIR" -ForegroundColor Cyan
            return $env:CODEX_PROJECT_DIR
        }
    }

    # Priority 2: Check relative to script location (codex-cli root)
    # This is the most reliable way to find the codex project
    if ($ScriptRoot -and $ScriptRoot -ne "") {
        Write-Host "[INFO] Script root: $ScriptRoot" -ForegroundColor Cyan
        
        $scriptParentDir = Split-Path -Parent -Path $ScriptRoot
        Write-Host "[INFO] Script parent dir: $scriptParentDir" -ForegroundColor Cyan
        
        if ($scriptParentDir -and $scriptParentDir -ne "") {
            $scriptPyproject = Join-Path -Path $scriptParentDir -ChildPath "pyproject.toml"
            Write-Host "[DEBUG] Checking: $scriptPyproject" -ForegroundColor Cyan
            
            if (Test-Path -Path $scriptPyproject -PathType Leaf) {
                Write-Host "[INFO] Found codex-cli pyproject.toml at: $scriptParentDir" -ForegroundColor Green
                return $scriptParentDir
            }
        }
    }

    # Priority 3: Fallback to current working directory
    Write-Host "[WARN] Using current directory: $currentDir" -ForegroundColor Yellow
    return $currentDir
}

$ProjectDir = Get-ProjectDir -ScriptRoot $ScriptLocation

Write-Host "[INFO] Final ProjectDir: $ProjectDir" -ForegroundColor Green

# Validate ProjectDir is not empty
if (-not $ProjectDir -or $ProjectDir -eq "") {
    Write-Host "[ERROR] ProjectDir is empty! This should not happen." -ForegroundColor Red
    Write-Host "[DEBUG] Current location: $((Get-Location).Path)" -ForegroundColor Yellow
    exit 1
}

Write-Host "[INFO] Final ProjectDir: $ProjectDir" -ForegroundColor Green

# 2. Smart search for uv executable
function Get-UvPath {
    # Check system PATH first
    $uvInPath = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvInPath) { return $uvInPath.Source }

    # Check user default install path
    $userUv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $userUv) { return $userUv }

    return $null
}

# 3. Auto-install uv if missing
function Install-Uv {
    Write-Host "[INFO] uv not found. Installing automatically..." -ForegroundColor Cyan
    try {
        # Use official PowerShell installer
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        
        # Refresh current session PATH
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "User") + ";" + `
                    [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
        
        $uvPath = Get-UvPath
        if ($uvPath) {
            Write-Host "[SUCCESS] uv installed successfully: $uvPath" -ForegroundColor Green
            return $uvPath
        } else {
            throw "uv was installed but still cannot be found in PATH."
        }
    } catch {
        Write-Host "[ERROR] Failed to auto-install uv: $_" -ForegroundColor Red
        exit 1
    }
}

# 4. Main Execution Logic
$uvExe = Get-UvPath
if (-not $uvExe) {
    $uvExe = Install-Uv
}

# Build arguments array
$runArgs = @(
    "run",
    "--directory", $ProjectDir,
    "python", "-m", "src.codex.cli",
    "--dir", (Get-Location).Path
)

# Append user arguments
if ($Arguments) {
    $runArgs += $Arguments
}

# Execute command
& $uvExe @runArgs