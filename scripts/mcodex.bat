@echo off
setlocal enabledelayedexpansion

set "args=%*"

rem Run in normal mode when no arguments provided
rem if "!args!"=="" goto usage

rem Check for --vfs flag
echo !args! | findstr /C:"--vfs" >nul
if !errorlevel! equ 0 (
    "%USERPROFILE%\.local\bin\uv.exe" run --directory "D:\workspace\codex-cli" python -m src.codex.cli --dir "%CD%" --vfs !args!
    goto :eof
)

rem Check for --mcp flag
echo !args! | findstr /C:"--mcp" >nul
if !errorlevel! equ 0 (
    "%USERPROFILE%\.local\bin\uv.exe" run --directory "D:\workspace\codex-cli" python -m src.codex.cli --dir "%CD%" --mcp !args!
    goto :eof
)

rem Normal mode - only pass args if not empty
if "!args!"=="" (
    "%USERPROFILE%\.local\bin\uv.exe" run --directory "D:\workspace\codex-cli" python -m src.codex.cli --dir "%CD%"
) else (
    "%USERPROFILE%\.local\bin\uv.exe" run --directory "D:\workspace\codex-cli" python -m src.codex.cli --dir "%CD%" !args!
)
goto :eof

:usage
echo Codex CLI Launcher
echo Usage:
echo   mcodex.bat [task]                    - Normal mode
echo   mcodex.bat --mcp [task]              - MCP mode
echo   mcodex.bat --vfs [task]              - VFS Pro mode
echo   mcodex.bat --vfs -y [task]           - VFS with auto-approve
echo   mcodex.bat --vfs --mcp-config xxx    - VFS with custom config