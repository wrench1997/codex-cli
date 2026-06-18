#!/usr/bin/env python3
"""
pack_for_ai.py - 代码打包工具

功能：
1. 根据配置文件统计并合并源代码
2. 收集 git 提交历史和改动内容
3. 生成完整的报告文件，方便发送给其他 AI 求助

用法：
    python -m src.codex.pack_for_ai [config_file]
    
    config_file: 可选，默认为 upload_config.yaml
"""

import os
import sys
import yaml
import glob
import subprocess
from datetime import datetime


def count_lines_in_file(file_path):
    """统计单个文件的非空行数"""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            # 去掉空行和仅包含空白的行
            return sum(1 for line in lines if line.strip()), lines
    except Exception as e:
        print(f"无法读取文件 {file_path}: {e}")
        return 0, []


def resolve_paths(base_dir, patterns):
    """根据模式解析文件路径"""
    resolved_files = []
    for pattern in patterns:
        # 处理绝对路径和相对路径
        if os.path.isabs(pattern):
            path_pattern = pattern
        else:
            path_pattern = os.path.join(base_dir, pattern)
        
        # 使用 glob 匹配文件
        matched_files = glob.glob(path_pattern, recursive=True)
        # 只保留文件，排除目录
        matched_files = [f for f in matched_files if os.path.isfile(f)]
        resolved_files.extend(matched_files)
    
    return sorted(set(resolved_files))


