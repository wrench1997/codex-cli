#!/usr/bin/env python3
"""
自动初始化 agent 目录 - 一键创建工程执行协议模板

用法:
    python init_agent.py                      # 当前目录
    python init_agent.py /path/to/project     # 指定项目目录
"""

import os
import sys
from pathlib import Path

# 获取脚本所在目录（模板文件位置）
SCRIPT_DIR = Path(__file__).parent
AGENT_TEMPLATE_DIR = SCRIPT_DIR / "agent"

# 模板文件内容（如果独立运行，直接嵌入）
SKILLS_MD = """# 工程执行协议

## 最高目标

完成用户需求的全部可验证验收项。**最小改动只是实现手段，不得以"少改代码"为理由遗漏功能、异常处理、测试或兼容性。**

> **Prefer the smallest change that fully satisfies every acceptance criterion.**
> **Never reduce scope, omit edge cases, or skip verification merely to keep changes small.**

## 每次开发任务必须遵循的阶段

### 1. 建立任务契约

在修改文件前，先明确：

* **用户目标**：用户最终想实现什么
* **必须实现的功能列表**：具体验收项
* **明确不做的内容**：范围边界
* **受影响模块和文件**：相关代码位置
* **验收方式**：构建、测试、运行、截图、接口返回或其他可观察结果

**未明确验收方式时**，优先从项目文档、现有测试、package 配置、构建脚本中推断；不能推断时说明风险，**不得假装已验证**。

### 2. 先理解，再修改

修改前必须：

* 阅读相关实现、调用方、类型定义和已有测试
* 搜索同类实现和历史规则
* **不得凭文件名或局部代码猜测接口**
* 修改公共接口时，必须检查全部引用点

### 3. 小步实现

* 优先做**可运行的完整闭环**，不写伪实现、空函数、假数据或仅展示 UI
* **不得为了让编译通过而吞异常、静默 fallback、删除校验或绕过类型系统**
* 每次修改保持局部且可回滚
* 若发现任务范围变化，**更新任务契约后继续**

### 4. 强制验证

只要修改了代码，结束前必须执行与项目匹配的：

1. **格式化检查**
2. **编译或类型检查**
3. **单元测试或相关测试**
4. **必要的运行时 smoke test**
5. **git diff --check**

**没有实际成功执行的命令，不得声称"已修复""可用""完成"。**

### 5. 错误修复纪律

遇到报错时：

* 先读取完整报错、相关源代码和调用链
* 修复后必须**重新运行导致该错误的原始命令**
* 同一类错误第二次出现时，必须把根因、正确规则和回归检查写入 `agent/lessons.md`
* **已记录的 lessons 优先级高于临时推测**

## 完成条件

只有同时满足以下条件，才可以说任务完成：

* ✅ 所有验收项都有结果
* ✅ 所有必要构建/测试命令成功
* ✅ 没有未解释的失败、跳过项或 TODO
* ✅ 最终回复明确列出：修改文件、验证命令及结果、剩余风险

**若验证失败或无法执行，必须说"未完成验证"，并说明失败原因；不得用乐观语言掩盖。**

## 当前项目特定规则

### 项目类型
（根据实际项目修改）

* **语言**: 
* **格式化**: 
* **测试命令**: 
* **构建命令**: 

### 禁止行为

* 禁止为了通过编译删除功能或吞掉错误
* 禁止新增 TODO、pass、空实现、mock 代替真实逻辑
* 禁止修改公共类型后不检查所有引用
* 禁止修改脚本语法后不运行对应 parser/compiler 测试
"""

