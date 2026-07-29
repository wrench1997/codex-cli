"""Run repeatable real-model evaluations for mcodex.

Usage:
  python scripts/run_agent_evaluation.py --list
  python scripts/run_agent_evaluation.py --scenario single-file-fix
  python scripts/run_agent_evaluation.py --all --output evaluation.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.codex.agent_evaluation import SCENARIOS, scenario_catalog, score_run
from src.codex.cli import ChatAgent
from src.codex.workspace_state import WorkspaceState


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def build_fixture(name: str, root: Path) -> str:
    if name in {"single-file-fix", "failure-recovery"}:
        _write(root / "discount.py", """def apply_discount(price, percent):
    if price < 0 or not 0 <= percent <= 100:
        raise ValueError("invalid input")
    return price * percent / 100
""")
        _write(root / "test_discount.py", """import pytest
from discount import apply_discount
def test_discount(): assert apply_discount(100, 20) == 80
def test_invalid():
    with pytest.raises(ValueError): apply_discount(-1, 20)
""")
        return (
            "修复 discount.py 的 apply_discount，保留输入校验且不要修改测试。"
            "先运行 python -m pytest -q，再修复并重跑；调用 verify_task，"
            "为每个验收项记录证据。"
        )
    if name == "multi-file-refactor":
        _write(root / "rates.py", "def discount_multiplier(percent):\n    return percent / 100\n")
        _write(root / "checkout.py", "from rates import discount_multiplier\ndef total(price, percent):\n    return price * discount_multiplier(percent)\n")
        _write(root / "test_checkout.py", "from checkout import total\ndef test_total(): assert total(100, 20) == 80\n")
        return (
            "修复 rates.py 与 checkout.py 的折扣计算，必须通过共享 helper 实现正确折后价；"
            "不要修改测试，运行 python -m pytest -q，并留下验收证据。"
        )
    if name == "long-output":
        _write(root / "large.log", "\n".join(f"line {i}: payload" for i in range(1, 1001)))
        return "读取 large.log 并报告第 900 行内容。使用分页读取，不能一次读取整个文件。"
    raise ValueError(f"{name} requires no model fixture")


async def run_model_scenario(name: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mcodex-eval-") as directory:
        root = Path(directory)
        prompt = build_fixture(name, root)
        agent = ChatAgent(str(root), auto_approve=True, agent_mode=True)
        agent.add_user(prompt)
        trace: list[dict[str, Any]] = []
        outputs: list[str] = []

        async def on_tool(name: str, args: dict[str, Any]) -> None:
            trace.append({"name": name, "args": args, "success": False})

        async def on_result(name: str, success: bool, output: str) -> None:
            for item in reversed(trace):
                if item["name"] == name and item["success"] is False:
                    item["success"] = success
                    break
            outputs.append(output)

        answer = await agent.run_turn(on_tool_call=on_tool, on_tool_result=on_result)
        task = agent.workspace_state.load_task() or {}
        task["checkpoint_count"] = agent.workspace_state.checkpoint_count()
        handoff = agent.workspace_state.write_handoff(task)
        result = score_run(
            name, trace, task, handoff_exists=handoff.exists(),
            overflow_seen=any("context" in item.lower() or "上下文" in item for item in outputs),
        )
        result.update({"answer": answer, "trace": trace, "task": task, "handoff_exists": handoff.exists()})
        return result


def run_resume_handoff() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mcodex-eval-") as directory:
        state = WorkspaceState(directory)
        task = state.save_task({"goal": "resume a task", "status": "implementing", "next_steps": ["run tests"]})
        state.checkpoint("seed", task)
        restored = ChatAgent(directory, agent_mode=False)
        task = state.load_task() or {}
        task["checkpoint_count"] = state.checkpoint_count()
        handoff = state.write_handoff(task)
        result = score_run("resume-handoff", [], task, handoff_exists=handoff.exists())
        result.update({"restored_goal": restored.task_goal, "task": task, "trace": [], "handoff_exists": handoff.exists()})
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate mcodex agent orchestration")
    parser.add_argument("--list", action="store_true", help="list scenarios")
    parser.add_argument("--scenario", choices=[item.name for item in SCENARIOS])
    parser.add_argument("--all", action="store_true", help="run every scenario")
    parser.add_argument("--output", help="write JSON report")
    args = parser.parse_args()
    if args.list:
        print(json.dumps(scenario_catalog(), ensure_ascii=False, indent=2))
        return
    names = [item.name for item in SCENARIOS] if args.all else [args.scenario or "single-file-fix"]
    results = []
    for name in names:
        result = run_resume_handoff() if name == "resume-handoff" else asyncio.run(run_model_scenario(name))
        results.append(result)
        print(f"{name}: {result['score']}/100 {'PASS' if result['passed'] else 'PARTIAL'}")
    report = {"scenarios": results, "average_score": round(sum(item["score"] for item in results) / len(results), 1)}
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
