# file_editor.py
"""
文件编辑器：支持 unified diff 风格的搜索/替换/插入/删除。
所有操作都会返回一个 diff 字符串供预览。
"""

import difflib
import fnmatch
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional, Set


# ──────────────────────────────────────────────
# 基础工具
# ──────────────────────────────────────────────

# 用于检测是否需要自动启用正则模式的特殊字符
_REGEX_SPECIAL_CHARS = re.compile(r'[\\.^$*+?{}[\]|(){}]')

def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)


def _make_diff(old: str, new: str, path: str) -> str:
    """生成 unified diff 字符串。"""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    return "".join(diff)


# ──────────────────────────────────────────────
# 核心操作
# ──────────────────────────────────────────────

def read_file(path: str) -> str:
    """读取文件内容。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"文件不存在: {path}")
    return _read(path)


def write_file(path: str, content: str, dry_run: bool = False) -> str:
    """
    写入（新建或覆盖）文件。
    返回 diff 字符串。
    """
    old = _read(path) if os.path.exists(path) else ""
    diff = _make_diff(old, content, path)
    if not dry_run:
        _write(path, content)
    return diff or "(无变更)"


def search_replace(
    path: str,
    search: str,
    replace: str,
    count: int = 0,         # 0 = 替换全部
    regex: bool = False,
    dry_run: bool = False,
) -> str:
    """
    在文件中搜索并替换文本。
    返回 diff 字符串；若未找到则抛出 ValueError。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"文件不存在: {path}")

    old = _read(path)
    if regex:
        flags = re.MULTILINE
        new = re.sub(search, replace, old, count=count, flags=flags)
    else:
        max_replace = count if count else -1   # str.replace 用 -1 表示全部
        if search not in old:
            raise ValueError(f"在文件 {path} 中未找到目标字符串:\n{search!r}")
        new = old.replace(search, replace, max_replace if max_replace != -1 else (old.count(search)))

    diff = _make_diff(old, new, path)
    if not dry_run:
        _write(path, new)
    return diff or "(无变更)"


def insert_lines(
    path: str,
    after_line: int,        # 1-based；0 = 插入到文件开头
    text: str,
    dry_run: bool = False,
) -> str:
    """
    在指定行之后插入文本（自动补 \n）。
    返回 diff 字符串。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"文件不存在: {path}")

    old = _read(path)
    lines = old.splitlines(keepends=True)

    insert_text = text if text.endswith("\n") else text + "\n"
    insert_lines_list = insert_text.splitlines(keepends=True)

    idx = max(0, min(after_line, len(lines)))
    new_lines = lines[:idx] + insert_lines_list + lines[idx:]
    new = "".join(new_lines)

    diff = _make_diff(old, new, path)
    if not dry_run:
        _write(path, new)
    return diff or "(无变更)"


def delete_lines(
    path: str,
    start_line: int,        # 1-based inclusive
    end_line: int,          # 1-based inclusive
    dry_run: bool = False,
) -> str:
    """
    删除 start_line ~ end_line 范围内的行（含两端）。
    返回 diff 字符串。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"文件不存在: {path}")

    old = _read(path)
    lines = old.splitlines(keepends=True)
    n = len(lines)
    s = max(1, start_line) - 1
    e = min(n, end_line)
    new_lines = lines[:s] + lines[e:]
    new = "".join(new_lines)

    diff = _make_diff(old, new, path)
    if not dry_run:
        _write(path, new)
    return diff or "(无变更)"


