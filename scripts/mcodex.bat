@echo off
REM Codex CLI Launcher
REM 用法：mcodex.bat [任务描述] 或 mcodex.bat --mcp
"%USERPROFILE%\.local\bin\uv.exe" run --directory "D:\workspace\codex-cli" python -m src.codex.cli --dir "%CD%" --mcp %*
