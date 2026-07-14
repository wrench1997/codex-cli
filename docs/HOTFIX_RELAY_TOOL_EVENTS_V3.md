# mcodex OpenAI 中转站工具事件修复 v3

## 修复的问题

部分 OpenAI 兼容中转站的 SSE 顺序如下：

1. `response.output_item.done` 返回完整 `function_call`
2. `response.completed` 仅返回 `status`，或返回空的 `output: []`

旧逻辑会用第 2 个事件覆盖第 1 个事件，导致工具调用被丢弃。终端表现为：

- 回复区域短暂出现后变空
- 不显示 Tool 卡片
- 不执行本地工具
- 本轮直接结束

v3 会把 SSE 中已经收集的 output items 合并回最终 response，并保留完整的
`function_call`、`call_id` 和 `arguments`。

## 额外修复

- 兼容 `tool_call`、嵌套 `function`、嵌套 `function_call` 等中转格式。
- 工具结果后不再提前打印空的 `Codex` 前缀。
- 如果中转站真的返回空响应，显示明确错误，而不是静默空白。
- `CODEX_DEBUG_REQUESTS=true` 时输出响应摘要，包括事件项和工具调用数量。

## 推荐配置

```dotenv
CODEX_API_BASE="http://localhost:3000/v1"
CODEX_API_MODE="responses"
CODEX_MODEL="gpt-5-5"
CODEX_TOOL_TRANSPORT="hybrid"
CODEX_SEND_TEMPERATURE="false"
CODEX_DEBUG_REQUESTS="true"
```

验证成功后可把 `CODEX_DEBUG_REQUESTS` 改回 `false`。

## 验证命令

```powershell
mcodex
```

输入：

```text
查看当前目录，并告诉我有哪些一级文件和文件夹。
```

预期顺序：

1. 显示 `Tool: list_directory`
2. 显示工具结果
3. 显示模型根据真实目录生成的最终回答

调试摘要应至少出现一次：

```text
DEBUG response: ... event_items=1 ... tool_calls=1 ...
```
