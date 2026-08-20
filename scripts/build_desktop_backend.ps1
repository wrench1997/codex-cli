$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$resourceDir = Join-Path $projectRoot 'desktop\resources'
$workDir = Join-Path $projectRoot 'desktop\.pyinstaller-work'
$specDir = Join-Path $projectRoot 'desktop\.pyinstaller-spec'

New-Item -ItemType Directory -Force -Path $resourceDir | Out-Null
& uvx --from pyinstaller==6.17.0 pyinstaller --noconfirm --clean --onefile `
  --name codex-backend --paths (Join-Path $projectRoot '.venv\Lib\site-packages') `
  --paths $projectRoot --collect-all mcp --collect-all dotenv `
  --distpath $resourceDir --workpath $workDir --specpath $specDir `
  (Join-Path $projectRoot 'desktop\backend_entry.py')

if ($LASTEXITCODE -ne 0) { throw "PyInstaller backend build failed with exit code $LASTEXITCODE" }
