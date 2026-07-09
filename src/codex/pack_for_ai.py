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

# 在 Windows 上设置标准输出为 UTF-8 编码，避免 emoji 字符编码错误
# 使用 try-except 处理某些环境（如 StdoutProxy）不支持 reconfigure 的情况
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # 如果 stdout 没有 reconfigure 方法（如 StdoutProxy），则忽略
        pass


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
            encoding='utf-8',
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
            encoding='utf-8',
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
            encoding='utf-8',
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def get_git_diff_content(commit_hash, max_lines=1000, cwd=None):
    """获取某个提交的详细改动内容（限制行数）"""
    try:
        # 使用 -p 或 --patch 来显示 diff，不使用 --no-stat（不是标准参数）
        # 显式指定 encoding='utf-8' 避免 Windows 上 GBK 编码问题
        result = subprocess.run(
            ["git", "show", "-p", commit_hash],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            cwd=cwd
        )
        lines = result.stdout.split("\n")
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines.append(f"\n... (内容被截断，共超过 {max_lines} 行)")
        return "\n".join(lines)
    except Exception as e:
        print(f"  ⚠️  获取 diff 失败：{e}")
        return ""


def get_git_status():
    """获取当前工作区状态"""
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            encoding='utf-8',
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
            encoding='utf-8',
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def pack_for_ai(config_path, output_file=None, include_git=True, git_limit=1, cwd=None):
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
                        encoding='utf-8',
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
                        encoding='utf-8',
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
                        encoding='utf-8',
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


