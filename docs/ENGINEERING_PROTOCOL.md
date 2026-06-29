# 工程执行协议 - 防止 AI 偷工减料

本文档说明 Codex CLI 如何通过**四层防护机制**确保 AI 不会"未验证就宣称完成"。

## 问题背景

传统 AI 编程助手常见问题：

1. ❌ 写一个看似合理的半成品，然后说"完成了"
2. ❌ 没有运行任何测试就声称"已修复"
3. ❌ 为了"最小改动"而遗漏边界情况
4. ❌ 同样的错误重复出现，没有形成记忆

## 四层防护机制

### 第一层：项目宪法（agent/skills.md）

**位置**: 每个项目根目录的 `agent/skills.md`

**作用**: 定义工程纪律和开发流程，不是聊天记忆，而是**必须遵守的协议**。

**核心内容**:

```markdown
# 工程执行协议

## 最高目标
完成用户需求的全部可验证验收项。**最小改动只是实现手段，不得以"少改代码"为理由遗漏功能、异常处理、测试或兼容性。**

## 必须遵循的阶段
1. 建立任务契约（明确验收方式）
2. 先理解，再修改
3. 小步实现（完整闭环，不写伪实现）
4. 强制验证（format/build/test/diff-check）
5. 错误修复纪律（同一错误第二次必须写入 lessons.md）

## 完成条件
- ✅ 所有验收项都有结果
- ✅ 所有必要构建/测试命令成功
- ✅ 没有未解释的失败、跳过项或 TODO
- ✅ 最终回复明确列出：修改文件、验证命令及结果、剩余风险
```

### 第二层：质量门禁配置（agent/quality.yaml）

**位置**: `agent/quality.yaml`

**作用**: 定义项目必须执行的验证命令，供 `verify_task` 工具自动执行。

**示例**:

```yaml
commands:
  diff_check:
    command: "git diff --check"
    required: true
  lint:
    command: "python -m py_compile src/codex/*.py"
    required: true
  build:
    command: "python -c 'import src.codex; import gateway'"
    required: false
  test:
    command: "python -m pytest tests/ -v"
    required: false

rules:
  - "禁止为了通过编译删除功能或吞掉错误"
  - "禁止新增 TODO、pass、空实现"
  - "最小改动是手段，不是目标"

completion:
  require_all_commands: false
  require_clean_diff_check: true
  require_verification_before_done: true  # 关键！
```

### 第三层：任务状态跟踪（代码级门禁）

**实现**: `src/codex/cli.py` 中的 `TaskState` 类

**核心逻辑**:

```python
class TaskState:
    dirty = False                    # 是否改过代码
    acceptance_items: list[str] = []  # 验收项列表
    changed_files: set[str] = set()   # 已修改的文件
    verification_passed = False       # 验证是否通过
    
    def can_finish(self) -> bool:
        if not self.dirty:
            return True  # 没改过代码，可以直接结束
        return self.verification_passed  # 改过代码必须验证通过
```

**关键门禁**: 当模型不再调用工具时：

```python
if not tool_calls:
    if self.task_state.dirty and not self.task_state.can_finish():
        # 强制插入系统消息，要求验证
        self.add_user("【系统门禁】⚠️ 代码已修改但未验证，必须调用 verify_task")
        continue  # 不让结束
```

### 第四层：verify_task 工具

**新增工具**: `verify_task`

**作用**: 自动执行 `agent/quality.yaml` 中定义的所有验证命令，返回详细报告。

**用法**:

```
用户：修复这个 bug
AI: （修改代码）
AI: （尝试结束）
系统：【门禁】代码已修改但未验证，请调用 verify_task
AI: <tool_call><function=verify_task/></tool_call>
系统：═══ 任务验证报告 ═══
      🔧 执行：diff_check → ✅ 通过
      🔧 执行：lint → ✅ 通过
      🔧 执行：build → ❌ 失败
      ⚠️  存在验证失败项。请修复后重新运行 verify_task
AI: （修复构建问题）
AI: <tool_call><function=verify_task/></tool_call>
系统：✅ 所有验证通过！可以宣称任务完成。
AI: 任务完成。已修复 XXX 问题，验证命令全部通过。
```

## 教训文档（agent/lessons.md）

**位置**: `agent/lessons.md`

**作用**: 记录已踩过的坑和不可复发的规则。

**何时添加**:

- 同一类错误出现第二次
- 修复后可能回归的问题
- 项目特定的重要约定

**模板**:

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

## 使用建议

### 温度设置

```bash
# 代码任务（修复 bug、重构、跟随既有架构）
CODEX_TEMPERATURE=0.15~0.25

# 讨论/设计/创意任务
CODEX_TEMPERATURE=0.6~0.8
```

### 新项目快速启动

1. 复制 `agent/` 模板文件夹到新项目
2. 根据项目类型修改 `agent/quality.yaml` 中的命令
3. 开始使用 Codex CLI

### 现有项目集成

只需在项目根目录创建 `agent/` 文件夹，放入三个文件：

```
your-project/
  agent/
    skills.md      # 工程执行协议
    quality.yaml   # 验证命令配置
    lessons.md     # 教训与回归规则
```

Codex CLI 会自动加载这些文件并强制执行。

## 效果对比

### 使用前（传统 AI）

```
用户：修复这个 bug
AI: 好的，已修复。（实际没跑测试）
用户：（运行测试）还是错的！
AI: 抱歉，我再看看...（来回多次）
```

### 使用后（带门禁）

```
用户：修复这个 bug
AI: （修改代码）
系统：【门禁】请调用 verify_task
AI: <tool_call><function=verify_task/></tool_call>
系统：❌ 测试失败
AI: （修复测试问题）
AI: <tool_call><function=verify_task/></tool_call>
系统：✅ 所有验证通过
AI: 任务完成。已修复 XXX，运行测试通过。
```

## 核心原则

> **提示词负责说明目标；程序负责阻止"未验证就宣称完成"。**

真正能解决偷工减料的不是"更凶的提示词"，而是让退出条件从"模型说完了"变成"验收命令真的通过了"。