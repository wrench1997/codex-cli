# Git 工具使用指南

## 📦 新增功能概览

已为 Codex CLI 添加了完整的 Git 集成工具，方便查看提交历史、代码改动，并打包发送给其他 AI 求助。

---

## 🛠️ 新增工具列表

### 1. `git_log` - 查看提交历史
获取最近的 git 提交记录。

**参数：**
- `limit` (可选): 获取的提交数量，默认 10
- `author` (可选): 按作者过滤

**示例：**
```python
# 查看最近 10 条提交
git_log()

# 查看最近 20 条提交
git_log(limit=20)

# 查看特定作者的提交
git_log(author="wrenchoniline")
```

**输出示例：**
```
📜 最近 10 条提交历史:
[1] 8aca63ca | wrenchoniline | 2026-06-18
    └─ docs: 更新 README.md 添加 VFS 模式、上下文压缩和新启动脚本说明
[2] 19b7c1f4 | wrenchoniline | 2026-06-17
    └─ 修改 bat 脚本，跟通用
...
```

---

### 2. `git_show` - 查看详细改动 🌟
查看某个 commit 的完整代码改动（diff），**支持显示修改后的完整源代码**。

**参数：**
- `commit_hash` (必填): 提交 hash（可以是短 hash，如 `8aca63ca`）
- `max_lines` (可选): 最大返回行数，防止输出过长，默认 500
- `show_source` (可选): 是否显示修改后的完整源代码（如果文件还存在），默认 False

**示例：**
```python
# 查看某个提交的完整改动（带 diff）
git_show(commit_hash="8aca63ca")

# 限制输出行数
git_show(commit_hash="8aca63ca", max_lines=200)

# 查看改动 + 修改后的完整源代码（推荐！）
git_show(commit_hash="8aca63ca", show_source=True, max_lines=800)
```

**输出结构：**
```
================================================================================
📝 Commit: 8aca63ca
================================================================================

commit 8aca63ca8fbccfd6964874ae219ff677ea125cfb
Author: wrenchoniline <ljl260435988@gmail.com>

    docs: 更新 README.md 添加 VFS 模式

---
 README.md | 102 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++--
 1 file changed, 99 insertions(+), 3 deletions(-)

--------------------------------------------------------------------------------
📁 修改的文件 (1 个):
  • README.md

================================================================================
📄 修改后的源代码内容:  (当 show_source=True 时显示)
================================================================================

============================================================
📄 FILE: README.md (342 行)
============================================================
# Codex CLI
... (完整文件内容)

================================================================================
📝 详细 Diff:
================================================================================
diff --git a/README.md b/README.md
... (完整 diff)
```

**输出示例：**
```
commit 8aca63ca8fbccfd6964874ae219ff677ea125cfb
Author: wrenchoniline <ljl260435988@gmail.com>
Date:   Thu Jun 18 10:46:13 2026 +0800

    docs: 更新 README.md 添加 VFS 模式、上下文压缩和新启动脚本说明

diff --git a/README.md b/README.md
index 5347285..991d469 100648
--- a/README.md
+++ b/README.md
@@ -9,6 +9,8 @@
 - 🔌 **MCP 支持** - 集成 Model Context Protocol，扩展工具生态
...
```

---

### 3. `git_status` - 查看工作区状态
查看当前未提交的改动。

**参数：**
- `show_untracked` (可选): 是否显示未跟踪的文件，默认 True

**示例：**
```python
# 查看当前状态（包括未跟踪文件）
git_status()

# 不显示未跟踪文件
git_status(show_untracked=False)
```

---

### 4. `git_diff` - 查看差异
查看两个 commit 之间或工作区与暂存区的差异。

**参数：**
- `target` (可选): 目标（可以是 commit hash、分支名，或空表示工作区对比暂存区）
- `cached` (可选): 是否对比暂存区与 HEAD，默认 False

**示例：**
```python
# 查看工作区未暂存的改动
git_diff()

# 查看暂存区的改动
git_diff(cached=True)

# 查看与某个 commit 的差异
git_diff(target="HEAD~1")

# 查看两个分支的差异
git_diff(target="main")
```

---

### 5. `pack_for_ai` - 打包代码和 Git 历史 🌟
**核心功能！** 将选中的源代码和 git 历史打包成单个文件，方便发送给其他 AI 求助。

**参数：**
- `config_file` (可选): 配置文件路径（YAML 格式），默认 `upload_config.yaml`
- `include_git` (可选): 是否包含 git 历史，默认 True
- `git_limit` (可选): 包含的 git 提交数量，默认 10

**注意：** `pack_for_ai` 工具会在**配置文件所在的项目目录**中执行 git 命令，确保配置文件放在正确的项目根目录。

**示例：**
```python
# 使用默认配置打包
pack_for_ai()

# 自定义配置
pack_for_ai(config_file="my_config.yaml", include_git=True, git_limit=20)

# 只打包代码，不包含 git 历史
pack_for_ai(include_git=False)
```