def analyze_codebase_for_help(cwd):
    """
    分析当前代码库，识别可能需要求助的代码
    
    优先级：
    1. 最近修改的文件（git diff）
    2. 未提交的改动（git status）
    3. 最近提交涉及的文件
    
    Returns:
        dict: {
            'modified_files': list,  # 最近修改的文件
            'uncommitted_files': list,  # 未提交的文件
            'recent_commits': list,  # 最近提交信息
            'suggested_focus': list  # 建议重点关注的文件
        }
    """
    result = {
        'modified_files': [],
        'uncommitted_files': [],
        'recent_commits': [],
        'suggested_focus': []
    }
    
    # 1. 获取未提交的改动
    try:
        status_result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            cwd=cwd
        )
        for line in status_result.stdout.strip().split("\n"):
            if line:
                # 格式：" M file.py" 或 "?? file.py"
                parts = line.split(None, 1)
                if len(parts) == 2:
                    file_path = parts[1].strip()
                    result['uncommitted_files'].append(file_path)
    except:
        pass
    
    # 2. 获取最近修改的文件（通过 git diff HEAD）
    try:
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            cwd=cwd
        )
        for line in diff_result.stdout.strip().split("\n"):
            if line and line not in result['uncommitted_files']:
                result['modified_files'].append(line)
    except:
        pass
    
    # 3. 获取最近提交涉及的文件
    try:
        log_result = subprocess.run(
            ["git", "log", "-5", "--name-only", "--pretty=format:", "--no-merges"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            cwd=cwd
        )
        files_from_commits = set()
        for line in log_result.stdout.strip().split("\n"):
            if line:
                files_from_commits.add(line)
        # 只保留 .py, .yaml, .yml, .toml, .md 等源代码文件
        for f in files_from_commits:
            if any(f.endswith(ext) for ext in ['.py', '.yaml', '.yml', '.toml', '.md', '.jinja', '.bat', '.ps1']):
                if f not in result['modified_files'] and f not in result['uncommitted_files']:
                    result['recent_commits'].append(f)
    except:
        pass
    
    # 4. 生成建议重点关注的文件列表
    # 优先级：未提交 > 最近修改 > 最近提交
    result['suggested_focus'] = (
        result['uncommitted_files'] + 
        result['modified_files'] + 
        result['recent_commits']
    )
    
    return result


def generate_smart_config(analysis_result, cwd, config_path):
    """
    根据分析结果生成智能配置文件
    
    Args:
        analysis_result: analyze_codebase_for_help 的返回结果
        cwd: 工作目录
        config_path: 配置文件路径
    """
    print("\n🔍 代码库分析结果:")
    print("-" * 60)
    
    if analysis_result['uncommitted_files']:
        print(f"📝 未提交的改动 ({len(analysis_result['uncommitted_files'])} 个文件):")
        for f in analysis_result['uncommitted_files'][:10]:  # 最多显示 10 个
            print(f"   - {f}")
        if len(analysis_result['uncommitted_files']) > 10:
            print(f"   ... 还有 {len(analysis_result['uncommitted_files']) - 10} 个文件")
    
    if analysis_result['modified_files']:
        print(f"\n🔄 最近修改的文件 ({len(analysis_result['modified_files'])} 个文件):")
        for f in analysis_result['modified_files'][:10]:
            print(f"   - {f}")
    
    if analysis_result['recent_commits']:
        print(f"\n📜 最近提交涉及的文件 ({len(analysis_result['recent_commits'])} 个文件):")
        for f in analysis_result['recent_commits'][:10]:
            print(f"   - {f}")
    
    print("-" * 60)
    
    # 生成配置
    config = {
        "output_file": "selected_code.txt",
        "include": [],
        "git_settings": {
            "include_git": True,
            "commit_limit": 5
        }
    }
    
    # 1. 优先添加未提交和最近修改的文件（具体文件路径）
    focus_files = analysis_result['suggested_focus'][:20]  # 最多 20 个重点文件
    for f in focus_files:
        # 确保是相对路径
        if not os.path.isabs(f):
            config['include'].append(f)
        else:
            config['include'].append(os.path.relpath(f, cwd))
    
    # 2. 添加常用的源代码模式（作为补充）
    default_patterns = [
        "**/*.py",
        "**/*.jinja",
        "**/*.yaml",
        "**/*.yml",
        "**/*.toml",
        "**/*.md",
        "**/*.bat",
        "**/*.ps1"
    ]
    
    # 3. 询问用户是否要包含所有源代码文件
    print("\n💡 建议配置:")
    print(f"   - 重点文件：{len(focus_files)} 个")
    print(f"   - 是否包含所有源代码文件？(y/n)")
    
    # 非交互模式下默认添加
    try:
        # 检查是否在非交互模式
        if not sys.stdin.isatty():
            user_input = "y"
        else:
            user_input = input("   输入 y 包含所有源代码，n 只包含重点文件：").strip().lower()
    except:
        user_input = "y"
    
    if user_input == 'y':
        config['include'].extend(default_patterns)
        print("   ✅ 已添加所有源代码文件模式")
    else:
        print("   ✅ 只包含重点文件")
    
    # 写入配置文件
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    
    print(f"\n✅ 已更新配置文件：{config_path}")
    print(f"   包含 {len(config['include'])} 个文件/模式")


def main():
    # 获取当前脚本所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 项目根目录（src/codex 的上级上级）
    project_root = os.path.dirname(os.path.dirname(current_dir))
    
    # 检查命令行参数
    auto_analyze = True  # 默认启用自动分析
    config_path = None
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--commit" and len(sys.argv) > 2:
            # 导出单个 commit
            export_single_commit(sys.argv[2])
            sys.exit(0)
        elif sys.argv[1] == "--help":
            print(__doc__)
            print("\n新增选项:")
            print("  --no-analyze  跳过自动分析，使用现有配置")
            sys.exit(0)
        elif sys.argv[1] == "--no-analyze":
            auto_analyze = False
            config_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(project_root, "upload_config.yaml")
        else:
            config_path = sys.argv[1]
    
    if config_path is None:
        config_path = os.path.join(project_root, "upload_config.yaml")
    
    # 检查配置文件是否存在
    config_exists = os.path.exists(config_path)
    
    if not config_exists:
        print(f"ℹ️  配置文件不存在：{config_path}")
        print("\n将自动创建配置文件...")
    elif auto_analyze:
        # 询问是否重新分析
        try:
            if not sys.stdin.isatty():
                user_input = "y"
            else:
                user_input = input("\n💡 检测到现有配置文件，是否重新分析代码库以优化配置？(y/n): ").strip().lower()
        except:
            user_input = "y"
        
        if user_input != 'y':
            auto_analyze = False
    
    # 自动分析代码库并生成智能配置
    if auto_analyze or not config_exists:
        print("\n🔍 正在分析代码库，识别需要求助的代码...")
        analysis_result = analyze_codebase_for_help(project_root)
        
        if analysis_result['suggested_focus']:
            generate_smart_config(analysis_result, project_root, config_path)
        else:
            if not config_exists:
                # 没有分析结果且配置不存在，创建默认配置
                print("\n⚠️  未检测到 Git 仓库或改动，创建默认配置...")
                example_config = {
                    "output_file": "selected_code.txt",
                    "include": [
                        "**/*.py",
                        "**/*.jinja",
                        "**/*.yaml",
                        "**/*.yml",
                        "**/*.toml",
                        "**/*.md",
                        "**/*.bat",
                        "**/*.ps1"
                    ],
                    "git_settings": {
                        "include_git": True,
                        "commit_limit": 5
                    }
                }
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(example_config, f, default_flow_style=False, allow_unicode=True)
                print(f"✅ 已创建默认配置文件：{config_path}")
    
    # 加载配置获取 git 设置
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    git_settings = config.get("git_settings", {})
    include_git = git_settings.get("include_git", True)
    git_limit = git_settings.get("commit_limit", 5)
    
    # 执行打包
    pack_for_ai(
        config_path=config_path,
        include_git=include_git,
        git_limit=git_limit
    )


if __name__ == "__main__":
    main()