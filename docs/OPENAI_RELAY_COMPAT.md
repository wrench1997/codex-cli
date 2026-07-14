# OpenAI 中转站兼容说明

## 推荐架构

中转站已经提供 `/v1/responses` 时，建议让 mcodex 直接调用中转站。新版支持两条工具链：

```text
原生链路：model -> function_call -> mcodex 本地执行
                     -> function_call_output（相同 call_id）

兼容链路：model -> <tool_call> XML 文本 -> mcodex 本地执行
                     -> <tool_response> 普通消息
```

不少“OpenAI 兼容”中转站只兼容文本对话，`tools` 字段、流式 function_call 事件或 `function_call_output` 并不完整。遇到工具调用后空白、工具结果消失时，应使用 `prompt` 工具传输模式。

## `.env` 示例

```dotenv
CODEX_API_BASE="http://localhost:3000/v1"
CODEX_API_MODE="chat"
CODEX_API_KEY="replace-with-a-new-key"
CODEX_MODEL="gpt-5-3-mini"
CODEX_SEND_TEMPERATURE="false"
CODEX_TOOL_TRANSPORT="prompt"
CODEX_TOOL_CHOICE="auto"
CODEX_DEBUG_REQUESTS="false"
```

新版会自动读取项目根目录的 `.env`。系统环境变量和命令行参数优先级更高。

也可以直接通过命令行启动：

```powershell
.\scripts\mcodex.ps1 --api http://localhost:3000/v1 --api-mode responses --model gpt-5-3-mini --mcp
```

## 模式说明

API 模式：

- `responses`：调用 `/v1/responses`。
- `chat`：调用 `/v1/chat/completions`，适合 ChatGPT2API 一类文本中转。
- `gateway`：调用本项目旧 vLLM XML 网关。
- `auto`：先尝试 `responses`，协议错误时回退 `gateway`。

工具传输模式：

- `native`：只使用原生 Responses `function_call`。要求中转站完整透传工具定义、流式事件和 `function_call_output`。
- `prompt`：不发送原生 `tools`，把工具说明注入 system prompt，解析模型输出的 `<tool_call>`。对于第三方中转站最稳。
- `hybrid`：原生 tools 与 XML 提示同时启用，适合不确定中转能力时测试。

对于当前 `localhost:3000` 的 ChatGPT2API 中转站，建议固定 `CODEX_API_MODE=chat` 与 `CODEX_TOOL_TRANSPORT=prompt`。原生工具不稳定时，文本协议会在本机执行工具并把结果作为普通消息回传。

## 本次修复的关键问题

1. `--api` 原默认值会无条件覆盖 `CODEX_API_BASE`。
2. CLI 没有加载 `.env`。
3. `THINK_RE = re.compile(r".*?")` 会删除所有正常回复文本。
4. 项目工具定义是 Chat Completions 的嵌套格式，而 Responses 需要扁平函数工具格式。
5. 原生 Responses 的 `reasoning`、`function_call` 等 output items 没有被带回下一轮。
6. `enable_thinking` 和 `temperature` 等字段可能被 GPT-5 或中转站拒绝。
7. 一些中转实现即使 `stream=true` 也返回普通 JSON；新版同时兼容 SSE 和 JSON。
8. 中转站把工具调用放在 message 的 `<tool_call>` 文本中时，旧版 UI 会隐藏 XML，但核心逻辑未解析，最终表现为整轮空白。
9. XML 工具调用不能伪造成原生 `function_call_output`；新版改用 `<tool_response>` 普通消息回传结果。
10. 新版同时兼容 `response.output_item.added`、参数 delta 和缺失 completed.response 的流式实现。

## 安全提醒

API Key 不应出现在聊天记录、日志、截图或 Git 中。已经公开过的 Key 应立即在中转站后台撤销并重新生成。


## Windows `.env` 优先级

项目根目录 `.env` 默认覆盖 PowerShell/CMD 会话中残留的 `CODEX_*` 变量。若需要恢复“系统环境变量优先”，启动前设置 `CODEX_ENV_OVERRIDE=false`。也可用 `CODEX_ENV_FILE=D:\\path\\mcodex.env` 指定另一份配置。
