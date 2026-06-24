# tools.py
"""
工具定义 + 执行器。
每个工具返回 (success: bool, output: str)。
"""

import json
import os
import subprocess
import traceback
from pathlib import Path
from typing import Any, Optional

from src.codex.file_editor import (
    apply_patch,
    delete_lines,
    insert_lines,
    list_directory,
    read_file,
    replace_lines,
    search_in_files,
    search_replace,
    write_file,
)

# ──────────────────────────────────────────────
# 工具 Schema（发给模型）
# ──────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容，支持显示行号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "start_line": {"type": "integer", "description": "起始行（1-based，可选）"},
                    "end_line": {"type": "integer", "description": "结束行（1-based，可选）"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入（新建或覆盖）文件的完整内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "文件的完整新内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_replace",
            "description": "在文件中搜索字符串并替换。支持正则。精确替换某段代码的首选工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "search": {"type": "string", "description": "要搜索的文本（精确匹配或正则）"},
                    "replace": {"type": "string", "description": "替换成的文本"},
                    "count": {"type": "integer", "description": "最多替换次数，0=全部", "default": 0},
                    "regex": {"type": ["boolean", "string"], "description": "是否使用正则表达式。默认 'auto' 会自动检测 pattern 中的正则特殊字符", "default": "auto", "enum": [True, False, "auto"]},
                },
                "required": ["path", "search", "replace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_lines",
            "description": "在指定行之后插入新行。after_line=0 插到文件开头。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "after_line": {"type": "integer", "description": "在此行之后插入（1-based，0=开头）"},
                    "text": {"type": "string", "description": "要插入的文本"},
                },
                "required": ["path", "after_line", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_lines",
            "description": "删除文件中指定范围的行（含两端）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "description": "起始行（1-based）"},
                    "end_line": {"type": "integer", "description": "结束行（1-based）"},
                },
                "required": ["path", "start_line", "end_line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_lines",
            "description": "用新文本替换文件中指定范围的行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "new_text": {"type": "string", "description": "替换后的文本"},
                },
                "required": ["path", "start_line", "end_line", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "应用 unified diff 格式的 patch 文件到工作区。",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch_text": {"type": "string", "description": "完整的 unified diff 内容"},
                    "base_dir": {"type": "string", "description": "应用 patch 的根目录", "default": "."},
                },
                "required": ["patch_text"],
            },
        },
    },
{
        "type": "function",
        "function": {
            "name": "search_in_files",
            "description": "在目录中全文搜索关键词，返回匹配的行。支持正则、大小写控制、上下文显示和文件排除。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "搜索模式（字符串或正则）"},
                    "directory": {"type": "string", "description": "搜索目录", "default": "."},
                    "file_glob": {"type": "string", "description": "文件 glob 模式，默认 **/*", "default": "**/*"},
                    "regex": {"type": ["boolean", "string"], "description": "是否使用正则表达式。默认 'auto' 会自动检测 pattern 中的正则特殊字符", "default": "auto", "enum": [True, False, "auto"]},
                    "max_results": {"type": "integer", "description": "最大结果数", "default": 50},
                    "case_sensitive": {"type": "boolean", "description": "是否区分大小写", "default": True},
                    "context_lines": {"type": "integer", "description": "上下文行数（前后各显示多少行）", "default": 0},
                    "exclude_glob": {"type": "string", "description": "排除的文件 glob 模式，逗号分隔（如 *.log, **/test/**）", "default": ""},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "列出目录树结构。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "."},
                    "depth": {"type": "integer", "default": 2},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": "执行 shell 命令（在工作目录下）。用于运行测试、安装依赖、git 操作等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                    "workdir": {"type": "string", "description": "工作目录，默认当前目录"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认 60", "default": 60},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diff_files",
            "description": "对比两个文件或同一文件的两个版本，返回 unified diff。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path_a": {"type": "string"},
                    "path_b": {"type": "string"},
                },
                "required": ["path_a", "path_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "获取 git 提交历史。返回最近的提交记录列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "获取的提交数量", "default": 1},
                    "author": {"type": "string", "description": "按作者过滤（可选）"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_show",
            "description": "获取指定 commit 的详细信息和代码改动（diff）。用于查看某人提交了什么、改了什么代码。",
            "parameters": {
                "type": "object",
                "properties": {
                    "commit_hash": {"type": "string", "description": "提交 hash（可以是短 hash，如 8aca63ca）"},
                    "max_lines": {"type": "integer", "description": "最大返回行数，防止输出过长", "default": 500},
                    "show_source": {"type": "boolean", "description": "是否显示修改后的完整源代码（如果文件还存在）", "default": False},
                },
                "required": ["commit_hash"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "获取当前 git 工作区状态，显示未提交的改动。",
            "parameters": {
                "type": "object",
                "properties": {
                    "show_untracked": {"type": "boolean", "description": "是否显示未跟踪的文件", "default": True},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "获取两个 commit 之间或当前工作区与暂存区的差异。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标（可以是 commit hash、分支名，或空表示工作区对比暂存区）"},
                    "cached": {"type": "boolean", "description": "是否对比暂存区与 HEAD", "default": False},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pack_for_ai",
            "description": "打包源代码和 git 历史到单个文件，方便发送给其他 AI 求助。支持配置文件选择要包含的文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "config_file": {"type": "string", "description": "配置文件路径（YAML 格式），默认 upload_config.yaml", "default": "upload_config.yaml"},
                    "include_git": {"type": "boolean", "description": "是否包含 git 历史", "default": True},
                    "git_limit": {"type": "integer", "description": "包含的 git 提交数量", "default": 1},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_commit",
            "description": "单独导出某个 commit 的详细改动到 TXT 文件，方便发给 AI 询问具体改动。",
            "parameters": {
                "type": "object",
                "properties": {
                    "commit_hash": {"type": "string", "description": "提交 hash（可以是短 hash）"},
                    "output_file": {"type": "string", "description": "输出文件名，默认 commit_{hash}.txt"},
                },
                "required": ["commit_hash"],
            },
        },
    },
]

# ──────────────────────────────────────────────
# 工具集列表函数
# ──────────────────────────────────────────────

def list_tools() -> str:
    """返回格式化的工具集列表。"""
    output = [
        "╔═══════════════════════════════════════════════════════════╗",
        "║                    可用工具集                           ║",
        "╚═══════════════════════════════════════════════════════════╝",
        ""
    ]
    
    for i, tool in enumerate(TOOLS, 1):
        func = tool["function"]
        name = func["name"]
        desc = func["description"]
        params = func["parameters"]["properties"]
        required = func["parameters"].get("required", [])
        
        output.append(f"【{i:2d}】 {name}")
        output.append(f"      描述：{desc}")
        
        if params:
            output.append("      参数:")
            for param_name, param_info in params.items():
                req_mark = "必填" if param_name in required else "可选"
                param_type = param_info.get("type", "any")
                param_desc = param_info.get("description", "")
                default = param_info.get("default", None)
                default_str = f"，默认：{default}" if default is not None else ""
                output.append(f"        • {param_name} ({param_type}) [{req_mark}]")
                output.append(f"          └─ {param_desc}{default_str}")
        
        output.append("")
    
    output.append("─" * 60)
    output.append(f"共计 {len(TOOLS)} 个工具")
    return "\n".join(output)


# ──────────────────────────────────────────────
# 执行器
# ──────────────────────────────────────────────

class ToolExecutor:
    def __init__(self, workdir: str, auto_approve: bool = False, mcp_manager=None, vfs_mode: bool = False):
        self.workdir = workdir
        self.auto_approve = auto_approve
        self.mcp_manager = mcp_manager  # 注入 MCP 管理器
        self.vfs_mode = vfs_mode  # 虚拟文件系统模式
        self._pending_writes: dict[str, str] = {}   # path -> diff (等待审批)

    def _resolve(self, path: str) -> str:
        """将相对路径解析为工作目录下的绝对路径。"""
        if os.path.isabs(path):
            return path
        return os.path.join(self.workdir, path)

    async def execute(self, name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """分发工具调用，返回 (success, output)。"""
        try:
            # VFS 模式：屏蔽本地文件操作工具，只允许通过 MCP 调用虚拟文件系统
            if self.vfs_mode:
                # 定义被屏蔽的本地工具列表
                blocked_local_tools = [
                    "read_file", "write_file", "search_replace", "insert_lines",
                    "delete_lines", "replace_lines", "apply_patch", "search_in_files",
                    "list_directory", "diff_files"
                ]
                if name in blocked_local_tools:
                    # 尝试使用 VFS 前缀的 MCP 工具
                    vfs_tool_name = f"vfs_{name}"
                    if self.mcp_manager and any(t["function"]["name"] == vfs_tool_name for t in self.mcp_manager.get_all_tools()):
                        output = await self.mcp_manager.call_tool(vfs_tool_name, args)
                        return True, output
                    # 如果没有对应的 VFS 工具，返回错误提示
                    return False, f"❌ VFS 模式：本地工具 '{name}' 已被禁用，请使用 MCP 虚拟文件系统工具"
            
            # 如果匹配到 MCP 工具，交给 MCP 执行
            if self.mcp_manager and any(t["function"]["name"] == name for t in self.mcp_manager.get_all_tools()):
                output = await self.mcp_manager.call_tool(name, args)
                return True, output
                
            return self._dispatch(name, args)
        except FileNotFoundError as e:
            return False, f"❌ 文件未找到: {e}"
        except ValueError as e:
            return False, f"❌ 参数错误: {e}"
        except Exception as e:
            return False, f"❌ 错误: {e}\n{traceback.format_exc()}"

    def _dispatch(self, name: str, args: dict) -> tuple[bool, str]:
        # ── read_file ──────────────────────────────────
        if name == "read_file":
            path = self._resolve(args["path"])
            content = read_file(path)
            lines = content.splitlines()
            start_line = args.get("start_line", 1)
            end_line = args.get("end_line", len(lines))
            # 兼容字符串类型的行号（从 JSON 传递时可能是字符串）
            if isinstance(start_line, str):
                start_line = int(start_line)
            if isinstance(end_line, str):
                end_line = int(end_line)
            start = start_line - 1
            end = end_line
            slice_lines = lines[start:end]
            numbered = "\n".join(
                f"{start + i + 1:4d} │ {l}" for i, l in enumerate(slice_lines)
            )
            return True, f"📄 {args['path']} ({len(lines)} 行)\n\n{numbered}"

        # ── write_file ─────────────────────────────────
        elif name == "write_file":
            path = self._resolve(args["path"])
            diff = write_file(path, args["content"], dry_run=not self.auto_approve)
            if not self.auto_approve:
                return True, f"__PENDING_WRITE__\n路径: {args['path']}\n\n{diff}"
            return True, f"✅ 已写入: {args['path']}\n\n{diff}"

        # ── search_replace ─────────────────────────────
        elif name == "search_replace":
            path = self._resolve(args["path"])
            diff = search_replace(
                path,
                args["search"],
                args["replace"],
                count=args.get("count", 0),
                regex=args.get("regex", False),
                dry_run=not self.auto_approve,
            )
            if not self.auto_approve:
                return True, f"__PENDING_WRITE__\n路径: {args['path']}\n\n{diff}"
            return True, f"✅ 替换完成: {args['path']}\n\n{diff}"

        # ── insert_lines ───────────────────────────────
        elif name == "insert_lines":
            path = self._resolve(args["path"])
            after_line = args["after_line"]
            if isinstance(after_line, str):
                after_line = int(after_line)
            diff = insert_lines(
                path,
                after_line,
                args["text"],
                dry_run=not self.auto_approve,
            )
            if not self.auto_approve:
                return True, f"__PENDING_WRITE__\n路径: {args['path']}\n\n{diff}"
            return True, f"✅ 插入完成: {args['path']}\n\n{diff}"

        # ── delete_lines ───────────────────────────────
        elif name == "delete_lines":
            path = self._resolve(args["path"])
            start_line = args["start_line"]
            end_line = args["end_line"]
            if isinstance(start_line, str):
                start_line = int(start_line)
            if isinstance(end_line, str):
                end_line = int(end_line)
            diff = delete_lines(
                path,
                start_line,
                end_line,
                dry_run=not self.auto_approve,
            )
            if not self.auto_approve:
                return True, f"__PENDING_WRITE__\n路径: {args['path']}\n\n{diff}"
            return True, f"✅ 删除完成: {args['path']}\n\n{diff}"

        # ── replace_lines ──────────────────────────────
        elif name == "replace_lines":
            path = self._resolve(args["path"])
            start_line = args["start_line"]
            end_line = args["end_line"]
            if isinstance(start_line, str):
                start_line = int(start_line)
            if isinstance(end_line, str):
                end_line = int(end_line)
            diff = replace_lines(
                path,
                start_line,
                end_line,
                args["new_text"],
                dry_run=not self.auto_approve,
            )
            if not self.auto_approve:
                return True, f"__PENDING_WRITE__\n路径: {args['path']}\n\n{diff}"
            return True, f"✅ 行替换完成: {args['path']}\n\n{diff}"

# ── apply_patch ────────────────────────────────
        elif name == "apply_patch":
            result = apply_patch(
                args["patch_text"],
                base_dir=self._resolve(args.get("base_dir", ".")),
                dry_run=not self.auto_approve,
            )
            return True, f"✅ Patch 应用成功\n{result}"

        # ── search_in_files ────────────────────────────
        elif name == "search_in_files":
            max_results = args.get("max_results", 50)
            if isinstance(max_results, str):
                max_results = int(max_results)
            hits = search_in_files(
                args["pattern"],
                directory=self._resolve(args.get("directory", ".")),
                file_glob=args.get("file_glob", "**/*"),
                regex=args.get("regex", "auto"),
                max_results=max_results,
                case_sensitive=args.get("case_sensitive", True),
                context_lines=args.get("context_lines", 0),
                exclude_glob=args.get("exclude_glob", ""),
            )
            if not hits:
                return True, "🔍 未找到匹配结果。"
            
            # 提取统计信息
            stats = hits[0].pop("_stats", None) if hits else None
            stats_str = f"\n\n📊 统计：搜索了 {stats['files_searched']} 个文件，{stats['files_matched']} 个文件包含匹配项" if stats else ""
            
            lines = [f"🔍 找到 {len(hits)} 处匹配:{stats_str}\n"]
            for h in hits:
                ctx_before = h.get("context_before", [])
                ctx_after = h.get("context_after", [])
                rel_path = h.get("rel_path", h['file'])
                
                # 构建带上下文的输出
                entry_lines = []
                entry_lines.append(f"  📁 {rel_path}:{h['line_no']}")
                
                # 显示上下文前
                if ctx_before:
                    for i, ctx_line in enumerate(ctx_before, 1):
                        entry_lines.append(f"     {h['line_no'] - len(ctx_before) + i - 1}: {ctx_line}")
                
                # 显示匹配行（高亮）
                entry_lines.append(f"  → {h['line_no']}: {h['line'].strip()}")
                
                # 显示上下文后
                if ctx_after:
                    for i, ctx_line in enumerate(ctx_after, 1):
                        entry_lines.append(f"     {h['line_no'] + i}: {ctx_line}")
                
                lines.append("\n".join(entry_lines))
            
            return True, "\n".join(lines)

        # ── list_directory ─────────────────────────────
        elif name == "list_directory":
            tree = list_directory(
                self._resolve(args.get("path", ".")),
                depth=int(args.get("depth", 2)),
            )
            return True, tree

        # ── execute_shell ──────────────────────────────
        elif name == "execute_shell":
            # 如果未指定 workdir，默认使用 Agent 的工作目录
            if "workdir" in args:
                workdir = self._resolve(args["workdir"])
            else:
                workdir = self.workdir
            timeout = int(args.get("timeout", 60))
            cmd = args["command"]
            
            # Windows 下需要创建新的进程组，以便超时时可以终止整个进程树
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            
            proc = None
            try:
                proc = subprocess.Popen(
                    cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors="replace",
                    cwd=workdir,
                    creationflags=creationflags,
                )
                stdout, stderr = proc.communicate(timeout=timeout)
                result = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
            except subprocess.TimeoutExpired as e:
                # Windows 下需要显式终止整个进程树
                if proc is not None and os.name == "nt":
                    try:
                        # 使用 taskkill 终止整个进程树（包括所有子进程）
                        subprocess.run(
                            f"taskkill /F /T /PID {proc.pid}",
                            shell=True,
                            capture_output=True,
                            timeout=5,
                        )
                    except Exception:
                        pass  # 忽略 taskkill 失败
                    try:
                        proc.kill()
                    except Exception:
                        pass
                # 获取已输出的内容
                try:
                    stdout, stderr = proc.communicate(timeout=1)
                except Exception:
                    stdout, stderr = "", ""
                return False, f"❌ 命令执行超时（{timeout}秒）\n\n部分输出:\nSTDOUT:\n{stdout or ''}\nSTDERR:\n{stderr or ''}"
            
            out = ""
            if result.stdout:
                out += f"STDOUT:\n{result.stdout}"
            if result.stderr:
                out += f"\nSTDERR:\n{result.stderr}"
            status = "✅" if result.returncode == 0 else "❌"
            return result.returncode == 0, f"{status} exit={result.returncode}\n{out}"

        # ── diff_files ─────────────────────────────────
        elif name == "diff_files":
            from file_editor import _make_diff, _read
            a = self._resolve(args["path_a"])
            b = self._resolve(args["path_b"])
            diff = _make_diff(_read(a), _read(b), args["path_a"])
            return True, diff or "(文件相同)"
# ── git_log ─────────────────────────────────
        elif name == "git_log":
            limit = int(args.get("limit", 1))
            author = args.get("author", "")
            
            cmd = ["git", "log", f"-{limit}", "--pretty=format:%H|%an|%ae|%ai|%s", "--no-merges"]
            if author:
                cmd.extend(["--author", author])
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=self.workdir)
                commits = []
                for line in result.stdout.strip().split("\n"):
                    if line:
                        parts = line.split("|", 4)
                        if len(parts) == 5:
                            commits.append({
                                "hash": parts[0],
                                "author": parts[1],
                                "email": parts[2],
                                "date": parts[3],
                                "message": parts[4]
                            })
                
                if not commits:
                    return True, "📝 没有找到提交记录"
                
                output = [f"📜 最近 {len(commits)} 条提交历史:\n"]
                for i, c in enumerate(commits, 1):
                    output.append(f"[{i}] {c['hash'][:8]} | {c['author']} | {c['date'][:10]}")
                    output.append(f"    └─ {c['message']}")
                
                return True, "\n".join(output)
            except subprocess.CalledProcessError as e:
                return False, f"❌ git log 失败：{e}"

        # ── git_show ─────────────────────────────────
        elif name == "git_show":
            commit_hash = args["commit_hash"]
            max_lines = int(args.get("max_lines", 500))
            show_source = args.get("show_source", False)  # 是否显示修改后的完整源代码
            
            try:
                # 第一步：获取提交信息和 diff
                result = subprocess.run(
                    ["git", "show", "--pretty=full", "--stat", "-p", commit_hash],
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=self.workdir
                )
                
                output_parts = []
                output_parts.append("=" * 80)
                output_parts.append(f"📝 Commit: {commit_hash}")
                output_parts.append("=" * 80)
                output_parts.append("")
                
                # 解析输出，分离 commit 信息和文件改动统计
                raw_lines = result.stdout.split("\n")
                
                # 提取 commit 信息（到第一个 diff --git 之前）
                commit_info_lines = []
                changed_files = []
                in_diff = False
                
                for line in raw_lines:
                    if line.startswith("diff --git"):
                        in_diff = True
                        # 提取文件名（从 b/ 后面取）
                        # 格式：diff --git a/file.txt b/file.txt
                        match_parts = line.split(" b/")
                        if len(match_parts) == 2:
                            file_path = match_parts[1].strip()
                            changed_files.append(file_path)
                    if not in_diff:
                        commit_info_lines.append(line)
                
                # 添加 commit 信息
                output_parts.extend(commit_info_lines)
                output_parts.append("")
                output_parts.append("-" * 80)
                output_parts.append(f"📁 修改的文件 ({len(changed_files)} 个):")
                for f in changed_files:
                    output_parts.append(f"  • {f}")
                output_parts.append("")
                
                # 如果 show_source 为 True，读取并显示修改后的文件内容
                if show_source and changed_files:
                    output_parts.append("=" * 80)
                    output_parts.append("📄 修改后的源代码内容:")
                    output_parts.append("=" * 80)
                    
                    for file_path in changed_files:
                        full_path = self._resolve(file_path)
                        if os.path.exists(full_path):
                            try:
                                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                    content = f.read()
                                    lines_count = len(content.split("\n"))
                                    output_parts.append("")
                                    output_parts.append(f"{'='*60}")
                                    output_parts.append(f"📄 FILE: {file_path} ({lines_count} 行)")
                                    output_parts.append(f"{'='*60}")
                                    output_parts.append(content)
                            except Exception as e:
                                output_parts.append(f"⚠️  无法读取 {file_path}: {e}")
                        else:
                            output_parts.append(f"⚠️  文件已删除或不存在：{file_path}")
                    output_parts.append("")
                
                # 添加详细 diff（如果空间允许）
                remaining_lines = max_lines - len(output_parts)
                if remaining_lines > 50:
                    output_parts.append("=" * 80)
                    output_parts.append("📝 详细 Diff:")
                    output_parts.append("=" * 80)
                    
                    # 重新获取带完整 diff 的输出
                    diff_result = subprocess.run(
                        ["git", "show", "-p", commit_hash],
                        capture_output=True,
                        text=True,
                        check=True,
                        cwd=self.workdir
                    )
                    diff_lines = diff_result.stdout.split("\n")
                    
                    if len(diff_lines) > remaining_lines:
                        output_parts.extend(diff_lines[:remaining_lines])
                        output_parts.append(f"\n... (diff 被截断，共超过 {remaining_lines} 行)")
                    else:
                        output_parts.extend(diff_lines)
                
                final_output = "\n".join(output_parts)
                if len(final_output.split("\n")) > max_lines:
                    final_lines = final_output.split("\n")[:max_lines]
                    final_lines.append(f"\n... (总输出被截断，共超过 {max_lines} 行)")
                    final_output = "\n".join(final_lines)
                
                return True, final_output
            except subprocess.CalledProcessError as e:
                return False, f"❌ git show 失败：{e}"

        # ── git_status ─────────────────────────────────
        elif name == "git_status":
            show_untracked = args.get("show_untracked", True)
            
            try:
                cmd = ["git", "status"]
                if not show_untracked:
                    cmd.append("--untracked-files=no")
                
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=self.workdir)
                return True, f"📝 Git 工作区状态:\n{result.stdout}"
            except subprocess.CalledProcessError as e:
                return False, f"❌ git status 失败：{e}"

        # ── git_diff ─────────────────────────────────
        elif name == "git_diff":
            target = args.get("target", "")
            cached = args.get("cached", False)
            
            try:
                cmd = ["git", "diff"]
                if cached:
                    cmd.append("--cached")
                if target:
                    cmd.append(target)
                
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=self.workdir)
                
                if not result.stdout.strip():
                    return True, "📝 没有差异"
                
                return True, f"📊 Git 差异:\n{result.stdout}"
            except subprocess.CalledProcessError as e:
                return False, f"❌ git diff 失败：{e}"

        # ── pack_for_ai ─────────────────────────────────
        elif name == "pack_for_ai":
            config_file = args.get("config_file", "upload_config.yaml")
            include_git = args.get("include_git", True)
            git_limit = int(args.get("git_limit", 1))
            
            config_path = self._resolve(config_file)
            
            if not os.path.exists(config_path):
                return False, f"❌ 配置文件不存在：{config_path}"
            
            # 导入 pack_for_ai 模块（内置在 src.codex.pack_for_ai）
            from src.codex.pack_for_ai import pack_for_ai as pack_func
            
            # 执行打包（传入当前工作目录，确保 git 命令在正确的项目目录执行）
            output_file = pack_func(
                config_path=config_path,
                include_git=include_git,
                git_limit=git_limit,
                cwd=self.workdir  # 使用工具执行器的工作目录
            )
            
            if output_file:
                return True, f"✅ 打包完成！\n输出文件：{output_file}\n\n可以直接发送这个文件给其他 AI 求助。"
            else:
                return False, "❌ 打包失败"

        # ── export_commit ─────────────────────────────────
        elif name == "export_commit":
            commit_hash = args["commit_hash"]
            output_file = args.get("output_file", "")
            
            # 导入 pack_for_ai 模块（内置在 src.codex.pack_for_ai）
            from src.codex.pack_for_ai import export_single_commit
            
            if not output_file:
                output_file = f"commit_{commit_hash[:8]}.txt"
            
            result_file = export_single_commit(commit_hash, output_file)
            
            if result_file:
                return True, f"✅ 已导出 commit {commit_hash[:8]}\n文件：{result_file}\n\n可以发送这个文件给 AI 询问具体改动。"
            else:
                return False, f"❌ 导出失败，请检查 commit hash 是否正确：{commit_hash}"

        else:
            return False, f"❌ 未知工具: {name}"