def replace_lines(
    path: str,
    start_line: int,        # 1-based inclusive
    end_line: int,          # 1-based inclusive
    new_text: str,
    dry_run: bool = False,
) -> str:
    """
    用 new_text 替换 start_line~end_line 之间的行。
    返回 diff 字符串。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"文件不存在: {path}")

    old = _read(path)
    lines = old.splitlines(keepends=True)
    n = len(lines)
    s = max(1, start_line) - 1
    e = min(n, end_line)

    new_block = new_text if new_text.endswith("\n") else new_text + "\n"
    new_lines = lines[:s] + new_block.splitlines(keepends=True) + lines[e:]
    new = "".join(new_lines)

    diff = _make_diff(old, new, path)
    if not dry_run:
        _write(path, new)
    return diff or "(无变更)"


def apply_patch(
    patch_text: str,
    base_dir: str = ".",
    dry_run: bool = False,
) -> str:
    """
    应用 unified diff patch。
    返回操作结果摘要。
    """
    # 写入临时 patch 文件，调用 patch 命令（或纯 Python 实现）
    import subprocess

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".patch", delete=False, encoding="utf-8"
    ) as f:
        f.write(patch_text)
        patch_file = f.name

    try:
        cmd = ["patch", "-p1", "--input", patch_file, "--directory", base_dir]
        if dry_run:
            cmd.append("--dry-run")
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout + result.stderr
        if result.returncode != 0:
            raise RuntimeError(f"patch 失败:\n{output}")
        return output
    finally:
        os.unlink(patch_file)


def search_in_files(
    pattern: str,
    directory: str = ".",
    file_glob: str = "**/*",
    regex: bool = False,
    max_results: int = 200,
    case_sensitive: bool = True,
    context_lines: int = 0,
    exclude_glob: str = "",
) -> list[dict]:
    """
    在目录中搜索文本，返回匹配列表。
    
    Args:
        pattern: 搜索模式（字符串或正则）
        directory: 搜索目录
        file_glob: 文件 glob 模式，默认 **/*
        regex: 是否使用正则表达式。如果为 "auto" 或未指定，当检测到 pattern 包含正则特殊字符时自动启用
        max_results: 最大结果数
        case_sensitive: 是否区分大小写（默认区分）
        context_lines: 上下文行数（前后各显示多少行）
        exclude_glob: 排除的文件 glob 模式（如 *.log, **/test/**）
    
    Returns:
        每项：{file, line_no, line, context_before, context_after, rel_path}
        会自动读取 .gitignore 并排除忽略的文件和目录。
    """
    results = []
    base_path = Path(directory).resolve()
    patterns = _load_gitignore_patterns(base_path)
    
    # 自动检测是否需要正则模式：当 regex=False 但 pattern 包含正则特殊字符时自动启用
    if regex == "auto" or (isinstance(regex, bool) and not regex and _REGEX_SPECIAL_CHARS.search(pattern)):
        regex = True
    
    # 构建正则标志
    flags = re.MULTILINE
    if not case_sensitive:
        flags |= re.IGNORECASE
    
    # 预编译正则表达式（如果是正则模式）
    compiled_regex = None
    if regex:
        try:
            compiled_regex = re.compile(pattern, flags=flags)
        except re.error as e:
            raise ValueError(f"无效的正则表达式 '{pattern}': {e}")
    
    # 解析排除模式
    exclude_patterns = exclude_glob.split(",") if exclude_glob else []
    
    files_searched = 0
    files_matched = 0
    
    # 始终忽略的目录（与 list_directory 保持一致）
    ALWAYS_IGNORE_DIRS = {'.git', 'node_modules', '.zig-cache', '__pycache__', '.venv', '.vscode', 'zig-out'}
    
    for p in Path(directory).glob(file_glob):
        if not p.is_file():
            continue
        
        # 检查是否在始终忽略的目录中
        should_skip = False
        for part in p.relative_to(base_path).parts:
            if part in ALWAYS_IGNORE_DIRS:
                should_skip = True
                break
        if should_skip:
            continue
        
        # 检查排除模式
        rel_str = str(p.relative_to(base_path)).replace("\\", "/")
        excluded = False
        for exc in exclude_patterns:
            exc = exc.strip()
            if exc and (fnmatch.fnmatch(rel_str, exc) or fnmatch.fnmatch(p.name, exc)):
                excluded = True
                break
        if excluded:
            continue
        
        # 检查是否应该被 .gitignore 忽略
        if _should_ignore(p, base_path, patterns):
            continue
        
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        
        files_searched += 1
        lines = content.splitlines()
        file_matched = False
        
        for i, line in enumerate(lines, 1):
            matched = (
                compiled_regex.search(line) is not None
                if regex
                else (pattern in line if case_sensitive else pattern.lower() in line.lower())
            )
            if matched:
                file_matched = True
                # 获取上下文
                ctx_before = lines[max(0, i-1-context_lines):i-1]
                ctx_after = lines[i:min(len(lines), i+context_lines)]
                
                results.append({
                    "file": str(p),
                    "rel_path": rel_str,
                    "line_no": i,
                    "line": line,
                    "context_before": ctx_before,
                    "context_after": ctx_after,
                })
                if len(results) >= max_results:
                    break
        if file_matched:
            files_matched += 1
        if len(results) >= max_results:
            break
    
    # 添加统计信息到结果（通过第一个元素的特殊字段）
    if results:
        results[0]["_stats"] = {"files_searched": files_searched, "files_matched": files_matched}
    
    return results


def _load_gitignore_patterns(base_path: Path) -> List[str]:
    """加载 .gitignore 中的忽略模式。"""
    gitignore_path = base_path / ".gitignore"
    patterns = []
    if gitignore_path.exists():
        with open(gitignore_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
    return patterns


def _should_ignore(entry: Path, base_path: Path, patterns: List[str]) -> bool:
    """检查条目是否应该被忽略（根据 gitignore 模式）。"""
    rel_path = entry.relative_to(base_path)
    rel_str = str(rel_path).replace("\\", "/")
    name = entry.name
    
    # .gitignore 文件本身不应该被忽略（否则无法搜索其内容，但通常我们也不希望它出现在搜索结果中）
    # 这里选择排除 .gitignore 本身，避免搜索时匹配到 ignore 规则
    if name == ".gitignore":
        return True
    
    for pattern in patterns:
        # 处理目录模式（以 / 结尾）
        if pattern.endswith("/"):
            pattern = pattern.rstrip("/")
            if entry.is_dir() and (name == pattern or rel_str.endswith("/" + pattern)):
                return True
        # 处理路径模式（包含 / 但不以 / 结尾）
        elif "/" in pattern:
            # 处理 __pycache__/* 这种模式 - 忽略目录本身
            if pattern.endswith("/*"):
                dir_pattern = pattern[:-2]  # 去掉 /*
                if entry.is_dir() and (name == dir_pattern or rel_str.endswith("/" + dir_pattern)):
                    return True
            if fnmatch.fnmatch(rel_str, pattern):
                return True
        # 简单模式：匹配文件名或目录名
        else:
            if fnmatch.fnmatch(name, pattern):
                return True
    
    return False


def list_directory(path: str = ".", depth: int = 2, max_entries_per_dir: int = 15) -> str:
    """返回目录树字符串（优化版，减少 token 消耗）。
    
    Args:
        path: 目录路径
        depth: 递归深度，默认 2
        max_entries_per_dir: 每层最大显示条目数，超过则显示摘要
    """
    lines = []
    root = Path(path).resolve()
    patterns = _load_gitignore_patterns(root)
    
    # 始终忽略的目录
    ALWAYS_IGNORE = {'.git', 'node_modules'}
    
    def _walk(current: Path, prefix: str, d: int):
        if d < 0:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            return
        
        # 过滤忽略的目录和文件
        entries = [e for e in entries 
                   if not (e.is_dir() and e.name in ALWAYS_IGNORE)
                   and not _should_ignore(e, root, patterns)]
        
        total = len(entries)
        if total > max_entries_per_dir:
            # 优先显示目录，然后是文件
            dirs = [e for e in entries if e.is_dir()]
            files = [e for e in entries if e.is_file()]
            # 截断
            shown_dirs = dirs[:max_entries_per_dir // 2]
            shown_files = files[:max_entries_per_dir - len(shown_dirs)]
            shown = shown_dirs + shown_files
            hidden_count = total - len(shown)
        else:
            shown = entries
            hidden_count = 0
        
        for i, entry in enumerate(shown):
            connector = "└── " if i == len(shown) - 1 and hidden_count == 0 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir() and d > 0:
                extension = "    " if i == len(shown) - 1 and hidden_count == 0 else "│   "
                _walk(entry, prefix + extension, d - 1)
        
        if hidden_count > 0:
            lines.append(f"{prefix}    ... ({hidden_count} 个条目未显示)")

    root = Path(path)
    lines.append(f"{root.resolve()} (depth={depth})")
    _walk(root, "", depth)
    return "\n".join(lines)