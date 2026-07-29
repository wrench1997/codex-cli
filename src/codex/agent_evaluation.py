"""Repeatable, local evaluation primitives for mcodex agent runs.

The evaluator grades orchestration evidence, not model prose: tool traces,
verification, durable task state, and handoff artifacts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EvaluationScenario:
    name: str
    description: str
    required_signals: tuple[str, ...]


SCENARIOS = (
    EvaluationScenario("single-file-fix", "Read, fix, and test one faulty source file.", ("read", "write", "test", "verify", "evidence")),
    EvaluationScenario("multi-file-refactor", "Modify coordinated implementation files without changing tests.", ("read", "write", "test", "verify", "evidence")),
    EvaluationScenario("failure-recovery", "Observe a failing test, repair the cause, then re-run successfully.", ("failure", "write", "test", "verify", "evidence")),
    EvaluationScenario("long-output", "Navigate a large file or log through bounded, paged tool output.", ("read", "pagination", "no_overflow")),
    EvaluationScenario("resume-handoff", "Restore durable task state and emit a complete handoff artifact.", ("restore", "handoff", "checkpoint")),
)


def scenario_catalog() -> list[dict[str, Any]]:
    return [asdict(item) for item in SCENARIOS]


def score_run(
    scenario: str,
    tool_trace: list[dict[str, Any]],
    task: dict[str, Any] | None,
    *,
    handoff_exists: bool = False,
    overflow_seen: bool = False,
) -> dict[str, Any]:
    """Return deterministic evidence-based scoring for one agent run."""
    names = [str(item.get("name", "")) for item in tool_trace]
    successes = {str(item.get("name", "")) for item in tool_trace if item.get("success")}
    failed = any(not item.get("success", True) for item in tool_trace)
    task = task or {}
    evidence = task.get("acceptance_evidence", {}) or {}
    passed = bool(task.get("verification_passed"))
    completed = set(task.get("completed_items", []))

    checks = {
        "read": any(name in {"read_file", "search_in_files"} for name in names),
        "write": any(name in {"write_file", "search_replace", "insert_lines", "delete_lines", "replace_lines", "apply_patch"} for name in names),
        "test": "execute_shell" in successes,
        "verify": "verify_task" in successes and passed,
        "evidence": bool(evidence) and bool(completed),
        "failure": failed,
        "pagination": (
            sum(name == "read_file" for name in names) >= 2
            or any(
                item.get("name") == "read_file"
                and (item.get("args", {}).get("start_line") or item.get("args", {}).get("end_line"))
                for item in tool_trace
            )
        ),
        "no_overflow": not overflow_seen,
        "restore": bool(task.get("goal")),
        "handoff": handoff_exists,
        "checkpoint": bool(task.get("last_checkpoint") or task.get("checkpoint_count")),
    }
    required = next(item.required_signals for item in SCENARIOS if item.name == scenario)
    passed_checks = [name for name in required if checks.get(name)]
    score = round(100 * len(passed_checks) / len(required)) if required else 0
    return {
        "scenario": scenario,
        "score": score,
        "passed": len(passed_checks) == len(required),
        "checks": checks,
        "missing": [name for name in required if name not in passed_checks],
        "tool_count": len(tool_trace),
    }
