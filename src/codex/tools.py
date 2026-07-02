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

# 可选的 SSH 远程模块
try:
    from src.codex.remote import remote_manager, get_remote_tools, REMOTE_AVAILABLE
except ImportError:
    remote_manager = None
    get_remote_tools = lambda: []
    REMOTE_AVAILABLE = False

# ──────────────────────────────────────────────
# 工具 Schema（发给模型）
# ──────────────────────────────────────────────

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "verify_task",
            "description": "【任务完成前必须调用】执行质量验证（编译/测试/git diff）。只在所有代码修改完成后调用一次，不要重复调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "acceptance_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "验收项列表（可选），用于逐项核对"
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_lessons",
            "description": "【仅在修复重复错误后调用】记录教训到 lessons.md。不要为每个错误都调用，只在同一类错误第二次出现时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "简短标题，如'尾随空格导致 diff 失败'"
                    },
                    "description": {
                        "type": "string",
                        "description": "问题现象描述"
                    },
                    "root_cause": {
                        "type": "string",
                        "description": "根本原因分析"
                    },
                    "rule": {
                        "type": "string",
                        "description": "正确做法/规则"
                    },
                    "regression_check": {
                        "type": "string",
                        "description": "回归检查命令（可选），如'git diff --check'"
                    }
                },
                "required": ["title", "description", "root_cause", "rule"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_task_contract",
            "description": "【仅在任务开始时调用一次】记录任务目标和范围。后续实现中不要重复调用，除非需求范围发生变化。",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "用户想要实现什么（用一句话描述）"
                    },
                    "acceptance_items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "验收项列表（可选），如'能正常运行'、'测试通过'"
                    },
                    "not_in_scope": {
                        "type": "string",
                        "description": "明确不做的内容（可选），避免范围蔓延"
                    },
                    "affected_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "预计要修改的文件（可选）"
                    }
                },
                "required": ["goal"],
            },
        },
    },
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

