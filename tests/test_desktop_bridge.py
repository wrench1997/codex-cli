import json
import subprocess
import sys
from pathlib import Path

from src.codex.desktop_bridge import DesktopSessionStore, read_diff


class _Agent:
    def __init__(self):
        self.input_items = [{"role": "system", "content": "system"}, {"role": "user", "content": "hello"}]


def test_desktop_sessions_are_project_local_and_keep_history(tmp_path):
    store = DesktopSessionStore(str(tmp_path))
    session = store.create()
    agent = _Agent()

    store.save(session["id"], agent, [{"type": "user", "text": "写一个功能"}])

    loaded = store.load(session["id"])
    assert store.list_sessions()[0]["title"] == "写一个功能"
    assert loaded["input_items"] == agent.input_items
    assert loaded["timeline"] == [{"type": "user", "text": "写一个功能"}]
    assert not any("api" in Path(path).name.lower() for path in (tmp_path / ".mcodex" / "desktop").iterdir())


def test_read_diff_reports_non_git_directory(tmp_path):
    output = read_diff(str(tmp_path))

    assert "Git" in output or "git" in output


def test_desktop_bridge_starts_and_creates_project_session(tmp_path):
    requests = [
        {"action": "start", "options": {"workdir": str(tmp_path), "auto_approve": True}},
        {"action": "new_session"},
        {"action": "shutdown"},
    ]
    payload = "\n".join(json.dumps(item) for item in requests) + "\n"
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, "-m", "src.codex.desktop_bridge"], cwd=project_root,
        input=payload, text=True, capture_output=True, timeout=15,
    )

    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 0, result.stderr
    assert any(item["type"] == "started" for item in events)
    assert sum(item["type"] == "session" for item in events) == 2
    assert events[-1]["type"] == "stopped"
    assert (tmp_path / ".mcodex" / "desktop" / "sessions.json").exists()
