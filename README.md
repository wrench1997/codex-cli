# Codex CLI

一个强大的 AI 编程助手，支持持续对话、上下文记忆、工具调用和虚拟文件系统（VFS）集成。

## 功能特性

- 💬 **持续对话** - 多轮上下文保留的 AI 聊天
- 🛠️ **工具调用** - 自动读写文件、执行命令
- 🔌 **MCP 支持** - 集成 Model Context Protocol，扩展工具生态
- 📝 **代码编辑** - 支持 diff 预览、行级编辑、搜索替换
- 💰 **计费统计** - 实时监控 token 使用和缓存命中
- 🧠 **上下文压缩** - 自动压缩长对话历史，提取核心记忆点
- 🗂️ **VFS 模式** - 虚拟文件系统专业模式，安全操作隔离环境

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
│   ├── mcodex.bat         # Windows 批处理启动器
│   ├── mcodex.ps1         # PowerShell 智能启动器
│   ├── start_gateway.ps1  # API 网关启动脚本
│   └── start_rjcut_studio.ps1  # RJCut Studio MCP 启动脚本
├── tests/                  # 测试文件
├── docs/                   # 文档
│   ├── MCP_USAGE.md       # MCP 使用指南
│   └── VFS_MODE.md        # VFS 模式文档
├── count_src_lines_yaml.py # 代码行数统计工具
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

# VFS 模式（虚拟文件系统专业模式）
python -m src.codex.cli --vfs

# VFS 模式 + 自动审批
python -m src.codex.cli --vfs -y "帮我创建一个视频项目"
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
| `--vfs` | VFS 模式：自动启动 Electron 应用并连接虚拟文件系统 |
| `--vfs-port` | VFS MCP 服务器端口（默认：8001） |

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
| `/memory` | 查看当前提炼的核心记忆点 |
| `/compress` | 手动压缩并归纳历史上下文 |
| `/exit` | 退出 |

### 🆕 Git 工具（AI 可自动调用）

Codex 现在集成了完整的 Git 工具，AI 可以自动调用它们来查看代码历史、打包代码求助其他 AI：

| 工具名 | 功能描述 |
|--------|----------|
| `git_log` | 查看最近的提交历史 |
| `git_show` | 查看某个 commit 的详细代码改动 |
| `git_status` | 查看当前工作区状态 |
| `git_diff` | 查看分支或 commit 之间的差异 |
| `pack_for_ai` | 🌟 打包源代码 + Git 历史到单个文件，方便发送给其他 AI 求助 |
| `export_commit` | 🌟 单独导出某个 commit 的改动到 TXT 文件 |

**使用示例：**
```python
# 让 AI 打包代码求助
"帮我把当前项目的代码和最近的 git 提交打包，我要发给其他 AI 求助"
→ AI 会自动调用 pack_for_ai() 生成 selected_code.txt

# 查看某个提交的改动
"看看 8aca63ca 这个提交改了什么代码"
→ AI 会调用 git_show(commit_hash="8aca63ca")

# 导出特定 commit 询问
"把上次修复 bug 的提交单独导出来"
→ AI 会调用 export_commit(commit_hash="...") 生成 commit_xxx.txt
```

详细文档：[docs/GIT_TOOLS.md](docs/GIT_TOOLS.md)

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
  # stdio 模式：使用命令启动子进程
  - name: playwright
    description: Playwright 浏览器自动化
    command: npx
    args:
      - "@playwright/mcp@latest"
    enabled: false  # 默认禁用，需要时手动开启
  
  # WebSocket 模式：连接到远程 MCP 服务器
  - name: rjcut_vfs
    description: RJCut Studio 虚拟文件系统（VFS 专业模式）
    enabled: true
    websocket_url: "ws://localhost:8001/ws"
    # Electron 应用配置（VFS 模式自动启动）
    electron:
      app_path: "D:\\workspace\\rjcut\\studio"
      start_command: "cmd"
      start_args: ["/c", "start", "RJCut Studio MCP", "powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts\\start_rjcut_studio.ps1", "-studioPath", "D:\\workspace\\rjcut\\studio"]
      wait_time: 15  # 等待 MCP 服务器就绪的时间（秒）
```

启动时添加 `--mcp` 参数：

```bash
python -m src.codex.cli --mcp
```

### VFS 模式（虚拟文件系统专业模式）

VFS 模式是专门为 RJCut Studio 虚拟文件系统设计的专业工作模式：

```bash
# 启动 VFS 模式（自动启动 Electron 应用 + 连接 MCP 服务器 + 屏蔽本地文件工具）
python -m src.codex.cli --vfs

# VFS 模式 + 指定任务
python -m src.codex.cli --vfs "帮我创建一个视频项目"
```

**VFS 模式特性**：
- ✅ 自动启动 RJCut Studio Electron 应用
- ✅ 自动连接 MCP 服务器（端口 8001）
- ✅ 屏蔽本地文件操作工具，避免误操作真实文件系统
- ✅ 全部使用虚拟文件系统工具（vfs_read, vfs_write, vfs_list 等）

详细说明请参考：[docs/VFS_MODE.md](docs/VFS_MODE.md)

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
| `CODEX_MAX_CONTEXT_TOKENS` | `140000` | 触发上下文压缩的 token 阈值 |
| `CODEX_KEEP_RECENT_TURNS` | `6` | 上下文压缩时保留的最近对话轮数 |
| `CODEX_PROJECT_DIR` | (自动检测) | 项目根目录（mcodex.ps1 使用） |
| `VLLM_BASE_URL` | `http://yourserver:7980` | vLLM 地址（网关用） |
| `POLL_INTERVAL` | `5` | Metrics 刷新间隔（秒） |

## 启动脚本

### mcodex.ps1 - PowerShell 智能启动器

智能启动器，支持自动检测项目目录和安装依赖：

```powershell
# 基本用法
.\scripts\mcodex.ps1

# 执行任务
.\scripts\mcodex.ps1 "帮我重构代码"

# 使用 MCP 模式
.\scripts\mcodex.ps1 --mcp

# 使用 VFS 模式
.\scripts\mcodex.ps1 --vfs
```

**特性**：
- 自动检测项目根目录（通过 `pyproject.toml`）
- 支持 `CODEX_PROJECT_DIR` 环境变量覆盖
- 自动安装 `uv`（如果未安装）
- 智能路径解析

### start_rjcut_studio.ps1 - RJCut Studio MCP 启动脚本

用于手动启动 RJCut Studio MCP 服务器：

```powershell
# 使用默认配置
.\scripts\start_rjcut_studio.ps1

# 指定 Studio 路径
.\scripts\start_rjcut_studio.ps1 -studioPath "D:\workspace\rjcut\studio"
```

## 相关文档

- [MCP 使用指南](docs/MCP_USAGE.md) - MCP 服务器配置和使用
- [VFS 模式文档](docs/VFS_MODE.md) - 虚拟文件系统专业模式详解

## 许可证

MIT
