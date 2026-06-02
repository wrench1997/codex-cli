# Codex CLI

一个强大的 AI 编程助手，支持持续对话、上下文记忆和工具调用。

## 功能特性

- 💬 **持续对话** - 多轮上下文保留的 AI 聊天
- 🛠️ **工具调用** - 自动读写文件、执行命令
- 🔌 **MCP 支持** - 集成 Model Context Protocol，扩展工具生态
- 📝 **代码编辑** - 支持 diff 预览、行级编辑、搜索替换
- 💰 **计费统计** - 实时监控 token 使用和缓存命中

## 技术栈

- **Python 3.10+**
- **FastAPI** - API 网关
- **Rich** - 终端美化输出
- **Prompt Toolkit** - 交互式 REPL
- **MCP** - Model Context Protocol

## 项目结构

```
codex-cli/
├── src/codex/              # 核心源代码
│   ├── cli.py             # CLI 主入口
│   ├── config.py          # 配置管理
│   ├── tools.py           # 工具定义
│   ├── file_editor.py     # 文件编辑器
│   └── mcp/               # MCP 集成
│       └── manager.py     # MCP 管理器
├── gateway/                # API 网关
│   └── app.py             # FastAPI 应用
├── config/                 # 配置文件
│   ├── mcp_config.yaml    # MCP 服务器配置
│   └── upload_config.yaml
├── scripts/                # 启动脚本
│   ├── mcodex.bat
│   └── start_gateway.ps1
├── tests/                  # 测试文件
├── docs/                   # 文档
├── pyproject.toml
└── requirements.txt
```

## 快速开始

### 1. 安装依赖

```bash
# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 到 `.env` 并修改配置：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
CODEX_API_BASE=http://127.0.0.1:8080/v1
CODEX_MODEL=Qwen/Qwen3.5-397B-A17B-FP8
CODEX_API_KEY=your-api-key
CODEX_TEMPERATURE=0.6
```

### 3. 启动 API 网关（可选）

如果需要本地 API 网关：

```bash
# PowerShell
.\scripts\start_gateway.ps1

# 或直接运行
python -m uvicorn gateway.app:app --host 0.0.0.0 --port 8080
```

### 4. 运行 Codex CLI

```bash
# 使用 uv
uv run codex

# 或直接运行
python -m src.codex.cli

# 使用批处理脚本
.\scripts\mcodex.bat
```

## 使用方法

### 基本用法

```bash
# 进入交互式 REPL
python -m src.codex.cli

# 执行单次任务
python -m src.codex.cli "帮我重构 main.py"

# 自动审批模式
python -m src.codex.cli -y "修复所有 TODO"

# 指定工作目录
python -m src.codex.cli --dir /path/to/project

# 纯聊天模式（不调用工具）
python -m src.codex.cli --no-agent
```

### 常用参数

| 参数 | 说明 |
|------|------|
| `-y, --yes` | 自动审批所有文件修改 |
| `-m, --model` | 指定模型名称 |
| `--api` | API 基地址 |
| `--no-agent` | 纯聊天模式 |
| `-t, --temperature` | 采样温度 |
| `--mcp` | 加载 MCP 服务 |
| `--mcp-config` | 指定 MCP 配置文件 |

### 内置命令

在 REPL 中可以使用以下命令：

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/reset` | 清空对话历史 |
| `/history` | 查看对话历史摘要 |
| `/ls [path]` | 列出目录结构 |
| `/cat <file>` | 查看文件内容 |
| `/cd <dir>` | 切换工作目录 |
| `/approve` | 切换自动审批模式 |
| `/model` | 显示当前配置 |
| `/tokens` | 估算上下文 token 数 |
| `/mode` | 切换 chat/agent 模式 |
| `/tools` | 显示可用工具列表 |
| `/mcp` | 显示 MCP 服务状态 |
| `/billing` | 显示当天计费统计 |
| `/exit` | 退出 |

### 输入技巧

- **多行输入**: 按 `Esc+Enter` 换行，`Enter` 发送
- **粘贴多行**: 按 `Ctrl+V` 粘贴剪贴板内容
- **历史**: 上下箭头翻阅历史
- **取消生成**: `Esc` 或 `Ctrl+C`

## MCP 配置

在 `config/mcp_config.yaml` 中配置 MCP 服务器：

```yaml
enabled: true
settings:
  timeout: 30

servers:
  - name: playwright
    description: Playwright 浏览器自动化
    command: npx
    args:
      - "@playwright/mcp@latest"
    enabled: true
```

启动时添加 `--mcp` 参数：

```bash
python -m src.codex.cli --mcp
```

## API 网关

Codex 包含一个 FastAPI 网关，提供以下端点：

- `POST /v1/responses` - 主要 API 端点（支持流式）
- `GET /v1/models` - 获取模型列表
- `GET /v1/billing` - 获取计费统计
- `POST /v1/billing/reset` - 重置计费统计

启动网关：

```bash
python -m uvicorn gateway.app:app --host 0.0.0.0 --port 8080
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CODEX_API_BASE` | `http://yourserver:port/v1` | API 基地址 |
| `CODEX_MODEL` | `Qwen/Qwen3.5-397B-A17B-FP8` | 模型名称 |
| `CODEX_API_KEY` | `dummy` | API 密钥 |
| `CODEX_TEMPERATURE` | `0.6` | 采样温度 |
| `CODEX_MAX_TURNS` | `50` | 最大工具调用轮次 |
| `CODEX_AUTO_APPROVE` | `false` | 自动审批 |
| `VLLM_BASE_URL` | `http://yourserver:7980` | vLLM 地址（网关用） |
| `POLL_INTERVAL` | `5` | Metrics 刷新间隔（秒） |

## 许可证

MIT
