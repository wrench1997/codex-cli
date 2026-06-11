# VFS 模式 - 虚拟文件系统专业模式

## 概述

VFS（Virtual File System）模式是 Codex 专门为 RJCut Studio 虚拟文件系统设计的**专业工作模式**。在此模式下：

- ✅ **自动启动** RJCut Studio Electron 应用（从配置文件）
- ✅ **自动连接** MCP 服务器（端口 8001）
- ✅ **屏蔽本地** 文件操作工具，避免误操作真实文件系统
- ✅ **全部使用** 虚拟文件系统工具进行文件操作

## 启动方式

### 方式 1：使用 `--vfs` 参数（推荐）

```bash
# 基本用法 - 自动从 config/mcp_config.yaml 加载配置
python -m src.codex.cli --vfs

# VFS 模式 + 自动审批
python -m src.codex.cli --vfs -y

# VFS 模式 + 指定任务
python -m src.codex.cli --vfs "帮我创建一个视频项目"

# VFS 模式 + 指定 MCP 配置文件
python -m src.codex.cli --vfs --mcp-config ./custom_mcp.yaml
```

### 方式 2：手动启动 + `--mcp` 参数

如果 Electron 应用已经运行，可以直接使用普通 MCP 模式连接：

```bash
# 1. 手动启动 RJCut Studio Electron 应用
cd D:\workspace\rjcut\studio\electron
npm start

# 2. 使用 --mcp 参数连接
python -m src.codex.cli --mcp
```

## 配置文件

VFS 模式使用标准的 MCP 配置文件（`config/mcp_config.yaml`），关键配置如下：

```yaml
servers:
  - name: rjcut_vfs
    description: "RJCut Studio 虚拟文件系统（VFS 专业模式）"
    enabled: true
    websocket_url: "ws://localhost:8001/ws"
    # Electron 应用配置（VFS 模式专用）
    electron:
      # Electron 应用路径
      app_path: "D:\\workspace\\rjcut\\studio\\electron"
      # 启动命令
      start_command: "electron"
      # 启动参数
      start_args: ["."]
      # 等待 MCP 服务器就绪的时间（秒）
      wait_time: 5
```

当使用 `--vfs` 参数时，系统会：
1. 从配置文件加载 `rjcut_vfs` 服务器配置
2. 自动启动配置的 Electron 应用
3. 等待 MCP 服务器就绪
4. 建立 WebSocket 连接
5. 加载虚拟文件系统工具

## 工作原理