# 添加 SSH 远程工具（如果模块可用）
TOOLS.extend(get_remote_tools())

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

    def _verify_task(self, acceptance_items: list[str]) -> tuple[bool, str]:
        """
        执行项目质量验证。
        自动分析项目类型，动态生成验证命令。
        返回验证结果。
        """
        import yaml

        quality_path = os.path.join(self.workdir, "agent", "quality.yaml")
        results = []
        all_passed = True

        # 自动分析项目类型并生成验证命令
        def auto_detect_commands():
            """根据项目文件结构自动检测项目类型并生成验证命令"""
            commands = {}

            # 始终包含 git diff 检查
            commands["diff_check"] = {
                "command": "git diff --check",
                "required": True,
                "description": "检查是否有 whitespace 错误或合并冲突标记"
            }

            # 检测 Python 项目
            has_pyproject = os.path.exists(os.path.join(self.workdir, "pyproject.toml"))
            has_setup_py = os.path.exists(os.path.join(self.workdir, "setup.py"))
            has_requirements = os.path.exists(os.path.join(self.workdir, "requirements.txt"))
            py_files = []
            for root, dirs, files in os.walk(self.workdir):
                # 跳过常见非源码目录
                if any(skip in root for skip in ["__pycache__", ".git", "node_modules", "venv", ".venv", "dist", "build"]):
                    continue
                for f in files:
                    if f.endswith(".py"):
                        py_files.append(os.path.join(root, f))

            if has_pyproject or has_setup_py or has_requirements or len(py_files) > 0:
                # Python 项目
                if py_files:
                    # 限制文件数量，避免命令过长
                    py_files_str = " ".join(py_files[:20])
                    commands["lint"] = {
                        "command": f"python -m py_compile {py_files_str}",
                        "required": True,
                        "description": "Python 语法检查"
                    }
                if has_pyproject:
                    commands["build"] = {
                        "command": "python -c \"import sys; sys.path.insert(0, '.'); import src\"" if os.path.exists(os.path.join(self.workdir, "src")) else "python -c \"print('Python project')\"",
                        "required": False,
                        "description": "Python 导入检查"
                    }
                # 检测是否有测试
                test_dirs = ["tests", "test", "spec"]
                has_tests = any(os.path.exists(os.path.join(self.workdir, d)) for d in test_dirs)
                if has_tests:
                    commands["test"] = {
                        "command": "python -m pytest tests/ -v --tb=short",
                        "required": False,
                        "description": "运行单元测试"
                    }

            # 检测 Node.js 项目
            has_package_json = os.path.exists(os.path.join(self.workdir, "package.json"))
            if has_package_json:
                # Node.js 项目
                commands["lint"] = {
                    "command": "npm run lint 2>nul || eslint . --ext .ts,.tsx,.js,.jsx 2>nul || echo 'No lint config found'",
                    "required": False,
                    "description": "JavaScript/TypeScript 代码检查"
                }
                commands["build"] = {
                    "command": "npm run build 2>nul || tsc --noEmit 2>nul || echo 'No build script'",
                    "required": False,
                    "description": "构建或类型检查"
                }
                commands["test"] = {
                    "command": "npm test 2>nul || jest 2>nul || echo 'No test config'",
                    "required": False,
                    "description": "运行测试"
                }

            # 检测 Zig 项目
            has_build_zig = os.path.exists(os.path.join(self.workdir, "build.zig"))
            if has_build_zig:
                commands["lint"] = {
                    "command": "zig ast-check src/*.zig 2>nul || echo 'No Zig source found'",
                    "required": False,
                    "description": "Zig 语法检查"
                }
                commands["build"] = {
                    "command": "zig build --summary all",
                    "required": False,
                    "description": "Zig 项目构建"
                }

            return commands

        # 优先自动检测项目类型，配置文件仅作为可选覆盖
        detected_commands = auto_detect_commands()
        completion_rules = {}
        rules = []

        # 如果配置文件存在，可以覆盖自动检测的命令
        if os.path.exists(quality_path):
            try:
                with open(quality_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                    # 只使用配置文件中的 completion 规则和 rules
                    completion_rules = config.get("completion", {})
                    rules = config.get("rules", [])
                    # 如果配置文件中明确定义了 commands，则使用配置文件的（向后兼容）
                    # 否则使用自动检测的命令
                    if config.get("commands"):
                        commands = config.get("commands", {})
                        results.append("ℹ️  使用 quality.yaml 中定义的验证命令\n")
                    else:
                        commands = detected_commands
                        results.append("ℹ️  quality.yaml 未定义 commands，已自动检测项目类型并生成验证命令\n")
            except Exception as e:
                results.append(f"⚠️  读取 quality.yaml 失败：{e}，将使用自动检测\n")
                commands = detected_commands
        else:
            # 自动检测项目类型
            commands = detected_commands
            results.append("ℹ️  未找到 quality.yaml，已自动检测项目类型并生成验证命令\n")

        results.append("═══ 任务验证报告 ═══\n")

        # 执行验证命令
        for cmd_name, cmd_config in commands.items():
            command = cmd_config.get("command", "")
            required = cmd_config.get("required", False)
            description = cmd_config.get("description", "")

            if not command:
                continue

            results.append(f"🔧 执行：{cmd_name}")
            if description:
                results.append(f"   说明：{description}")
            results.append(f"   命令：{command}")

            try:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    errors="replace",
                    cwd=self.workdir,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                )
                stdout, stderr = proc.communicate(timeout=60)
                success = proc.returncode == 0

                if success:
                    results.append(f"   结果：✅ 通过")
                else:
                    results.append(f"   结果：❌ 失败 (exit={proc.returncode})")
                    if stdout.strip():
                        results.append(f"   输出：{stdout[:500]}")
                    if stderr.strip():
                        results.append(f"   错误：{stderr[:500]}")
                    all_passed = False
                    if required:
                        results.append(f"   ⚠️  这是必需通过的命令")

            except subprocess.TimeoutExpired:
                proc.kill()
                results.append(f"   结果：❌ 超时")
                all_passed = False
                if required:
                    results.append(f"   ⚠️  这是必需通过的命令")
            except Exception as e:
                results.append(f"   结果：❌ 执行异常：{e}")
                all_passed = False

            results.append("")

        # 验收项核对
        if acceptance_items:
            results.append("═══ 验收项核对 ═══")
            for i, item in enumerate(acceptance_items, 1):
                results.append(f"  [ ] {item}")
            results.append("")
            results.append("⚠️  请逐项确认以上验收项是否全部完成")
            results.append("")

        # 规则提醒
        if rules:
            results.append("═══ 项目规则提醒 ═══")
            for rule in rules:
                results.append(f"  ⚠️  {rule}")
            results.append("")

        # 完成条件检查
        completion_config = completion_rules or {}
        require_clean_diff = completion_config.get("require_clean_diff_check", True)
        require_all = completion_config.get("require_all_commands", False)

        results.append("═══ 完成条件检查 ═══")
        if require_clean_diff and not all_passed:
            results.append("❌ 存在未通过的验证命令，不得宣称任务完成")
        if require_all and not all_passed:
            results.append("❌ 配置要求所有命令必须通过，但当前有失败项")

        results.append("")
        if all_passed:
            results.append("✅ 所有验证通过！可以宣称任务完成。")
        else:
            results.append("⚠️  存在验证失败项。请修复问题后重新运行 verify_task，或明确报告未完成原因。")

        return all_passed, "\n".join(results)

    def _update_lessons(self, title: str, description: str, root_cause: str,
                        rule: str, regression_check: str = "") -> tuple[bool, str]:
        """
        更新 agent/lessons.md，记录新发现的错误和回归规则。
        """
        lessons_path = os.path.join(self.workdir, "agent", "lessons.md")

        # 确保目录存在
        os.makedirs(os.path.dirname(lessons_path), exist_ok=True)

        # 生成新条目
        from datetime import datetime
        today = datetime.now().strftime("%Y-%m-%d")

        new_entry = f"""
### {title}

- **出现日期**: {today}
- **问题描述**: {description}
- **根因**: {root_cause}
- **正确规则**: {rule}
- **回归检查**:
  ```bash
  {regression_check if regression_check else '# 暂无具体检查命令'}
  ```
"""

        # 如果文件不存在，创建基础结构
        if not os.path.exists(lessons_path):
            header = """# 项目教训与回归规则

本文档记录本项目已踩过的坑、已修复的错误和不可复发的规则。

**规则优先级高于临时推测**。当遇到类似问题时，先查阅本文档。

---

## 已记录规则

"""
            with open(lessons_path, "w", encoding="utf-8") as f:
                f.write(header + new_entry)
            return True, f"✅ 已创建 lessons.md 并添加新规则：{title}"

        # 读取现有内容
        try:
            with open(lessons_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return False, f"❌ 读取 lessons.md 失败：{e}"

        # 检查是否已存在相同标题的规则
        if f"### {title}" in content:
            return False, f"⚠️  规则 '{title}' 已存在，避免重复添加"

        # 找到"## 已记录规则"的位置，在其后插入
        marker = "## 已记录规则"
        if marker in content:
            # 找到 marker 所在行的末尾
            idx = content.find(marker) + len(marker)
            # 跳过可能的空白行
            while idx < len(content) and content[idx] in '\n\r':
                idx += 1
            # 插入新条目
            new_content = content[:idx] + "\n" + new_entry + content[idx:]
        else:
            # 没有 marker，追加到末尾
            new_content = content + "\n" + new_entry

        # 写回文件
        try:
            with open(lessons_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return True, f"✅ 已更新 lessons.md，添加规则：{title}"
        except Exception as e:
            return False, f"❌ 写入 lessons.md 失败：{e}"

    def _update_task_contract(self, goal: str, acceptance_items: list[str] = None,
                               not_in_scope: str = "", affected_files: list[str] = None) -> tuple[bool, str]:
        """
        更新任务契约文件 (.codex/task.json)。
        """
        import json

        task_dir = os.path.join(self.workdir, ".codex")
        task_file = os.path.join(task_dir, "task.json")

        # 确保目录存在
        os.makedirs(task_dir, exist_ok=True)

        # 读取现有契约（如果有）
        contract = {}
        if os.path.exists(task_file):
            try:
                with open(task_file, "r", encoding="utf-8") as f:
                    contract = json.load(f)
            except Exception:
                contract = {}

        # 更新契约
        contract["goal"] = goal
        if acceptance_items:
            contract["acceptance"] = acceptance_items
        if not_in_scope:
            contract["not_in_scope"] = not_in_scope
        if affected_files:
            contract["affected_files"] = affected_files

        # 更新状态
        contract["status"] = "implementing"
        if "changed_files" not in contract:
            contract["changed_files"] = []
        if "verification" not in contract:
            contract["verification"] = {"required": [], "passed": []}

        # 写回文件
        try:
            with open(task_file, "w", encoding="utf-8") as f:
                json.dump(contract, f, indent=2, ensure_ascii=False)
            return True, f"✅ 已更新任务契约：{goal[:50]}..."
        except Exception as e:
            return False, f"❌ 写入 task.json 失败：{e}"

    def _dispatch(self, name: str, args: dict) -> tuple[bool, str]:
        # ── verify_task ─────────────────────────────────
        if name == "verify_task":
            return self._verify_task(args.get("acceptance_items", []))

        # ── update_lessons ─────────────────────────────────
        if name == "update_lessons":
            return self._update_lessons(
                title=args.get("title", ""),
                description=args.get("description", ""),
                root_cause=args.get("root_cause", ""),
                rule=args.get("rule", ""),
                regression_check=args.get("regression_check", "")
            )

        # ── update_task_contract ─────────────────────────────────
        if name == "update_task_contract":
            return self._update_task_contract(
                goal=args.get("goal", ""),
                acceptance_items=args.get("acceptance_items", []),
                not_in_scope=args.get("not_in_scope", ""),
                affected_files=args.get("affected_files", [])
            )

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
                stdout = result.stdout.strip() if result.stdout else ""
                for line in stdout.split("\n"):
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
                # 使用 if-else 处理 stdout 为 None 的情况
                raw_lines = result.stdout.split("\n") if result.stdout else []

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
# ── SSH 远程工具 ─────────────────────────────────
        elif REMOTE_AVAILABLE and remote_manager:
            if name == "connect_remote":
                return remote_manager.connect(**args)
            elif name == "read_remote_file":
                conn = remote_manager.get_conn()
                if not conn:
                    return False, "未连接到远程主机，请先执行 connect_remote"
                try:
                    result = conn.run(f"cat '{args['path']}'", hide=True, timeout=30)
                    return True, result.stdout
                except Exception as e:
                    return False, f"读取失败：{str(e)}"
            elif name == "write_remote_file":
                conn = remote_manager.get_conn()
                if not conn:
                    return False, "未连接到远程主机"
                try:
                    import io
                    binary_content = args["content"].replace("\r\n", "\n").encode("utf-8")
                    file_obj = io.BytesIO(binary_content)
                    conn.put(file_obj, args["path"])
                    return True, f"文件写入成功：{args['path']} (实际写入 {len(binary_content)} 字节)"
                except Exception as e:
                    return False, f"写入失败：{str(e)}"
            elif name == "run_remote_command":
                conn = remote_manager.get_conn()
                if not conn:
                    return False, "未连接到远程主机"
                try:
                    timeout = int(args.get("timeout", 60))
                    result = conn.run(args["command"], hide=True, timeout=timeout)
                    output = result.stdout or result.stderr or "命令执行完成（无输出）"
                    return True, f"Exit: {result.exited}\n{output}"
                except Exception as e:
                    return False, f"命令执行失败：{str(e)}"
            elif name == "list_remote_dir":
                conn = remote_manager.get_conn()
                if not conn:
                    return False, "未连接到远程主机"
                try:
                    path = args.get("path", ".")
                    result = conn.run(f"ls -la '{path}'", hide=True, timeout=15)
                    return True, result.stdout
                except Exception as e:
                    return False, f"列目录失败：{str(e)}"
            elif name == "disconnect_remote":
                return remote_manager.disconnect()
            elif name == "remote_status":
                return True, remote_manager.get_status()

        else:
            return False, f"❌ 未知工具: {name}"