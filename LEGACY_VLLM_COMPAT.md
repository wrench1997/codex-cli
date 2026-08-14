# mcodex 旧 vLLM / 新中转站双模式兼容

这个版本保留三条调用链，不需要再反复改核心代码：

```text
A. mcodex -> 原始 vLLM /v1/chat/completions
B. mcodex -> 本地 gateway -> 原始 vLLM
C. mcodex -> 本地 gateway -> OpenAI 兼容中转站
```

## A. 直接调用旧 vLLM（最少环节）

PowerShell：

```powershell
.\scripts\mcodex-vllm.ps1 `
  -BaseUrl "http://112.111.7.91:7980/v1" `
  -Model "DeepSeek-V4-Flash-0731"
```

该直连启动器默认使用 `prompt` 工具协议，因此不要求 vLLM 服务端启用
`--enable-auto-tool-choice` 或配置 `--tool-call-parser`。只有服务端已经按模型
配置好原生工具解析器时，才显式传入 `-ToolTransport native`。

等价命令：

```powershell
$env:CODEX_ENV_OVERRIDE="false"
mcodex `
  --api "http://112.111.7.91:7980/v1" `
  --api-mode chat `
  --model "DeepSeek-V4-Flash-0731" `
  --tool-transport prompt
```

这里使用 `chat + prompt`，不依赖 vLLM 原生 function calling。模型输出文本工具调用，mcodex 在本机执行工具，再把结果作为普通消息发回模型。

## B. 通过旧 Gateway 调用 vLLM

复制配置：

```powershell
Copy-Item .env.gateway-vllm.example .env
.\scripts\start_gateway.ps1
```

另开一个 PowerShell：

```powershell
mcodex --api http://127.0.0.1:8080/v1 --api-mode gateway --tool-transport native
```

网关同时开放：

- `POST /v1/responses`
- `POST /v1/chat/completions`
- `GET /health`
- `GET /v1/gateway/probe`

探测上游：

```powershell
curl.exe http://127.0.0.1:8080/v1/gateway/probe
```

## C. Gateway 转中转站

复制：

```powershell
Copy-Item .env.gateway-relay.example .env
```

填写：

```dotenv
UPSTREAM_BASE_URL="http://localhost:3000/v1"
UPSTREAM_API_KEY="你的中转站密钥"
UPSTREAM_MODEL="gpt-5-5"
```

然后启动网关。Relay 模式默认关闭 vLLM 专属的 thinking、metrics 和 stream usage 扩展，减少 400/422。

## 独立连通性测试

测试原始 vLLM：

```powershell
uv run python scripts/test_api_compat.py `
  --base "http://112.111.7.91:7980" `
  --model "DeepSeek-V4-Flash-0731"
```

测试本地 Gateway：

```powershell
uv run python scripts/test_api_compat.py `
  --base "http://127.0.0.1:8080" `
  --model "DeepSeek-V4-Flash-0731"
```

## 关键兼容修复

1. 恢复标准 `/v1/chat/completions`，旧 OpenAI 客户端不再被强制拒绝。
2. `UPSTREAM_BASE_URL` 支持根地址、`/v1` 和完整 endpoint，避免重复拼接 `/v1/v1`。
3. 支持上游 Bearer API Key。
4. `function_call_output` 转为 XML 工具结果普通消息，不再发送缺少 `tool_call_id` 的非法 `role=tool`。
5. Responses 输入中的历史 `function_call` 会还原成 XML assistant 消息。
6. relay 模式不再默认发送 vLLM 私有 thinking/metrics 参数。
7. Chat 普通和流式响应都能把 XML 工具调用恢复为标准 `tool_calls`。
