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
from typing import Any

from file_editor import (
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
                    "regex": {"type": ["boolean", "string"], "description": "是否使用正则表达式。默认 'auto' 会自动检测 pattern 中的正则特殊字符", "default": "auto", "enum": [true, false, "auto"]},
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
                    "regex": {"type": ["boolean", "string"], "description": "是否使用正则表达式。默认 'auto' 会自动检测 pattern 中的正则特殊字符", "default": "auto", "enum": [true, false, "auto"]},
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
    def __init__(self, workdir: str, auto_approve: bool = False):
        self.workdir = workdir
        self.auto_approve = auto_approve
        self._pending_writes: dict[str, str] = {}   # path -> diff (等待审批)

    def _resolve(self, path: str) -> str:
        """将相对路径解析为工作目录下的绝对路径。"""
        if os.path.isabs(path):
            return path
        return os.path.join(self.workdir, path)

    def execute(self, name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """分发工具调用，返回 (success, output)。"""
        try:
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
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                errors="replace",
                cwd=workdir,
                timeout=timeout,
            )
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

        else:
            return False, f"❌ 未知工具: {name}"