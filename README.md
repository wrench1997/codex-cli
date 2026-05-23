# Codex Gateway

一个基于 FastAPI 的 API 网关，将 OpenAI 兼容的 Responses API 转换为 VLLM 后端服务。支持流式输出、工具调用（Function Calling）和思维链（Thinking）功能。

## 🚀 功能特性

- **OpenAI Responses API 兼容** - 支持 `/v1/responses` 端点
- **流式输出** - 实时流式传输响应内容
- **工具调用支持** - 将 JSON 格式的工具调用转换为 XML 格式，适配 Qwen 模型
- **思维链过滤** - 自动过滤 `` 思考过程，只输出最终结果
- **模型支持** - 支持 Qwen3.5 等大语言模型

## 📦 安装依赖

```bash
pip install -r requirements.txt
```

主要依赖：
- `fastapi` - Web 框架
- `httpx` - 异步 HTTP 客户端
- `uvicorn` - ASGI 服务器

## ⚙️ 配置

> **⚠️ 安全提示**: 敏感配置信息（如 API 地址、密钥等）请通过**环境变量**或**本地配置文件**管理，切勿提交到版本控制系统。

### 环境变量配置

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `VLLM_BASE_URL` | VLLM 服务地址 | 需自行配置 |
| `MODEL_NAME` | 模型名称 | `Qwen/Qwen3.5-397B-A17B-FP8` |

### 配置示例

创建 `.env` 文件（不提交到 Git）：

```bash
# .env 文件示例
VLLM_BASE_URL="http://your-server:port/v1"
MODEL_NAME="Qwen/Qwen3.5-397B-A17B-FP8"
```

## 🚀 启动服务

### 方式一：使用 PowerShell 脚本（推荐）

```bash
./start_gateway.ps1
```

### 方式二：直接使用 Uvicorn

```bash
python -m uvicorn codex_gateway:app --host 0.0.0.0 --port 8080
```

服务启动后，默认访问地址：`http://localhost:8080`

## 📡 API 端点

### GET `/v1/models`

获取可用模型列表。

**响应示例：**
```json
{
  "object": "list",
  "data": [{
    "id": "Qwen/Qwen3.5-397B-A17B-FP8",
    "object": "model",
    "owned_by": "qwen",
    "context_length": 262144
  }]
}
```

### POST `/v1/responses`

主要的对话接口，支持流式和非流式模式。

**请求参数：**
- `input` - 对话输入（支持多轮对话）
- `model` - 模型名称（可选）
- `stream` - 是否启用流式输出（默认：false）
- `tools` - 工具定义列表（可选）
- `temperature` - 温度参数（默认：0.2）

**流式响应事件类型：**
- `response.created` - 响应创建
- `response.in_progress` - 响应进行中
- `response.output_text.delta` - 文本增量
- `response.function_call_arguments.delta` - 工具调用参数
- `response.completed` - 响应完成

### GET `/v1/responses/{response_id}`

根据 ID 获取响应记录。

## 🛠️ 工具调用格式

本网关支持将标准的 OpenAI 工具调用格式转换为 Qwen 模型友好的 XML 格式：

**输入格式（OpenAI 标准）：**
```json
{
  "tool_calls": [{
    "function": {
      "name": "read_file_content",
      "arguments": "{\"path\": \"/path/to/file\"}"
    }
  }]
}
```

**输出格式（XML）：**
```xml
<tool_call>
<function=read_file_content>
<parameter=path>
/path/to/file
</parameter>
</function>
</tool_call>
```

## 📝 系统提示词规则

网关会自动注入工具调用的系统提示词，包括：

1. **工具使用规则** - 必须使用提供的工具，禁止幻觉
2. **文件操作规则** - 必须使用专用文件工具，禁止使用 shell 命令操作文件
3. **输出格式规则** - 工具调用必须使用指定的 XML 格式

## 🔒 安全注意事项

1. **不要硬编码敏感信息** - API 地址、密钥等应通过环境变量配置
2. **限制访问来源** - 生产环境建议配置防火墙或反向代理
3. **启用认证** - 根据需要添加 API 密钥验证

## 💻 Codex CLI 使用指南

`codex.py` 是一个支持持续对话的 AI 编程助手，具备多轮上下文记忆和工具调用能力。

### 基本用法

```bash
# 进入交互式 REPL 模式（默认）
python codex.py

# 执行单次任务后进入 REPL
python codex.py "帮我重构 main.py"

# 自动审批所有文件修改
python codex.py -y "修复所有 TODO"

# 指定工作目录
python codex.py --dir /path/to/project

# 纯聊天模式（不加载工具）
python codex.py --no-agent
```

### CLI 参数

| 参数 | 简写 | 说明 |
|------|------|------|
| `--dir` | `-d` | 指定工作目录（默认当前目录） |
| `--yes` | `-y` | 自动审批所有文件修改 |
| `--model` | `-m` | 指定模型名称 |
| `--api` | | API 基地址（默认 `http://127.0.0.1:8080/v1`） |
| `--no-agent` | | 纯聊天模式，不使用工具 |
| `--temperature` | `-t` | 采样温度（默认 0.6） |
| `--help` | `-h` | 显示帮助信息 |

### 内置命令

在 REPL 中输入 `/` 开头的命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助信息 |
| `/reset` | 清空对话历史（保留系统提示） |
| `/history` | 查看对话历史摘要 |
| `/ls [path]` | 列出目录结构 |
| `/cat <file>` | 查看文件内容 |
| `/cd <dir>` | 切换工作目录 |
| `/approve` | 切换自动审批模式 |
| `/model` | 显示当前模型和配置 |
| `/tokens` | 估算当前上下文 token 数 |
| `/mode` | 切换 chat/agent 模式 |
| `/exit` | 退出程序 |

### 输入技巧

- **多行输入**: 按 `Esc+Enter` 换行，`Enter` 发送
- **粘贴多行**: 按 `Ctrl+V` 粘贴剪贴板内容
- **历史**: 上下箭头翻阅历史
- **取消生成**: `Ctrl+C`

### 模式说明

- **Agent 模式**（默认）: AI 可以读写文件、执行命令，适合编程任务
- **Chat 模式**: 纯对话，不调用工具，适合讨论思路

### 配置

`codex.py` 使用与网关相同的配置系统，可通过以下方式配置：

1. **命令行参数**: 优先级最高
2. **config.py**: 修改配置文件
3. **环境变量**: 通过 `.env` 文件管理

## 📄 许可证

本项目仅供学习和研究使用。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！