QUALITY_YAML = """# 项目质量门禁配置
# 用于 verify_task 工具自动执行验证命令

commands:
  # Git 差异检查（必须）
  diff_check:
    command: "git diff --check"
    required: true
    description: "检查是否有 whitespace 错误或合并冲突标记"

  # 代码检查（根据项目类型修改）
  lint:
    command: "python -m py_compile .  # 替换为项目的 lint 命令"
    required: true
    description: "代码语法检查"

  # 构建检查（可选）
  build:
    command: "echo '请替换为项目的构建命令'"
    required: false
    description: "构建/编译检查"

  # 单元测试（可选）
  test:
    command: "echo '请替换为项目的测试命令'"
    required: false
    description: "运行单元测试"

rules:
  - "禁止为了通过编译删除功能或吞掉错误"
  - "禁止新增 TODO、pass、空实现、mock 代替真实逻辑"
  - "修改公共类型后必须检查所有引用"
  - "修改脚本语法后必须运行对应 parser/compiler 测试"
  - "最小改动是手段，不是目标 —— 不得以少改为理由遗漏验收项"

completion:
  require_all_commands: false   # 不强制所有命令都成功（有些项目可能没有测试）
  require_clean_diff_check: true
  require_acceptance_checklist: true
  require_verification_before_done: true  # 关键：修改后必须验证才能说完成
"""

LESSONS_MD = """# 项目教训与回归规则

本文档记录本项目已踩过的坑、已修复的错误和不可复发的规则。

**规则优先级高于临时推测**。当遇到类似问题时，先查阅本文档。

---

## 如何添加新规则

当你发现以下情况时，请添加新条目：

1. **同一类错误出现第二次**
2. **修复后可能回归的问题**
3. **项目特定的重要约定**

每个条目应包含：

- **问题描述**：什么错误
- **根因分析**：为什么会出现
- **正确规则**：应该怎么做
- **回归检查**：如何验证不再犯（命令/测试）

---

## 模板

```markdown
### [问题标题]

- **出现日期**: YYYY-MM-DD
- **问题描述**: ...
- **根因**: ...
- **正确规则**: ...
- **回归检查**: 
  ```bash
  # 执行此命令确保问题不再出现
  ```
```

---

## 已记录规则

（暂无，待添加）
"""


def init_agent_directory(target_dir: Path):
    """在目标目录创建 agent/ 文件夹和模板文件"""
    
    agent_dir = target_dir / "agent"
    
    # 检查是否已存在
    if agent_dir.exists():
        print(f"⚠️  目录已存在：{agent_dir}")
        response = input("是否覆盖现有文件？(y/N): ").strip().lower()
        if response != "y":
            print("❌ 已取消")
            return False
    
    # 创建目录
    agent_dir.mkdir(exist_ok=True)
    
    # 写入文件
    files_created = []
    
    skills_path = agent_dir / "skills.md"
    with open(skills_path, "w", encoding="utf-8") as f:
        f.write(SKILLS_MD)
    files_created.append(str(skills_path))
    print(f"✅ 创建：{skills_path}")
    
    quality_path = agent_dir / "quality.yaml"
    with open(quality_path, "w", encoding="utf-8") as f:
        f.write(QUALITY_YAML)
    files_created.append(str(quality_path))
    print(f"✅ 创建：{quality_path}")
    
    lessons_path = agent_dir / "lessons.md"
    with open(lessons_path, "w", encoding="utf-8") as f:
        f.write(LESSONS_MD)
    files_created.append(str(lessons_path))
    print(f"✅ 创建：{lessons_path}")
    
    print()
    print("=" * 60)
    print("🎉 agent 目录初始化完成！")
    print("=" * 60)
    print()
    print("📋 下一步：")
    print(f"  1. 编辑 {quality_path}")
    print("     修改 commands 中的命令为你的项目实际使用的构建/测试命令")
    print()
    print("  2. 编辑 skills.md")
    print("     在'当前项目特定规则'部分填写项目类型和特定规则")
    print()
    print("  3. 开始使用 Codex CLI")
    print("     AI 会自动读取 agent/ 目录的规则并强制执行")
    print()
    print("💡 提示：lessons.md 初始为空模板，遇到重复错误时再添加规则")
    print()
    
    return True


def main():
    # 确定目标目录
    if len(sys.argv) > 1:
        target_dir = Path(sys.argv[1]).resolve()
    else:
        target_dir = Path.cwd()
    
    if not target_dir.is_dir():
        print(f"❌ 目录不存在：{target_dir}")
        sys.exit(1)
    
    print(f"🔧 正在初始化 agent 目录...")
    print(f"📁 目标位置：{target_dir}")
    print()
    
    success = init_agent_directory(target_dir)
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()