```
┌─────────────────────────────────────────────────────────────┐
│                    Codex CLI (--vfs)                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  VFS Mode Controller                                 │   │
│  │  - 自动启动 Electron 应用                              │   │
│  │  - 自动连接 MCP 服务器 (ws://localhost:8001/ws)       │   │
│  │  - 屏蔽本地文件工具                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  可用工具：                                                  │
│  - vfs_list, vfs_read, vfs_write, vfs_delete               │
│  - vfs_move, vfs_copy, vfs_mkdir, vfs_exists               │
│  - vfs_search, vfs_search_videos, vfs_search_json          │
│  - vfs_project_list, vfs_project_create                    │
│  - vfs_project_read, vfs_project_update                    │
│  - vfs_storage_info                                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ WebSocket (MCP 协议)
                            │ ws://localhost:8001/ws
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              RJCut Studio Electron Application              │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  MCP Server (mcp-server.js)                          │   │
│  │  - 工具注册与路由                                     │   │
│  │  - WebSocket 通信                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Virtual File System (virtual-file-server.js)        │   │
│  │  - 内存 + 持久化存储                                   │   │
│  │  - 虚拟路径系统 (/projects, /素材，/配置，etc.)        │   │
│  │  - 项目模板管理                                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 可用工具列表

### 基础文件操作

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `vfs_list` | 列出目录内容 | `path` (可选，默认 `/`) |
| `vfs_read` | 读取文件内容 | `path` (必填) |
| `vfs_write` | 写入文件 | `path`, `content` (必填) |
| `vfs_delete` | 删除文件/目录 | `path`, `recursive` (可选) |
| `vfs_move` | 移动/重命名 | `from`, `to` (必填) |
| `vfs_copy` | 复制文件 | `from`, `to` (必填) |
| `vfs_mkdir` | 创建目录 | `path`, `recursive` (可选) |
| `vfs_exists` | 检查路径是否存在 | `path` (必填) |

### 搜索工具

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `vfs_search` | 搜索文件 | `pattern`, `maxResults` (可选) |
| `vfs_search_videos` | 搜索视频文件 | `maxResults` (可选) |
| `vfs_search_json` | 搜索 JSON 文件 | `maxResults` (可选) |

### 项目管理

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `vfs_project_list` | 列出所有项目 | 无 |
| `vfs_project_create` | 创建新项目 | `name`, `config` (可选) |
| `vfs_project_read` | 读取项目配置 | `projectPath` (必填) |
| `vfs_project_update` | 更新项目配置 | `projectPath`, `config` (必填) |

### 系统信息

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `vfs_storage_info` | 获取存储使用情况 | 无 |

## 使用示例

### 示例 1：创建视频项目

```bash
python -m src.codex.cli --vfs "帮我创建一个名为'我的纪录片'的视频项目"
```

### 示例 2：列出虚拟目录

```bash
python -m src.codex.cli --vfs "列出 /projects 目录下的所有内容"
```

### 示例 3：读取配置文件

```bash
python -m src.codex.cli --vfs "读取 /配置/default.json 的内容"
```

### 示例 4：搜索视频文件

```bash
python -m src.codex.cli --vfs "帮我找到所有的视频文件"
```

## 注意事项

### 1. Electron 应用路径

VFS 模式默认从以下路径启动 Electron 应用：
```
D:\workspace\rjcut\studio\electron
```

如果路径不存在，请修改 `src/codex/cli.py` 中的 `rjcut_electron_path` 变量。

### 2. 端口配置

默认 MCP 服务器端口为 `8001`，如需修改可使用 `--vfs-port` 参数。

### 3. 本地工具屏蔽

在 VFS 模式下，以下本地工具会被**自动屏蔽**：
- `read_file` → 改用 `vfs_read`
- `write_file` → 改用 `vfs_write`
- `list_directory` → 改用 `vfs_list`
- `search_in_files` → 改用 `vfs_search`
- `delete_lines`, `insert_lines`, `replace_lines`, `search_replace`, `apply_patch`, `diff_files`

如果尝试使用被屏蔽的工具，会收到错误提示：
```
❌ VFS 模式：本地工具 'read_file' 已被禁用，请使用 MCP 虚拟文件系统工具
```

### 4. 虚拟路径系统

VFS 使用虚拟路径系统，常见根目录包括：
- `/projects` - 视频项目
- `/素材` - 原始素材
- `/草稿` - 草稿文件
- `/配置` - 配置文件
- `/脚本` - 脚本文件
- `/模板` - 模板文件
- `/输出` - 输出文件
- `/音频` - 音频文件
- `/字幕` - 字幕文件
- `/转录` - 转录文件

### 5. 持久化存储

虚拟文件系统的数据会定期持久化到：
```
<vfs-storage.json>
```

位置通常在 Electron 应用的用户数据目录中。

## 故障排除

### 问题 1：Electron 应用启动失败

**症状**：显示 `❌ 启动 Electron 应用失败：...`

**解决方案**：
1. 确认 Electron 已全局安装：`npm install -g electron`
2. 手动启动 Electron 应用测试
3. 检查路径是否正确

### 问题 2：MCP 服务器连接失败

**症状**：显示 `⚠️  VFS MCP 服务器连接失败`

**解决方案**：
1. 确认 Electron 应用已启动
2. 确认 MCP 服务器已在端口 8001 启动
3. 检查防火墙设置
4. 尝试手动访问：`ws://localhost:8001/ws`

### 问题 3：工具调用返回空结果

**症状**：工具执行成功但返回空数据

**解决方案**：
1. 检查虚拟路径是否正确
2. 确认虚拟文件系统中存在相应数据
3. 查看 Electron 应用的控制台日志

## 开发调试

### 查看 MCP 服务器状态

在 Codex REPL 中使用：
```
/mcp
```

### 查看可用工具

在 Codex REPL 中使用：
```
/tools
```

### 启用详细日志

修改 `src/codex/mcp/manager.py` 中的日志级别，或在 Electron 应用中启用调试模式。

## 相关文档

- [MCP 使用指南](./MCP_USAGE.md)
- [RJCut Studio Electron 文档](../../rjcut/studio/electron/VFS-README.md)