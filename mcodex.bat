@echo off
REM Codex CLI Launcher
"%USERPROFILE%\.local\bin\uv.exe" run --directory "D:\workspace\codex-cli" python codex.py --dir "%CD%" %*