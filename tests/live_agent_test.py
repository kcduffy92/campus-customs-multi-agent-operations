"""One limited live run of the agent team (gpt-6-luna through Portkey) on an isolated database.

1. Checks that Homework 5/.env provides PORTKEY_API_KEY. If not, it stops before doing anything.
2. Copies the ORIGINAL database to a temporary file and starts the campus-customs MCP
   server over HTTP on a free localhost port, pointed at that copy.
3. Runs the team on one ticket (default 102, the rent notice) and records what really
   happened: the status, delegations, MCP tool calls, approval requests, tokens and errors.
   Nothing is executed or paid: agents can only file approval requests.
4. Saves the record to docs/problem5_live_test.json and appends the real agent steps to
   output/audit_trail.json (labelled "problem5-live-test").

The original and working databases are hashed before and after.

This SPENDS PORTKEY TOKENS and REPLACES the Problem 5 evidence, so it needs explicit flags:
  --live              confirm you want real gpt-6-luna calls
  --overwrite-record  allow replacing an existing docs/problem5_live_test.json

Run from the Homework 5 folder:
  .venv/Scripts/python.exe tests/live_agent_test.py [ticket_id] --live [--overwrite-record]
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DBS = [ROOT / "data" / "campus_customs.db", ROOT / "data" / "campus_customs_new.db"]
RECORD = ROOT / "docs" / "problem5_live_test.json"
_ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
TICKET = int(_ARGS[0]) if _ARGS else 102


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    if "--live" not in sys.argv:
        print("STOPPED: this test makes real gpt-6-luna calls through Portkey (it costs tokens). "
              "Add --live to run it.")
        return 2
    if RECORD.exists() and "--overwrite-record" not in sys.argv:
        print(f"STOPPED: {RECORD.relative_to(ROOT)} already holds the Problem 5 evidence. "
              "Add --overwrite-record to replace it.")
        return 2
    sys.path.insert(0, str(ROOT / "backend"))
    import config  # loads Homework 5/.env only

    try:
        config.portkey_api_key()
    except RuntimeError as exc:
        print(f"STOPPED before any model call: {exc}")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="hw5_live_"))
    test_db = tmp / "campus_customs_live.db"
    shutil.copyfile(DBS[0], test_db)
    before = [sha256(p) for p in DBS]
    port = free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    env = {**os.environ, "CAMPUS_CUSTOMS_DB": str(test_db), "MCP_PORT": str(port)}
    server = subprocess.Popen([sys.executable, str(ROOT / "mcp_server" / "server.py"), "--http"], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        config.MCP_SERVER_URL = url
        config.RUN_LABEL = "problem5-live-test (isolated copy of the original database)"
        import agents

        started = time.monotonic()
        result = asyncio.run(agents.run_team(TICKET))
        seconds = round(time.monotonic() - started, 1)

        conn = sqlite3.connect(f"{test_db.as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        has_queue = conn.execute("SELECT 1 FROM sqlite_master WHERE name='approval_requests'").fetchone()
        requests = [dict(r) for r in conn.execute("SELECT id, ticket_id, kind, ref_id, amount, status, requested_by "
                                                  "FROM approval_requests")] if has_queue else []
        ticket = dict(conn.execute("SELECT id, status, notes FROM tickets WHERE id = ?", (TICKET,)).fetchone())
        cash = conn.execute("SELECT balance FROM cash_accounts WHERE name='checking'").fetchone()[0]
        payments = conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
        conn.close()

        trail = json.loads(config.AUDIT_PATH.read_text(encoding="utf-8"))
        steps = [e for e in trail if e.get("run_id") == result.run_id]
        record = {
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ticket_id": TICKET,
            "model": config.MODEL_NAME,
            "mcp_server": url,
            "database": "temporary copy of data/campus_customs.db (deleted after the run)",
            "seconds": seconds,
            "result": result.model_dump(),
            "agents_that_ran": sorted({e["agent"] for e in steps if e["action"] == "agent_started"}),
            "models_reported_by_responses": sorted({e["model"] for e in steps
                                                    if e["action"] == "model_response" and e.get("model")}),
            "mcp_tool_calls": [{"agent": e["agent"], "tool": e["tool"], "args": e["args"]}
                               for e in steps if e["action"] == "mcp_tool_call"],
            "audit_entries_appended": len(steps),
            "isolated_db_after_run": {"ticket": ticket, "approval_requests": requests,
                                      "checking_balance": cash, "payments_rows": payments},
            "original_and_working_db_unchanged": [sha256(p) for p in DBS] == before,
        }
        RECORD.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({k: record[k] for k in ("agents_that_ran", "models_reported_by_responses",
                                                 "audit_entries_appended", "original_and_working_db_unchanged")},
                         indent=2))
        print(f"status={result.status} usage={result.usage.model_dump()} error={result.error}")
        print(f"Saved {RECORD.relative_to(ROOT).as_posix()}")
        return 0 if result.status == "completed" else 1
    finally:
        server.terminate()
        server.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
