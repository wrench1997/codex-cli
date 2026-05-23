# file_editor.py
"""
文件编辑器：支持 unified diff 风格的搜索/替换/插入/删除。
所有操作都会返回一个 diff 字符串供预览。
"""

import difflib
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────
# 基础工具
# ──────────────────────────────────────────────

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
) -> list[dict]:
    """
    在目录中搜索文本，返回匹配列表。
    每项: {file, line_no, line}
    """
    results = []
    flags = re.MULTILINE

    for p in Path(directory).glob(file_glob):
        if not p.is_file():
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for i, line in enumerate(content.splitlines(), 1):
            matched = (
                bool(re.search(pattern, line, flags=flags))
                if regex
                else pattern in line
            )
            if matched:
                results.append({"file": str(p), "line_no": i, "line": line})
                if len(results) >= max_results:
                    return results
    return results


def list_directory(path: str = ".", depth: int = 2) -> str:
    """返回目录树字符串。"""
    lines = []

    def _walk(current: Path, prefix: str, d: int):
        if d < 0:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            return
        for i, entry in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir() and d > 0:
                extension = "    " if i == len(entries) - 1 else "│   "
                _walk(entry, prefix + extension, d - 1)

    root = Path(path)
    lines.append(str(root.resolve()))
    _walk(root, "", depth)
    return "\n".join(lines)