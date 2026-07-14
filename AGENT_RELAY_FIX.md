# OpenAI 中转站 Agent 修复说明

本版本已针对 `http://localhost:3000/v1` 一类 ChatGPT2API/OpenAI 兼容中转站调整：

- 默认配置使用 `CODEX_API_MODE=chat`，调用 `/v1/chat/completions`。
- 默认使用 `CODEX_TOOL_TRANSPORT=prompt`，不依赖中转站透传原生 function call。
- 本地工具采用 `<mcodex_tool_call>{...}</mcodex_tool_call>` JSON 标签协议。
- 自动忽略上游隐藏的 `api_tool`、Gmail、Calendar 等工具，防止与本地工具冲突。
- 当中转站丢失工具名但保留 `{"paths":["."]}` 参数时，会修复为 `list_directory`。
- 模型错误声称“无法访问本地/没有权限”时，会自动纠正并重试，默认最多 2 次。
- 同时支持 Responses API、Chat Completions API 和旧 gateway。
- 项目根目录 `.env` 默认覆盖 Windows 当前会话中残留的 `CODEX_*` 变量。

## 当前推荐 `.env`

```dotenv
CODEX_API_BASE="http://localhost:3000/v1"
CODEX_API_MODE="chat"
CODEX_MODEL="gpt-5-5"
CODEX_TOOL_TRANSPORT="prompt"
CODEX_TOOL_CHOICE="auto"
CODEX_AGENT_REFUSAL_RETRIES="2"
CODEX_ENV_OVERRIDE="true"
CODEX_SEND_TEMPERATURE="false"
```

API Key 继续填写在本地 `.env`，不要上传或提交到 Git。

## Windows 启动

```powershell
cd D:\workspace\chatgpt2api
mcodex
```

启动面板应显示：

```text
API:      http://localhost:3000/v1
协议:     chat / prompt
.env:     D:\workspace\codex-cli\.env
模式:     Agent（工具调用）
```

测试输入：

```text
使用 list_directory 查看当前目录，并告诉我一级文件和文件夹。
```

正常顺序应为：工具调用卡片 → 本地结果卡片 → 最终自然语言回答。
