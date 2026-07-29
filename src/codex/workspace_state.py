"""Long-lived, local-first state for engineering tasks.

Conversation history is intentionally not the source of truth.  This module
persists the small set of facts needed to resume a task and keeps tool evidence
in an append-only observation log that can be searched without reinjecting it
into every model request.
"""

from __future__ import annotations

import json
import os
import subprocess
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class WorkspaceState:
    def __init__(self, workdir: str):
        self.workdir = Path(workdir).resolve()
        self.root = self.workdir / ".mcodex"
        self.task_file = self.root / "active-task.json"
        self.archives_dir = self.root / "tasks"
        self.observations_file = self.root / "observations.jsonl"
        self.checkpoints_file = self.root / "checkpoints.jsonl"
        self.handoff_file = self.root / "handoff.md"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def git_state(self) -> dict[str, str | None]:
        def git(*args: str) -> str | None:
            try:
                return subprocess.check_output(
                    ["git", *args], cwd=self.workdir, text=True, stderr=subprocess.DEVNULL
                ).strip()
            except (subprocess.SubprocessError, OSError):
                return None
        return {"head": git("rev-parse", "HEAD"), "status": git("status", "--short")}

    def detect_git_drift(self) -> str:
        checkpoints = self._recent_json_lines(self.checkpoints_file, 1)
        if not checkpoints:
            return ""
        previous = checkpoints[-1]
        current = self.git_state()
        if previous.get("git_head") and current["head"] and previous["git_head"] != current["head"]:
            return "Git HEAD 已变化；恢复前必须检查提交与工作区差异。"
        if previous.get("git_status") != current["status"]:
            return "工作区状态已变化；恢复前必须检查未提交改动。"
        return ""

    def load_task(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.task_file.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def save_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task = dict(task)
        task.setdefault("schema_version", 1)
        existing = self.load_task()
        task.setdefault("task_id", (existing or {}).get("task_id", uuid.uuid4().hex[:12]))
        task.setdefault("created_at", self._now())
        task["updated_at"] = self._now()
        self._write_json(self.task_file, task)
        return task

    def record_observation(
        self, name: str, arguments: dict[str, Any], success: bool, output: str
    ) -> str:
        """Append full tool evidence locally; context receives only its safe excerpt."""
        self.root.mkdir(parents=True, exist_ok=True)
        observation_id = f"obs_{uuid.uuid4().hex[:12]}"
        # Avoid an accidental multi-gigabyte log while retaining normal test/log output.
        output = str(output)
        if len(output) > 1_000_000:
            output = output[:600_000] + "\n… [local evidence truncated at 1,000,000 characters] …\n" + output[-400_000:]
        item = {
            "id": observation_id,
            "timestamp": self._now(),
            "tool": name,
            "arguments": arguments,
            "success": success,
            "output": output,
        }
        with self.observations_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        return observation_id

    def search_observations(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query = query.lower().strip()
        if not query or not self.observations_file.exists():
            return []
        matches: list[dict[str, Any]] = []
        # 证据库可以很大；优先检索最近约 4 MiB，避免 /recall 自己制造内存问题。
        with self.observations_file.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 4 * 1024 * 1024))
            text = handle.read().decode("utf-8", errors="replace")
        for line in text.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            haystack = json.dumps(item.get("arguments", {}), ensure_ascii=False).lower() + "\n" + str(item.get("output", "")).lower()
            if query in haystack:
                matches.append({
                    "id": item.get("id"), "tool": item.get("tool"), "success": item.get("success"),
                    "timestamp": item.get("timestamp"), "excerpt": str(item.get("output", ""))[:1200],
                })
        return matches[-limit:][::-1]

    def checkpoint(self, label: str, task: dict[str, Any]) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        git_state = self.git_state()
        entry = {
            "id": f"cp_{uuid.uuid4().hex[:12]}", "timestamp": self._now(), "label": label or "checkpoint",
            "task_id": task.get("task_id"), "git_head": git_state["head"],
            "git_status": git_state["status"], "changed_files": task.get("changed_files", []),
            "status": task.get("status"), "next_steps": task.get("next_steps", []),
        }
        with self.checkpoints_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _recent_json_lines(self, path: Path, limit: int) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        records: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    def checkpoint_count(self) -> int:
        if not self.checkpoints_file.exists():
            return 0
        return len(self.checkpoints_file.read_text(encoding="utf-8", errors="replace").splitlines())

    def write_handoff(self, task: dict[str, Any]) -> Path:
        """Write a compact, human-readable task transfer report."""
        checkpoints = self._recent_json_lines(self.checkpoints_file, 1)
        observations = self._recent_json_lines(self.observations_file, 5)
        acceptance = task.get("acceptance_items", [])
        completed = {int(i) for i in task.get("completed_items", [])}
        evidence = task.get("acceptance_evidence", {})
        lines = [
            "# mcodex task handoff", "",
            f"- Task ID: `{task.get('task_id', 'unknown')}`",
            f"- Status: `{task.get('status', 'unknown')}`",
            f"- Updated: `{task.get('updated_at', self._now())}`", "",
            "## Goal", "", str(task.get("goal", "未记录")), "",
            "## Acceptance", "",
        ]
        if acceptance:
            for index, item in enumerate(acceptance, 1):
                state = "done" if index in completed else "pending"
                proof = str(evidence.get(str(index), ""))
                lines.append(f"- [{state}] {item}" + (f" — evidence: {proof}" if proof else ""))
        else:
            lines.append("- No explicit acceptance items recorded.")
        lines.extend([
            "", "## Changed files", "",
            *([f"- `{path}`" for path in task.get("changed_files", [])] or ["- None recorded."]),
            "", "## Next action", "",
            *([f"- {step}" for step in task.get("next_steps", [])] or ["- Inspect the working tree and active task before continuing."]),
            "", "## Latest checkpoint", "",
        ])
        if checkpoints:
            checkpoint = checkpoints[-1]
            lines.extend([
                f"- Label: {checkpoint.get('label', 'unknown')}",
                f"- Git HEAD: `{checkpoint.get('git_head') or 'not a Git repository'}`",
                f"- Git status: `{checkpoint.get('git_status') or 'clean'}`",
            ])
        else:
            lines.append("- No checkpoint recorded.")
        lines.extend(["", "## Recent tool evidence", ""])
        if observations:
            for item in observations:
                result = "passed" if item.get("success") else "failed"
                excerpt = str(item.get("output", "")).strip().replace("\n", " ")[:240]
                lines.append(f"- `{item.get('tool')}` ({result}): {excerpt}")
        else:
            lines.append("- No tool evidence recorded.")
        self.root.mkdir(parents=True, exist_ok=True)
        self.handoff_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.handoff_file

    def archive_task(self, task: dict[str, Any], status: str) -> Path:
        if status not in {"completed", "cancelled"}:
            raise ValueError("归档状态必须是 completed 或 cancelled")
        archived = dict(task)
        archived["status"] = status
        archived["archived_at"] = self._now()
        self.archives_dir.mkdir(parents=True, exist_ok=True)
        target = self.archives_dir / f"{archived.get('task_id', uuid.uuid4().hex[:12])}.json"
        self._write_json(target, archived)
        try:
            self.task_file.unlink()
        except FileNotFoundError:
            pass
        return target

    def create_worktree(self, name: str) -> tuple[str, str]:
        """Create an opt-in isolated worktree next to the current repository."""
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
        if not slug:
            raise ValueError("worktree 名称不能为空")
        try:
            subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=self.workdir, stderr=subprocess.DEVNULL)
        except (subprocess.SubprocessError, OSError) as exc:
            raise ValueError("当前工作目录不是 Git 仓库") from exc
        target = self.workdir.parent / f"{self.workdir.name}-{slug}"
        if target.exists():
            raise ValueError(f"目标目录已存在：{target}")
        branch = f"codex/{slug}"
        result = subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(target)], cwd=self.workdir,
            text=True, capture_output=True,
        )
        if result.returncode != 0:
            raise ValueError((result.stderr or result.stdout or "创建 worktree 失败").strip())
        return str(target), branch
