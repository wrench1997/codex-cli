import asyncio

from src.codex.cli import ChatAgent
from src.codex.config import CONFIG
from src.codex.tools import ToolExecutor


def test_read_file_is_paginated_and_reports_next_page(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "max_read_file_lines", 3)
    path = tmp_path / "large.txt"
    path.write_text("\n".join(f"line {i}" for i in range(1, 8)), encoding="utf-8")

    success, output = asyncio.run(
        ToolExecutor(str(tmp_path)).execute("read_file", {"path": "large.txt"})
    )

    assert success
    assert "显示 1-3 行" in output
    assert "line 3" in output
    assert "line 4" not in output
    assert "start_line=4" in output


def test_read_file_caps_explicit_range_to_safe_page_size(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "max_read_file_lines", 2)
    path = tmp_path / "large.txt"
    path.write_text("\n".join(f"line {i}" for i in range(1, 8)), encoding="utf-8")

    success, output = asyncio.run(
        ToolExecutor(str(tmp_path)).execute(
            "read_file", {"path": "large.txt", "start_line": 3, "end_line": 99}
        )
    )

    assert success
    assert "显示 3-4 行" in output
    assert "line 5" not in output
    assert "start_line=5" in output


def test_all_tool_output_is_head_tail_truncated(monkeypatch):
    monkeypatch.setattr(CONFIG, "max_tool_output_chars", 300)
    monkeypatch.setattr(CONFIG, "max_tool_output_lines", 4)

    output = ToolExecutor._truncate_output("execute_shell", "first\nsecond\nthird\nfourth\nfifth\nlast")

    assert "first" in output
    assert "last" in output
    assert "已截断 execute_shell 输出" in output
    assert len(output) <= 300


def test_context_compaction_falls_back_and_reduces_history(tmp_path, monkeypatch):
    agent = ChatAgent(str(tmp_path), agent_mode=False)
    agent.input_items = [
        {"type": "message", "role": "system", "content": "system"},
        {"type": "message", "role": "user", "content": "old request"},
        {"type": "message", "role": "assistant", "content": "x" * 20_000},
        {"type": "message", "role": "user", "content": "recent request"},
        {"type": "message", "role": "assistant", "content": "recent answer"},
    ]
    monkeypatch.setattr(CONFIG, "keep_recent_turns", 1)

    async def failed_summary(_history):
        return None

    monkeypatch.setattr(agent, "_generate_summary", failed_summary)
    before = agent.estimate_tokens()
    assert asyncio.run(agent.compress_context())

    assert agent.estimate_tokens() < before
    assert "本地压缩检查点" in agent.memory_summary
    assert agent.input_items[-2]["content"] == "recent request"