**输出文件结构：**
```
================================================================================
📋 代码打包报告 - Code Pack Report
================================================================================
生成时间：2026-06-18 16:13:46
配置文件：D:\workspace\codex-cli\upload_config.yaml
工作目录：D:\workspace\codex-cli

================================================================================
🔗 Git 仓库信息
================================================================================
仓库路径：D:/workspace/codex-cli
当前分支：main

📝 工作区状态:
 M src/codex/tools.py
?? pack_for_ai.py

📜 最近 10 条提交历史:
--------------------------------------------------------------------------------
[1] 8aca63ca
    作者：wrenchoniline <ljl260435988@gmail.com>
    时间：2026-06-18 10:46:13 +0800
    消息：docs: 更新 README.md 添加 VFS 模式、上下文压缩和新启动脚本说明
    ...

================================================================================
📝 Git 详细改动内容
================================================================================
...

================================================================================
📁 源代码内容
================================================================================

================================================================================
📄 FILE: src/codex/tools.py (595 行)
================================================================================
...

================================================================================
📈 统计摘要
================================================================================
总文件数：16
总代码行数：4323
文件列表:
  README.md: 235 行
  src/codex/tools.py: 595 行
  ...
```

---

### 6. `export_commit` - 单独导出某个 commit 🌟
将某个 commit 的详细改动导出到独立的 TXT 文件，方便单独询问 AI。

**参数：**
- `commit_hash` (必填): 提交 hash（可以是短 hash）
- `output_file` (可选): 输出文件名，默认 `commit_{hash}.txt`

**示例：**
```python
# 导出某个 commit
export_commit(commit_hash="8aca63ca")

# 自定义输出文件名
export_commit(commit_hash="8aca63ca", output_file="my_change.txt")
```

**输出文件示例：**
```
================================================================================
📝 Commit: 8aca63ca
================================================================================

commit 8aca63ca8fbccfd6964874ae219ff677ea125cfb
Author: wrenchoniline <ljl260435988@gmail.com>
Date:   Thu Jun 18 10:46:13 2026 +0800

    docs: 更新 README.md 添加 VFS 模式、上下文压缩和新启动脚本说明

diff --git a/README.md b/README.md
...
```

---

## 📝 配置文件说明

`pack_for_ai` 使用 YAML 配置文件来选择要包含的文件。

**示例配置 (`upload_config.yaml`)：**
```yaml
output_file: selected_code.txt
include:
  # 🐍 Python 源码
  - "src/codex/*.py"
  - "src/codex/mcp/*.py"
  - "gateway/*.py"
  - "main.py"
  
  # 📄 配置文件和文档
  - "*.yaml"
  - "*.md"
  - "docs/*.md"

# Git 设置（可选）
git_settings:
  include_git: true      # 是否包含 git 提交历史
  commit_limit: 10       # 包含最近多少次提交
```

---

## 🚀 命令行使用

`pack_for_ai` 模块已内置到 Codex 中，支持命令行直接运行：

```bash
# 使用默认配置打包
python -m src.codex.pack_for_ai

# 使用自定义配置
python -m src.codex.pack_for_ai my_config.yaml

# 单独导出某个 commit
python -m src.codex.pack_for_ai --commit 8aca63ca

# 查看帮助
python -m src.codex.pack_for_ai --help
```

---

## 💡 典型使用场景

### 场景 1：向其他 AI 求助代码问题
```python
# 1. 打包相关代码和 git 历史
pack_for_ai()

# 2. 发送生成的 selected_code.txt 给 AI
# 文件位置：D:\workspace\codex-cli\selected_code.txt
```

### 场景 2：询问特定 commit 的改动
```python
# 1. 查看最近的提交
git_log(limit=5)

# 2. 导出感兴趣的 commit
export_commit(commit_hash="8aca63ca")

# 3. 发送 commit_8aca63ca.txt 给 AI，询问这个改动的意图
```

### 场景 3：代码审查
```python
# 1. 查看某人最近的提交
git_log(author="wrenchoniline", limit=10)

# 2. 查看具体改动
git_show(commit_hash="8aca63ca", max_lines=300)

# 3. 查看当前工作区状态
git_status()
```

### 场景 4：对比分支差异
```python
# 查看当前分支与 main 的差异
git_diff(target="main")

# 查看暂存区的改动
git_diff(cached=True)
```

---

## 📊 工具集成

所有工具已集成到 Codex CLI 的工具系统中，AI 可以自动调用这些工具来：
- 查看代码历史
- 理解改动内容
- 打包上下文
- 生成报告

**查看可用工具：**
```python
from src.codex.tools import list_tools
print(list_tools())
```

---

## ⚠️ 注意事项

1. **Git 仓库检测**：所有 git 工具需要在 git 仓库目录下运行
2. **输出大小**：`git_show` 和 `pack_for_ai` 可能生成大文件，注意使用 `max_lines` 限制
3. **配置文件**：确保 `upload_config.yaml` 中的文件路径正确
4. **编码**：所有输出文件使用 UTF-8 编码

---

## 🎯 下一步

现在你可以：
1. 使用 `pack_for_ai()` 打包代码求助其他 AI
2. 使用 `export_commit()` 单独导出某个改动
3. 使用 `git_show()` 直接查看 commit 详情
4. 在对话中让 AI 自动调用这些工具分析代码历史