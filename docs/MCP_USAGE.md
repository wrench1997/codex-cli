# MCP (Model Context Protocol) 使用指南

## 简介

MCP 允许 Codex CLI 连接到各种外部服务（如浏览器、数据库、GitHub 等），通过标准化的协议扩展 AI 的能力边界。

## 快速开始

### 1. 安装依赖

```bash
pip install mcp pyyaml
```

### 2. 配置 MCP 服务器

编辑 `mcp_config.yaml` 文件：

```yaml
# 是否启用 MCP 功能
enabled: true

# MCP 服务器列表
servers:
  # Playwright MCP - 浏览器自动化
  - name: playwright
    description: "浏览器自动化操作（导航、点击、截图等）"
    enabled: true
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-playwright"
    
  # SQLite MCP - 数据库操作
  - name: sqlite
    description: "SQLite 数据库查询和管理"
    enabled: false
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-sqlite"
    env:
      SQLITE_DB_PATH: "./data.db"
```

### 3. 启动 Codex CLI

```bash
# 使用默认配置文件 (./mcp_config.yaml)
python codex.py --mcp

# 或指定配置文件路径
python codex.py --mcp-config /path/to/mcp_config.yaml
```

### 4. 使用示例

启动后，AI 可以自动使用 MCP 工具：

```
>>> 帮我打开浏览器，访问 https://github.com 并告诉我它的页面标题是什么

<tool_call>
<function=playwright_navigate>
<parameter=url>
https://github.com
</parameter>
</function>
</tool_call>

<tool_call>
<function=playwright_screenshot>
<parameter=name>
github_homepage
</parameter>
</function>
</tool_call>
```

## 配置文件详解

### 完整配置示例

```yaml
# 是否启用 MCP 功能
enabled: true

# MCP 服务器列表
servers:
  # Playwright MCP - 浏览器自动化
  - name: playwright
    description: "浏览器自动化操作（导航、点击、截图等）"
    enabled: true
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-playwright"
    
  # SQLite MCP - 数据库操作
  - name: sqlite
    description: "SQLite 数据库查询和管理"
    enabled: false
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-sqlite"
    env:
      SQLITE_DB_PATH: "./data.db"
    
  # GitHub MCP - GitHub API 操作
  - name: github
    description: "GitHub API 操作（Issues, PRs, Repos）"
    enabled: false
    command: npx
    args:
      - "-y"
      - "@modelcontextprotocol/server-github"
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"

# 全局设置
settings:
  # 启动超时时间（秒）
  startup_timeout: 30
  # 工具调用超时时间（秒）
  call_timeout: 60
  # 是否显示详细日志
  verbose: false
```

### 配置字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | boolean | 是否启用 MCP 功能 |
| `servers` | array | MCP 服务器列表 |
| `servers[].name` | string | 服务器唯一标识 |
| `servers[].description` | string | 服务器描述 |
| `servers[].enabled` | boolean | 是否启用此服务器 |
| `servers[].command` | string | 启动命令（如 `npx`） |
| `servers[].args` | array | 命令参数列表 |
| `servers[].env` | object | 环境变量（支持 `${VAR}` 占位符） |
| `settings.startup_timeout` | number | 启动超时时间（秒） |
| `settings.call_timeout` | number | 工具调用超时时间（秒） |
| `settings.verbose` | boolean | 是否显示详细日志 |

## 可用的 MCP 服务器

### 官方服务器

| 服务器 | 命令 | 说明 |
|--------|------|------|
| Playwright | `@modelcontextprotocol/server-playwright` | 浏览器自动化 |
| SQLite | `@modelcontextprotocol/server-sqlite` | SQLite 数据库 |
| GitHub | `@modelcontextprotocol/server-github` | GitHub API |
| PostgreSQL | `@modelcontextprotocol/server-postgres` | PostgreSQL 数据库 |
| Filesystem | `@modelcontextprotocol/server-filesystem` | 文件系统操作 |

### 第三方服务器

可以在 [MCP 官网](https://modelcontextprotocol.io/) 查找更多服务器。

## 命令行参数

| 参数 | 说明 |
|------|------|
| `--mcp` | 从默认配置文件加载 MCP 服务 |
| `--mcp-config <path>` | 从指定路径加载配置文件 |

## 常见问题

### Q: MCP 服务启动失败？

A: 确保已安装 Node.js 和 npx：
```bash
node --version
npx --version
```

### Q: 如何调试 MCP 服务器？

A: 在配置文件中设置 `settings.verbose: true`，查看详细日志。

### Q: 环境变量如何使用？

A: 使用 `${VAR_NAME}` 语法引用系统环境变量：
```yaml
env:
  API_KEY: "${MY_API_KEY}"
```

### Q: 如何自定义 MCP 服务器？

A: 参考 [MCP 官方文档](https://modelcontextprotocol.io/docs) 创建自定义服务器。

## 架构说明

```
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐
│  Codex CLI  │───▶│ McpManager   │───▶│ MCP Server #1   │
│  (codex.py) │    │ (多服务器管理)│    │ (如 Playwright) │
└─────────────┘    └──────────────┘    └─────────────────┘
                          │
                          └───────────────────────────────┐
                                                          ▼
                                              ┌─────────────────┐
                                              │ MCP Server #2   │
                                              │ (如 SQLite)     │
                                              └─────────────────┘
```

- **McpManager**：从配置文件加载多个 MCP 服务器，管理生命周期
- **ToolExecutor**：统一分发工具调用（原生工具 + MCP 工具）
- **ChatAgent**：动态合并工具列表，发送给 AI 模型

## 下一步

- 尝试启用更多 MCP 服务器
- 创建自定义 MCP 服务器
- 分享你的 MCP 使用案例
