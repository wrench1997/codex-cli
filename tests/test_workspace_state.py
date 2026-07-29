import asyncio
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys

from src.codex.cli import ChatAgent
from src.codex.config import CONFIG
from src.codex.tools import ToolExecutor
from src.codex.workspace_state import WorkspaceState


def _start_faulty_sse_server(mode: str):
    """Start a local endpoint that either stalls or closes an SSE response."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            pass

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            if size:
                self.rfile.read(size)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            if mode == "stall":
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Connection", "close")
            self.end_headers()
            if mode == "stall":
                # 先确认 SSE 连接已建立，再模拟上游长时间不再发送 token。
                self.wfile.write(b"D\r\n: connected\n\n\r\n")
            self.wfile.flush()
            if mode == "stall":
                time.sleep(1.5)
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}/v1"


def _stop_faulty_sse_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_workspace_task_and_observations_persist(tmp_path):
    state = WorkspaceState(str(tmp_path))
    task = state.save_task({"goal": "fix regression", "status": "implementing", "changed_files": ["app.py"]})
    observation_id = state.record_observation("execute_shell", {"command": "pytest"}, True, "42 passed")

    loaded = state.load_task()
    matches = state.search_observations("42 passed")

    assert loaded["task_id"] == task["task_id"]
    assert loaded["goal"] == "fix regression"
    assert matches[0]["id"] == observation_id
    assert matches[0]["tool"] == "execute_shell"

    updated = state.save_task({"goal": "fix regression", "status": "verifying"})
    assert updated["task_id"] == task["task_id"]


def test_agent_restores_persisted_task(tmp_path):
    state = WorkspaceState(str(tmp_path))
    state.save_task({
        "goal": "persist task", "status": "implementing", "acceptance_items": ["tests pass"],
        "completed_items": [], "changed_files": ["module.py"], "verification_passed": False,
        "memory_summary": "root cause found", "next_steps": ["run tests"],
    })

    agent = ChatAgent(str(tmp_path), agent_mode=False)

    assert agent.task_goal == "persist task"
    assert agent.task_state.changed_files == {"module.py"}
    assert "恢复的工程任务" in agent.input_items[-1]["content"]


def test_agent_creates_resumable_task_from_first_request(tmp_path):
    agent = ChatAgent(str(tmp_path), agent_mode=True)
    agent.add_user("修复登录超时")

    task = WorkspaceState(str(tmp_path)).load_task()
    assert task["goal"] == "修复登录超时"
    assert task["status"] == "planning"
    assert task["next_steps"] == ["确认范围和验收项"]


def test_acceptance_completion_requires_evidence(tmp_path):
    executor = ToolExecutor(str(tmp_path))
    success, output = asyncio.run(executor.execute("complete_acceptance_item", {"index": 1, "evidence": "pytest: 10 passed"}))
    assert success
    assert "已记录证据" in output

    success, _ = asyncio.run(executor.execute("complete_acceptance_item", {"index": 1, "evidence": ""}))
    assert not success


def test_handoff_contains_evidence_and_archive_removes_active_task(tmp_path):
    state = WorkspaceState(str(tmp_path))
    task = state.save_task({
        "goal": "ship feature", "status": "done", "acceptance_items": ["tests pass"],
        "completed_items": [1], "acceptance_evidence": {"1": "pytest: 12 passed"},
        "changed_files": ["feature.py"], "next_steps": [],
    })
    state.record_observation("execute_shell", {"command": "pytest"}, True, "12 passed")
    state.checkpoint("verification-passed", task)

    handoff = state.write_handoff(task)
    text = handoff.read_text(encoding="utf-8")
    archive = state.archive_task(task, "completed")

    assert "ship feature" in text
    assert "pytest: 12 passed" in text
    assert "verification-passed" in text
    assert archive.exists()
    assert state.load_task() is None


def test_verify_arguments_create_missing_contract_and_persist_evidence(tmp_path, monkeypatch):
    agent = ChatAgent(str(tmp_path), agent_mode=True)
    agent.add_user("repair issue")
    responses = iter([
        {"output": [{"type": "function_call", "id": "verify", "call_id": "verify", "name": "verify_task", "arguments": '{"acceptance_items":["fix works","tests pass"]}'}]},
        {"output": [
            {"type": "function_call", "id": "accept1", "call_id": "accept1", "name": "complete_acceptance_item", "arguments": '{"index":1,"evidence":"observed result"}'},
            {"type": "function_call", "id": "accept2", "call_id": "accept2", "name": "complete_acceptance_item", "arguments": '{"index":2,"evidence":"pytest passed"}'},
        ]},
        {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "done"}]}]},
    ])

    async def fake_stream_request(**_kwargs):
        return "", next(responses)

    async def fake_execute(name, _args):
        return True, f"{name} ok"

    monkeypatch.setattr(agent, "_stream_request", fake_stream_request)
    monkeypatch.setattr(agent.executor, "execute", fake_execute)
    assert asyncio.run(agent.run_turn()) == "done"

    task = WorkspaceState(str(tmp_path)).load_task()
    assert task["acceptance_items"] == ["fix works", "tests pass"]
    assert task["completed_items"] == [1, 2]
    assert task["acceptance_evidence"] == {"1": "observed result", "2": "pytest passed"}
    assert task["status"] == "done"


def test_repeated_tool_failure_marks_task_blocked(tmp_path, monkeypatch):
    agent = ChatAgent(str(tmp_path), agent_mode=True)
    agent.add_user("run fragile command")
    monkeypatch.setattr(CONFIG, "tool_retry_budget", 2)
    responses = iter([
        {"output": [{"type": "function_call", "id": str(i), "call_id": str(i), "name": "execute_shell", "arguments": '{"command":"false"}'}]}
        for i in range(3)
    ] + [{"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "blocked"}]}]}])

    async def fake_stream_request(**_kwargs):
        return "", next(responses)

    async def fake_execute(_name, _args):
        return False, "❌ exit=1"

    monkeypatch.setattr(agent, "_stream_request", fake_stream_request)
    monkeypatch.setattr(agent.executor, "execute", fake_execute)
    assert asyncio.run(agent.run_turn()) == "blocked"

    task = WorkspaceState(str(tmp_path)).load_task()
    assert task["status"] == "blocked"
    assert len(task["failure_events"]) == 2


def test_worktree_creation_uses_isolated_codex_branch(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=tmp_path, check=True, capture_output=True)

    path, branch = WorkspaceState(str(tmp_path)).create_worktree("evaluation")

    assert branch == "codex/evaluation"
    assert (Path(path) / "README.md").exists()


def test_corrupt_task_ledger_is_ignored_without_crashing(tmp_path):
    state = WorkspaceState(str(tmp_path))
    state.root.mkdir()
    state.task_file.write_text("{not valid json", encoding="utf-8")

    assert state.load_task() is None
    assert ChatAgent(str(tmp_path), agent_mode=False).task_goal == ""


def test_restore_detects_git_worktree_drift(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "module.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=tmp_path, check=True, capture_output=True)

    state = WorkspaceState(str(tmp_path))
    task = state.save_task({"goal": "resume", "status": "implementing"})
    state.checkpoint("before-pause", task)
    source.write_text("value = 2\n", encoding="utf-8")

    assert "工作区状态已变化" in state.detect_git_drift()
    restored = ChatAgent(str(tmp_path), agent_mode=False)
    assert "工作区状态已变化" in restored.restore_drift


def test_long_shell_command_can_be_cancelled_and_persisted(tmp_path, monkeypatch):
    agent = ChatAgent(str(tmp_path), agent_mode=True)
    agent.add_user("download a large artifact")
    responses = iter([
        {"output": [{"type": "function_call", "id": "shell", "call_id": "shell", "name": "execute_shell", "arguments": '{"command":"' + sys.executable.replace("\\", "\\\\") + ' -c \\"import time; time.sleep(10)\\""}'}]},
    ])

    async def fake_stream_request(**_kwargs):
        return "", next(responses)

    monkeypatch.setattr(agent, "_stream_request", fake_stream_request)

    async def run_and_cancel():
        cancel_event = asyncio.Event()
        async def cancel_soon():
            await asyncio.sleep(0.3)
            cancel_event.set()
        canceller = asyncio.create_task(cancel_soon())
        try:
            await agent.run_turn(cancel_event=cancel_event)
        finally:
            await canceller

    try:
        asyncio.run(run_and_cancel())
        assert False, "expected cancellation"
    except asyncio.CancelledError:
        pass

    task = WorkspaceState(str(tmp_path)).load_task()
    assert task["status"] == "blocked"
    assert "用户取消" in task["block_reason"]
    assert WorkspaceState(str(tmp_path)).checkpoint_count() >= 1


def test_silent_sse_stream_cancellation_persists_recovery_state(tmp_path):
    server, thread, api_base = _start_faulty_sse_server("stall")
    try:
        agent = ChatAgent(str(tmp_path), api_base=api_base, agent_mode=True)
        agent.api_mode = "chat"
        agent._resolved_api_mode = "chat"
        agent.add_user("stop the stalled model request")

        async def cancel_stream():
            cancel_event = asyncio.Event()
            asyncio.get_running_loop().call_later(0.2, cancel_event.set)
            try:
                await agent.run_turn(cancel_event=cancel_event)
                assert False, "expected cancellation"
            except asyncio.CancelledError:
                pass

        asyncio.run(cancel_stream())
        task = WorkspaceState(str(tmp_path)).load_task()
        assert task["status"] == "blocked"
        assert "用户取消" in task["block_reason"]
        assert WorkspaceState(str(tmp_path)).checkpoint_count() >= 1
    finally:
        _stop_faulty_sse_server(server, thread)


def test_closed_sse_stream_marks_task_blocked_and_checkpoints(tmp_path):
    server, thread, api_base = _start_faulty_sse_server("close")
    try:
        agent = ChatAgent(str(tmp_path), api_base=api_base, agent_mode=True)
        agent.api_mode = "chat"
        agent._resolved_api_mode = "chat"
        agent.add_user("diagnose connection failure")

        try:
            asyncio.run(agent.run_turn())
            assert False, "expected connection failure"
        except RuntimeError as exc:
            assert "空响应" in str(exc)

        task = WorkspaceState(str(tmp_path)).load_task()
        assert task["status"] == "blocked"
        assert "模型服务异常" in task["block_reason"]
        assert WorkspaceState(str(tmp_path)).checkpoint_count() >= 1
    finally:
        _stop_faulty_sse_server(server, thread)
