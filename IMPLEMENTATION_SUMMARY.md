# 工程执行协议实现总结

## 改动概述

本次实现解决了 AI 编程助手"未验证就宣称完成"的核心问题，通过**四层防护机制**确保代码质量。

## 新增文件

### 1. `agent/skills.md` - 项目宪法
- 定义工程纪律和开发流程
- 明确"最小改动是手段，不是目标"
- 规定 5 个必须遵循的开发阶段
- 定义完成条件的 4 个必要条件

### 2. `agent/quality.yaml` - 质量门禁配置
- 定义项目必须执行的验证命令
- 支持 diff_check / lint / build / test
- 可配置哪些命令是必需的
- 包含项目规则提醒

### 3. `agent/lessons.md` - 教训与回归规则
- 记录已踩过的坑和不可复发的规则
- 提供标准模板
- 优先级高于临时推测

### 4. `docs/ENGINEERING_PROTOCOL.md` - 详细文档
- 四层防护机制的完整说明
- 使用建议和效果对比
- 新项目快速启动指南

## 代码改动

### `src/codex/cli.py`

#### 新增 `TaskState` 类（约 50 行）
```python
class TaskState:
    dirty = False                    # 是否改过代码
    acceptance_items: list[str] = []  # 验收项列表
    changed_files: set[str] = set()   # 已修改的文件
    verification_passed = False       # 验证是否通过
```

#### 修改 `ChatAgent.__init__`
- 初始化 `self.task_state = TaskState()`
- 增强系统提示词，强调验证规则

#### 修改 `ChatAgent.reset`
- 重置任务状态

#### 修改 `ChatAgent.run_turn`
- 跟踪文件修改（写操作工具调用后）
- **关键门禁**: 当模型不再调用工具时，检查 `task_state.dirty`
- 如果代码已修改但未验证，自动插入系统消息强制要求验证

#### 新增 `/verify` 内置命令
- 手动触发任务验证
- 显示验证报告

### `src/codex/tools.py`

#### 新增 `verify_task` 工具
- 读取 `agent/quality.yaml`
- 自动执行所有验证命令
- 返回详细验证报告
- 支持验收项核对

#### 工具执行跟踪
- 写操作成功后标记 `modified_files`
- 更新 `task_state.mark_modified()`

### `.env.example`
- 调整默认温度从 `0.6` 到 `0.2`（更适合代码任务）
- 添加温度设置建议注释

### `README.md`
- 新增"工程执行协议"功能特性
- 新增 `verify_task` 工具说明
- 新增 `/verify` 命令文档

### `upload_config.yaml`
- 包含 `agent/` 目录到打包文件

## 核心机制

### 门禁逻辑

```python
# 当模型不再调用工具时
if not tool_calls:
    if self.task_state.dirty and not self.task_state.can_finish():
        # 强制插入系统消息
        self.add_user("【系统门禁】⚠️ 代码已修改但未验证...")
        continue  # 不让结束
    
    # 只有通过验证或没改代码才能结束
    self.add_assistant(visible_text)
    return visible_text
```

### 验证流程

```
用户：修复这个 bug
  ↓
AI: （调用 search_replace 修改代码）
  ↓
系统：task_state.dirty = True
  ↓
AI: （尝试结束，不再调用工具）
  ↓
系统：【门禁】检测到代码已修改但未验证
      必须调用 verify_task 或报告未完成原因
  ↓
AI: <tool_call><function=verify_task/></tool_call>
  ↓
系统：执行 quality.yaml 中的命令
      ✅ diff_check
      ✅ lint
      ❌ build → 失败
  ↓
AI: （修复构建问题）
  ↓
AI: <tool_call><function=verify_task/></tool_call>
  ↓
系统：✅ 所有验证通过
  ↓
AI: 任务完成。已修复 XXX，验证命令全部通过。
```

## 使用建议

### 温度设置

