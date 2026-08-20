"""JSONL backend for the Tauri workbench, backed by the normal ``ChatAgent``."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from . import cli
from .cli import ChatAgent
from .config import CONFIG


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event(writer: Callable[[dict[str, Any]], None], event_type: str, **payload: Any) -> None:
    writer({"type": event_type, **payload})


class DesktopSessionStore:
    """Project-local UI session index; secrets deliberately never enter it."""

    def __init__(self, workdir: str):
        self.root = Path(workdir).resolve() / ".mcodex" / "desktop"
        self.index_path = self.root / "sessions.json"

    def _read_index(self) -> dict[str, Any]:
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {"sessions": []}
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {"sessions": []}

    def _write(self, path: Path, value: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def list_sessions(self) -> list[dict[str, Any]]:
        return list(self._read_index().get("sessions", []))

    def create(self) -> dict[str, Any]:
        session = {"id": uuid.uuid4().hex[:12], "title": "新对话", "created_at": _now(), "updated_at": _now()}
        index = self._read_index()
        index["sessions"] = [session, *index.get("sessions", [])]
        self._write(self.index_path, index)
        return session

    def load(self, session_id: str) -> dict[str, Any] | None:
        try:
            value = json.loads((self.root / f"{session_id}.json").read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None

    def save(self, session_id: str, agent: ChatAgent, timeline: list[dict[str, Any]]) -> None:
        index = self._read_index()
        sessions = index.get("sessions", [])
        metadata = next((item for item in sessions if item.get("id") == session_id), None)
        if metadata is None:
            metadata = {"id": session_id, "title": "新对话", "created_at": _now()}
            sessions.insert(0, metadata)
        first_user = next((item.get("text", "") for item in timeline if item.get("type") == "user"), "")
        if first_user:
            metadata["title"] = first_user.replace("\n", " ")[:48]
        metadata["updated_at"] = _now()
        index["sessions"] = sorted(sessions, key=lambda item: item.get("updated_at", ""), reverse=True)
        self._write(self.index_path, index)
        self._write(self.root / f"{session_id}.json", {"id": session_id, "updated_at": metadata["updated_at"],
            "input_items": agent.input_items, "timeline": timeline[-500:]})


def create_agent(options: dict[str, Any]) -> ChatAgent:
    for key, attribute in (("api", "api_base"), ("model", "model"), ("api_mode", "api_mode"),
                           ("tool_transport", "tool_transport"), ("temperature", "temperature")):
        value = options.get(key)
        if value is not None and value != "":
            setattr(CONFIG, attribute, value.lower() if key in {"api_mode", "tool_transport"} else value)
    workdir = os.path.abspath(str(options.get("workdir") or os.getcwd()))
    if not os.path.isdir(workdir):
        raise ValueError(f"项目目录不存在: {workdir}")
    return ChatAgent(workdir=workdir, auto_approve=bool(options.get("auto_approve", True)),
                     agent_mode=not bool(options.get("no_agent", False)))


def task_snapshot(agent: ChatAgent) -> dict[str, Any]:
    agent._persist_workspace_task()
    return agent.workspace_state.load_task() or agent._task_snapshot()


def read_diff(workdir: str, path: str = "") -> str:
    args = ["git", "diff", "--", path] if path else ["git", "diff"]
    try:
        result = subprocess.run(args, cwd=workdir, text=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"无法读取 Git 差异：{exc}"
    if result.returncode != 0:
        return result.stderr.strip() or "当前目录不是 Git 仓库。"
    return result.stdout or "没有可显示的 Git 差异。"


async def serve() -> None:
    cli.console = Console(file=sys.stderr)
    loop = asyncio.get_running_loop()

    def write(event: dict[str, Any]) -> None:
        print(json.dumps(event, ensure_ascii=False), flush=True)

    agent: ChatAgent | None = None
    store: DesktopSessionStore | None = None
    session_id = ""
    timeline: list[dict[str, Any]] = []
    running: asyncio.Task[Any] | None = None
    cancel_event: asyncio.Event | None = None

    def emit_state() -> None:
        if agent:
            _event(write, "task_state", task=task_snapshot(agent))

    def save_session() -> None:
        if agent and store and session_id:
            store.save(session_id, agent, timeline)

    def activate(target: str | None, fresh: bool = False) -> None:
        nonlocal session_id, timeline
        if not agent or not store:
            raise RuntimeError("desktop backend has not been started")
        save_session()
        session = store.create() if fresh else next((item for item in store.list_sessions() if item.get("id") == target), None)
        if not session:
            raise ValueError("会话不存在")
        session_id = str(session["id"])
        loaded = store.load(session_id) or {}
        history = loaded.get("input_items", [])
        agent.reset()
        if isinstance(history, list) and len(history) > 1:
            agent.input_items = [agent.system_item, *history[1:]]
        # A desktop session restores conversational context; the shared CLI
        # ledger is restored separately so its task status remains visible.
        agent._restore_workspace_task()
        timeline = list(loaded.get("timeline", []))
        _event(write, "session", session_id=session_id, timeline=timeline, sessions=store.list_sessions())
        emit_state()

    async def run_message(text: str) -> None:
        nonlocal running, cancel_event
        assert agent is not None
        cancel_event = asyncio.Event()
        item = {"type": "user", "text": text, "at": _now()}
        timeline.append(item); _event(write, "timeline", item=item)

        async def on_token(token: str) -> None:
            _event(write, "token", text=token)

        async def on_tool_call(name: str, arguments: dict[str, Any]) -> None:
            entry = {"type": "tool_call", "name": name, "arguments": arguments, "at": _now()}
            timeline.append(entry); _event(write, "timeline", item=entry)

        async def on_tool_result(name: str, success: bool, output: str) -> None:
            entry = {"type": "tool_result", "name": name, "success": success, "output": output, "at": _now()}
            timeline.append(entry); _event(write, "timeline", item=entry)

        try:
            agent.add_user(text)
            result = await agent.run_turn(on_token=on_token, on_tool_call=on_tool_call,
                                          on_tool_result=on_tool_result, cancel_event=cancel_event)
            entry = {"type": "assistant", "text": result, "at": _now()}
            timeline.append(entry); _event(write, "complete", text=result, exit_kind="normal")
        except asyncio.CancelledError:
            locally_cancelled = bool(cancel_event and cancel_event.is_set())
            reason = (
                "本地取消（停止按钮或会话关闭）"
                if locally_cancelled else "异常：外层任务取消，非本地停止操作"
            )
            entry = {"type": "cancelled", "text": f"生成退出：{reason}", "at": _now()}
            timeline.append(entry); _event(
                write, "cancelled", message=entry["text"],
                exit_kind="local_cancel" if locally_cancelled else "external_cancel",
            )
        except Exception as exc:
            entry = {"type": "error", "text": str(exc), "at": _now()}
            timeline.append(entry); _event(write, "error", message=str(exc), exit_kind="abnormal")
        finally:
            save_session(); emit_state(); running = None; cancel_event = None

    _event(write, "ready")
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            if cancel_event: cancel_event.set()
            return
        try:
            request = json.loads(line); action = request.get("action")
            if action == "start":
                if agent: raise RuntimeError("desktop backend is already running")
                agent = create_agent(request.get("options") or {}); store = DesktopSessionStore(agent.workdir)
                sessions = store.list_sessions(); _event(write, "started", workdir=agent.workdir, sessions=sessions)
                activate(sessions[0]["id"] if sessions else None, fresh=not sessions)
            elif action == "message":
                if not agent: raise RuntimeError("desktop backend has not been started")
                if running: raise RuntimeError("当前任务仍在运行，请先停止或等待完成")
                text = str(request.get("text") or "").strip()
                if not text: raise ValueError("消息不能为空")
                running = loop.create_task(run_message(text))
            elif action == "cancel":
                if not cancel_event: raise RuntimeError("当前没有可停止的任务")
                cancel_event.set()
            elif action == "new_session":
                if running: raise RuntimeError("生成期间不能切换会话")
                activate(None, fresh=True)
            elif action == "select_session":
                if running: raise RuntimeError("生成期间不能切换会话")
                activate(str(request.get("session_id", "")))
            elif action == "task_action":
                if not agent: raise RuntimeError("desktop backend has not been started")
                name = str(request.get("name", ""))
                if name == "checkpoint":
                    agent._persist_workspace_task(); agent.workspace_state.checkpoint(str(request.get("label") or "desktop"), task_snapshot(agent))
                elif name == "handoff":
                    agent._persist_workspace_task(); agent.workspace_state.write_handoff(task_snapshot(agent))
                elif name == "resume":
                    agent.reset(); agent._restore_workspace_task()
                elif name == "diff":
                    path = str(request.get("path") or "")
                    _event(write, "diff", path=path, content=read_diff(agent.workdir, path))
                else:
                    raise ValueError(f"未知任务操作: {name}")
                emit_state(); save_session()
            elif action == "shutdown":
                if cancel_event: cancel_event.set()
                if running: await running
                save_session(); _event(write, "stopped"); return
            else:
                raise ValueError(f"unsupported desktop action: {action!r}")
        except Exception as exc:
            _event(write, "error", message=str(exc))


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
