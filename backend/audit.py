"""Append-only audit trail for agent activity (output/audit_trail.json).

The file is a JSON list. Each write takes a thread lock and a cross-process lock
file, reads the list, appends, and atomically replaces the file, so concurrent
writers cannot interleave or truncate it. The file is never wiped: if it ever
fails to parse, it is moved aside to audit_trail.corrupt-<time>.json first.
Known secret values are redacted before anything is written.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

import config

_thread_lock = threading.Lock()
LOCK_TIMEOUT_S = 15.0
STALE_LOCK_S = 60.0
SECRET_ENV_VARS = ("PORTKEY_API_KEY", "OPENAI_API_KEY")


def _secrets() -> list[str]:
    return [v for v in (os.getenv(n, "").strip() for n in SECRET_ENV_VARS) if len(v) >= 8]


def redact(value: Any) -> Any:
    """Replace any known secret value inside strings, dicts and lists."""
    secrets = _secrets()
    if not secrets:
        return value
    if isinstance(value, str):
        for s in secrets:
            value = value.replace(s, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def preview(value: Any, limit: int = config.RESULT_PREVIEW_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(to_jsonable_python(value), ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _FileLock:
    """Cross-process lock using an exclusively created lock file."""

    def __init__(self, target: Path):
        self.path = target.with_name(target.name + ".lock")

    def __enter__(self) -> None:
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return
            except (FileExistsError, PermissionError):
                # Windows reports PermissionError while another process's lock file is being deleted
                # ("delete pending"); that also means the lock is busy, so wait and retry.
                try:
                    if time.time() - self.path.stat().st_mtime > STALE_LOCK_S:
                        self.path.unlink(missing_ok=True)
                        continue
                except (FileNotFoundError, PermissionError):
                    pass
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Could not lock {self.path.name}")
                time.sleep(0.02)

    def __exit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)


def _load(path: Path) -> list[Any]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path.replace(path.with_name(f"{path.stem}.corrupt-{stamp}.json"))
        return []


def append_events(events: list[dict[str, Any]], path: Path | None = None) -> None:
    """Append events to the audit trail. Never removes existing entries."""
    if not events:
        return
    path = path or config.AUDIT_PATH
    rows = [redact(to_jsonable_python(e)) for e in events]
    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    for r in rows:
        r.setdefault("time", stamp)
    with _thread_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _FileLock(path):
            existing = _load(path)
            existing.extend(rows)
            tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            for attempt in range(20):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:  # Windows: a reader may hold the file briefly
                    if attempt == 19:
                        raise
                    time.sleep(0.05)


def append_event(event: dict[str, Any], path: Path | None = None) -> None:
    append_events([event], path)
