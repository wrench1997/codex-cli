@echo off
REM Codex CLI - 一键启动脚本
REM 用法：mcodex [参数]
REM 示例：mcodex "帮我重构 main.py"

cd /d "%~dp0"

REM 可选：加载 .env 文件中的环境变量
if exist ".env" (
    for /f "delims=" %%a in (.env) do (
        echo %%a | findstr /r "^[^#]" >nul && (
            for /f "tokens=1,* delims==" %%b in ("%%a") do (
                set "%%b=%%c"
            )
        )
    )
)

uv run python codex.py %*