```bash
# 代码任务（修复 bug、重构、跟随既有架构）
CODEX_TEMPERATURE=0.15~0.25

# 讨论/设计/创意任务
CODEX_TEMPERATURE=0.6~0.8
```

### 新项目集成

只需在项目根目录创建 `agent/` 文件夹：

```bash
your-project/
  agent/
    skills.md      # 从本模板复制
    quality.yaml   # 根据项目类型修改命令
    lessons.md     # 初始可为空模板
```

Codex CLI 会自动加载并强制执行。

### 自定义验证命令

编辑 `agent/quality.yaml`：

```yaml
commands:
  # Python 项目
  lint:
    command: "ruff check src/"
    required: true
  test:
    command: "pytest tests/ -v"
    required: true
    
  # TypeScript 项目
  # lint:
  #   command: "pnpm lint"
  #   required: true
  # test:
  #   command: "pnpm test"
  #   required: true
  
  # Zig 项目
  # build:
  #   command: "zig build"
  #   required: true
  # test:
  #   command: "zig build test"
  #   required: true
```

## 测试验证

```bash
# 1. 语法检查
python -m py_compile src/codex/cli.py src/codex/tools.py

# 2. 导入测试
python -c "from src.codex.cli import ChatAgent, TaskState; print('OK')"

# 3. 运行 CLI（手动测试 verify_task）
python -m src.codex.cli
>>> /verify
```

## 预期效果

### 使用前
```
用户：修复这个 bug
AI: 好的，已修复。（实际没跑测试）
用户：（运行测试）还是错的！
```

### 使用后
```
用户：修复这个 bug
AI: （修改代码）
系统：【门禁】请调用 verify_task
AI: <tool_call><function=verify_task/></tool_call>
系统：❌ 测试失败
AI: （修复）
AI: <tool_call><function=verify_task/></tool_call>
系统：✅ 通过
AI: 任务完成，测试通过。
```

## 核心原则

> **提示词负责说明目标；程序负责阻止"未验证就宣称完成"。**

真正能解决偷工减料的不是"更凶的提示词"，而是让退出条件从"模型说完了"变成"验收命令真的通过了"。

## 后续优化建议

1. **任务契约文件** - 创建 `.codex/task.json` 结构化存储验收项
2. **自动提取验收项** - 从用户消息中 NLP 提取验收项
3. **回归测试自动化** - 把 lessons.md 规则变成自动测试
4. **验证结果缓存** - 避免重复执行相同验证
5. **更细粒度的状态** - 区分"部分验证通过"和"完全验证通过"

## 相关文件清单

```
D:\workspace\codex-cli\
├── agent/
│   ├── skills.md          # 新增：项目宪法
│   ├── quality.yaml       # 新增：质量门禁配置
│   └── lessons.md         # 新增：教训与回归规则
├── docs/
│   └── ENGINEERING_PROTOCOL.md  # 新增：详细文档
├── src/codex/
│   ├── cli.py             # 修改：TaskState + 门禁逻辑
│   └── tools.py           # 修改：verify_task 工具
├── .env.example           # 修改：默认温度 0.2
├── README.md              # 修改：新增功能说明
└── upload_config.yaml     # 修改：包含 agent/ 目录
```

## 提交建议

```bash
git add agent/ docs/ENGINEERING_PROTOCOL.md
git add src/codex/cli.py src/codex/tools.py
git add .env.example README.md upload_config.yaml
git commit -m "feat: 实现工程执行协议，防止 AI 未验证就宣称完成

- 新增 agent/skills.md 项目宪法，定义工程纪律
- 新增 agent/quality.yaml 质量门禁配置
- 新增 agent/lessons.md 教训与回归规则
- 新增 verify_task 工具，自动执行验证命令
- 新增 TaskState 类跟踪任务状态
- 实现代码门禁：修改后必须验证才能结束
- 调整默认温度到 0.2（更适合代码任务）
- 新增 /verify 内置命令

详细文档：docs/ENGINEERING_PROTOCOL.md"
```