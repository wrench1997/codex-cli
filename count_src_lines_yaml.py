import os
import yaml
import sys

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

def count_code_lines(file_paths, output_file=None):
    """统计指定文件列表下文件的行数"""
    total_lines = 0
    file_count = 0
    
    out_f = None
    if output_file:
        out_f = open(output_file, "w", encoding="utf-8")

    # 遍历传入的所有文件路径
    for file_path in file_paths:
        if not os.path.exists(file_path):
            print(f"警告: 文件不存在，已跳过: {file_path}")
            continue
            
        lines_count, content = count_lines_in_file(file_path)
        total_lines += lines_count
        file_count += 1
        print(f"{file_path} : {lines_count}")
        
        if out_f:
            out_f.write(f"\n\n// ================ FILE: {file_path} ================\n\n")
            out_f.writelines(content)
    
    if out_f:
        out_f.close()
        print(f"\n所有源码已合并到: {output_file}")
        
    return total_lines, file_count

def load_config(config_path):
    """加载YAML配置文件"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"无法加载配置文件 {config_path}: {e}")
        return None

def resolve_paths(base_dir, patterns):
    """根据模式解析文件路径"""
    import glob
    
    resolved_files = []
    for pattern in patterns:
        # 处理绝对路径和相对路径
        if os.path.isabs(pattern):
            path_pattern = pattern
        else:
            path_pattern = os.path.join(base_dir, pattern)
        
        # 使用glob匹配文件
        matched_files = glob.glob(path_pattern, recursive=True)
        resolved_files.extend(matched_files)
    
    return resolved_files

if __name__ == "__main__":
    # 获取当前脚本所在目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
    else:
        config_path = os.path.join(current_dir, "upload_config.yaml")
        
    # 检查配置文件是否存在
    if not os.path.exists(config_path):
        print(f"配置文件不存在: {config_path}")
        print("创建示例配置文件...")
        
        # 创建示例配置
        example_config = {
            "output_file": "selected_code.txt",
            "include": [
                "src/ecs/ecs.zig",
                "src/editor/math3d.zig",
                "src/gui/imgui_editor.zig",
                "shaders/*.{frag,vert}",
                "src/core/resource_manager.zig",
                "src/rhi/vertex.zig",
                "src/ecs/systems/common.zig",
                "src/core/c.zig",
                "src/core/input.zig",
                "src/ecs/systems/input_system.zig"
            ]
        }
        
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(example_config, f, default_flow_style=False)
            
        print(f"已创建示例配置文件: {config_path}")
        print("请编辑配置文件后重新运行脚本")
        sys.exit(0)
    
    # 加载配置
    config = load_config(config_path)
    if not config:
        print("无法加载配置，退出")
        sys.exit(1)
    
    # 解析文件路径
    files_to_scan = resolve_paths(current_dir, config.get("include", []))
    
    if not files_to_scan:
        print("没有找到匹配的文件，请检查配置")
        sys.exit(1)
    
    # 指定合并后的输出文件路径
    output_file = os.path.join(current_dir, config.get("output_file", "all_source_code.txt"))
    
    # 统计代码行数并合并文件
    total, count = count_code_lines(files_to_scan, output_file)
    
    print("\n" + "="*50)
    print(f"扫描完成！")
    print(f"总文件数: {count}")
    print(f"总代码行数: {total}")
    print("="*50)