def get_git_repo_root():
    """获取 git 仓库根目录"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_git_log(limit=20):
    """获取最近的 git 提交历史"""
    try:
        result = subprocess.run(
            ["git", "log", f"-{limit}", "--pretty=format:%H|%an|%ae|%ai|%s", "--no-merges"],
            capture_output=True,
            text=True,
            check=True
        )
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
        return commits
    except subprocess.CalledProcessError as e:
        print(f"获取 git log 失败：{e}")
        return []


def get_git_diff_stats(commit_hash):
    """获取某个提交的改动统计"""
    try:
        result = subprocess.run(
            ["git", "show", "--stat", "--no-patch", commit_hash],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def get_git_diff_content(commit_hash, max_lines=1000, cwd=None):
    """获取某个提交的详细改动内容（限制行数）"""
    try:
        # 使用 -p 或 --patch 来显示 diff，不使用 --no-stat（不是标准参数）
        result = subprocess.run(
            ["git", "show", "-p", commit_hash],
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd
        )
        lines = result.stdout.split("\n")
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines.append(f"\n... (内容被截断，共超过 {max_lines} 行)")
        return "\n".join(lines)
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️  获取 diff 失败：{e}")
        return ""


def get_git_status():
    """获取当前工作区状态"""
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def get_current_branch():
    """获取当前分支名"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def pack_for_ai(config_path, output_file=None, include_git=True, git_limit=10, cwd=None):
    """
    打包代码和 git 历史到单个文件
    
    Args:
        config_path: 配置文件路径
        output_file: 输出文件路径，默认从配置读取
        include_git: 是否包含 git 历史
        git_limit: 包含的提交数量限制
        cwd: 工作目录（用于 git 命令），默认为配置文件所在目录
    
    Returns:
        output_file: 生成的文件路径，失败返回 None
    """
    current_dir = os.path.dirname(os.path.abspath(config_path))
    
    # 如果没有指定 cwd，使用配置文件所在目录
    if cwd is None:
        cwd = current_dir
    
    # 加载配置
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    if not output_file:
        output_file = os.path.join(current_dir, config.get("output_file", "packed_for_ai.txt"))
    
    # 解析文件路径
    files_to_pack = resolve_paths(current_dir, config.get("include", []))
    
    if not files_to_pack:
        print("❌ 没有找到匹配的文件，请检查配置")
        return None
    
    # 开始生成报告
    print(f"📦 开始打包代码...")
    print(f"   配置文件：{config_path}")
    print(f"   输出文件：{output_file}")
    print(f"   文件数量：{len(files_to_pack)}")
    
    total_lines = 0
    file_stats = []
    
    with open(output_file, "w", encoding="utf-8") as out_f:
        # ============ 报告头部 ============
        out_f.write("=" * 80 + "\n")
        out_f.write("📋 代码打包报告 - Code Pack Report\n")
        out_f.write("=" * 80 + "\n")
        out_f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        out_f.write(f"配置文件：{config_path}\n")
        out_f.write(f"工作目录：{current_dir}\n")
        
        # ============ Git 信息 ============
        if include_git:
            repo_root = get_git_repo_root()
            if repo_root:
                out_f.write("\n" + "=" * 80 + "\n")
                out_f.write("🔗 Git 仓库信息\n")
                out_f.write("=" * 80 + "\n")
                out_f.write(f"仓库路径：{repo_root}\n")
                
                # 获取当前分支（使用 cwd）
                try:
                    result = subprocess.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        capture_output=True,
                        text=True,
                        check=True,
                        cwd=cwd
                    )
                    branch = result.stdout.strip()
                except:
                    branch = "unknown"
                out_f.write(f"当前分支：{branch}\n")
                
                # 当前工作区状态（使用 cwd）
                try:
                    result = subprocess.run(
                        ["git", "status", "--short"],
                        capture_output=True,
                        text=True,
                        check=True,
                        cwd=cwd
                    )
                    status = result.stdout.strip()
                except:
                    status = ""
                if status:
                    out_f.write("\n📝 工作区状态:\n")
                    out_f.write(status + "\n")
                
                # 提交历史（使用 cwd）
                try:
                    result = subprocess.run(
                        ["git", "log", f"-{git_limit}", "--pretty=format:%H|%an|%ae|%ai|%s", "--no-merges"],
                        capture_output=True,
                        text=True,
                        check=True,
                        cwd=cwd
                    )
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
                except Exception as e:
                    print(f"  ⚠️  获取 git log 失败：{e}")
                    commits = []
                if commits:
                    out_f.write(f"\n📜 最近 {len(commits)} 条提交历史:\n")
                    out_f.write("-" * 80 + "\n")
                    
                    for i, commit in enumerate(commits, 1):
                        out_f.write(f"\n[{i}] {commit['hash'][:8]}\n")
                        out_f.write(f"    作者：{commit['author']} <{commit['email']}>\n")
                        out_f.write(f"    时间：{commit['date']}\n")
                        out_f.write(f"    消息：{commit['message']}\n")
                        
                        # 改动统计
                        stats = get_git_diff_stats(commit['hash'])
                        if stats:
                            # 只取统计部分
                            stat_lines = stats.split("\n")
                            if len(stat_lines) > 2:
                                out_f.write(f"    改动:\n")
                                for line in stat_lines[-5:]:  # 最后几行是统计
                                    if line.strip():
                                        out_f.write(f"      {line}\n")
                
                # 详细改动内容（可选，放在最后）
                if commits and git_limit > 0:
                    out_f.write("\n" + "=" * 80 + "\n")
                    out_f.write("📝 Git 详细改动内容\n")
                    out_f.write("=" * 80 + "\n")
                    
                    for commit in commits:
                        out_f.write(f"\n{'='*60}\n")
                        out_f.write(f"Commit: {commit['hash'][:8]} - {commit['message']}\n")
                        out_f.write(f"{'='*60}\n")
                        diff_content = get_git_diff_content(commit['hash'], cwd=current_dir)
                        out_f.write(diff_content + "\n")
            else:
                out_f.write("\n⚠️  未检测到 Git 仓库\n")
        
        # ============ 代码文件统计 ============
        out_f.write("\n" + "=" * 80 + "\n")
        out_f.write("📊 代码文件统计\n")
        out_f.write("=" * 80 + "\n")
        
        # ============ 代码文件内容 ============
        out_f.write("\n" + "=" * 80 + "\n")
        out_f.write("📁 源代码内容\n")
        out_f.write("=" * 80 + "\n")
        
        for file_path in files_to_pack:
            rel_path = os.path.relpath(file_path, current_dir)
            lines_count, content = count_lines_in_file(file_path)
            total_lines += lines_count
            file_stats.append((rel_path, lines_count))
            
            out_f.write(f"\n\n{'='*80}\n")
            out_f.write(f"📄 FILE: {rel_path} ({lines_count} 行)\n")
            out_f.write(f"{'='*80}\n\n")
            out_f.writelines(content)
        
        # ============ 报告尾部 ============
        out_f.write("\n\n" + "=" * 80 + "\n")
        out_f.write("📈 统计摘要\n")
        out_f.write("=" * 80 + "\n")
        out_f.write(f"总文件数：{len(file_stats)}\n")
        out_f.write(f"总代码行数：{total_lines}\n")
        out_f.write("\n文件列表:\n")
        for path, lines in file_stats:
            out_f.write(f"  {path}: {lines} 行\n")
        out_f.write("\n" + "=" * 80 + "\n")
        out_f.write("✅ 打包完成！\n")
        out_f.write("=" * 80 + "\n")
    
    # 打印摘要
    print(f"\n{'='*50}")
    print(f"✅ 打包完成！")
    print(f"   总文件数：{len(file_stats)}")
    print(f"   总代码行数：{total_lines}")
    print(f"   输出文件：{output_file}")
    
    if include_git:
        commits = get_git_log(git_limit)
        print(f"   Git 提交：{len(commits)} 条")
    
    print(f"{'='*50}")
    
    return output_file


