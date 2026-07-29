from src.codex.agent_evaluation import SCENARIOS, scenario_catalog, score_run
from src.codex.cli import TaskState, _classify_tool_failure


def test_catalog_covers_five_long_running_scenarios():
    assert {item.name for item in SCENARIOS} == {
        "single-file-fix", "multi-file-refactor", "failure-recovery", "long-output", "resume-handoff",
    }
    assert len(scenario_catalog()) == 5


def test_score_requires_durable_evidence_not_model_text():
    trace = [
        {"name": "read_file", "success": True},
        {"name": "search_replace", "success": True},
        {"name": "execute_shell", "success": True},
        {"name": "verify_task", "success": True},
    ]
    no_evidence = score_run("single-file-fix", trace, {"verification_passed": True, "completed_items": []})
    with_evidence = score_run("single-file-fix", trace, {
        "verification_passed": True, "completed_items": [1], "acceptance_evidence": {"1": "pytest passed"},
    })

    assert no_evidence["score"] == 80
    assert with_evidence["passed"]


def test_verify_contract_fallback_requires_evidence_before_done():
    state = TaskState()
    state.ensure_acceptance_items(["formula fixed", "tests pass"])
    state.mark_verified(True)

    assert state.status == "verifying"
    state.mark_item_completed(1)
    assert state.status == "verifying"
    state.mark_item_completed(2)
    assert state.status == "done"


def test_failure_classifier_covers_actionable_categories():
    assert _classify_tool_failure("command timeout after 30s") == "timeout"
    assert _classify_tool_failure("Context length exceeded") == "context_limit"
    assert _classify_tool_failure("permission denied") == "permission"


def test_long_output_accepts_precise_line_reads_without_forced_pagination():
    result = score_run(
        "long-output",
        [{"name": "read_file", "args": {"path": "large.log", "start_line": 900, "end_line": 900}, "success": True}],
        {},
    )
    assert result["passed"]