def export_single_commit(commit_hash, output_file=None):
    """
    单独导出某个 commit 的详细改动
    
    Args:
        commit_hash: 提交 hash（可以是短 hash）
        output_file: 输出文件路径，默认是 commit_{hash}.txt
    
    Returns:
        output_file: 生成的文件路径，失败返回 None
    """
    try:
        # 获取提交信息
        result = subprocess.run(
            ["git", "show", "--pretty=full", "-p", commit_hash],
            capture_output=True,
            text=True,
            check=True
        )
        
        if not output_file:
            output_file = f"commit_{commit_hash[:8]}.txt"
        
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"📝 Commit: {commit_hash}\n")
            f.write("=" * 80 + "\n\n")
            f.write(result.stdout)
        
        print(f"✅ 已导出 commit {commit_hash[:8]} 到：{output_file}")
        return output_file
    except subprocess.CalledProcessError as e:
        print(f"❌ 获取 commit 失败：{e}")
        return None


def main():
    # 获取当前脚本所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 项目根目录（src/codex 的上级上级）
    project_root = os.path.dirname(os.path.dirname(current_dir))
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        if sys.argv[1] == "--commit" and len(sys.argv) > 2:
            # 导出单个 commit
            export_single_commit(sys.argv[2])
            sys.exit(0)
        elif sys.argv[1] == "--help":
            print(__doc__)
            sys.exit(0)
        
        config_path = sys.argv[1]
    else:
        # 默认在项目根目录查找配置文件
        config_path = os.path.join(project_root, "upload_config.yaml")
    
    # 检查配置文件是否存在
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在：{config_path}")
        print("\n创建示例配置文件...")
        
        # 创建示例配置
        example_config = {
            "output_file": "packed_for_ai.txt",
            "include": [
                "src/**/*.py",
                "src/**/*.zig",
                "*.md"
            ],
            "git_settings": {
                "include_git": True,
                "commit_limit": 10
            }
        }
        
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(example_config, f, default_flow_style=False, allow_unicode=True)
        
        print(f"✅ 已创建示例配置文件：{config_path}")
        print("请编辑配置文件后重新运行脚本")
        sys.exit(0)
    
    # 加载配置获取 git 设置
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    git_settings = config.get("git_settings", {})
    include_git = git_settings.get("include_git", True)
    git_limit = git_settings.get("commit_limit", 10)
    
    # 执行打包
    pack_for_ai(
        config_path=config_path,
        include_git=include_git,
        git_limit=git_limit
    )


if __name__ == "__main__":
    main()