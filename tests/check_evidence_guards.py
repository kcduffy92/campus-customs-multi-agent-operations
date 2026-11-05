"""Checks that the evidence scripts cannot overwrite the verified Problem 9 / Problem 4 results by accident.

Everything runs on a temporary copy of the project's evidence; the real files are never written.

- build_problem9_outputs.py, run on the unchanged copy: succeeds and every evidence file is byte-identical.
- After a new database_reset in the audit trail: it refuses and writes nothing.
- After an extra payment in the working database: it refuses and writes nothing.
- verify_mcp_smoke.py --record while the databases differ: refuses and leaves mcp_smoke.json unchanged.

Run: .venv/Scripts/python.exe tests/check_evidence_guards.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ["output/desk_tickets.html", "output/resolved_tickets.json", "output/resolved_board.html", "output/harness.md"]
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_copy() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="hw5_guards_"))
    for rel in ["tests/build_problem9_outputs.py", "tests/verify_mcp_smoke.py", "output/audit_trail.json",
                "output/mcp_smoke.json", "data/campus_customs.db", "data/campus_customs_new.db", *EVIDENCE]:
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp / rel)
    shutil.copytree(ROOT / "docs" / "problem9_screenshots", tmp / "docs" / "problem9_screenshots")
    return tmp


def run(tmp: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(tmp / "tests" / script), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=tmp)


def snapshot(tmp: Path) -> dict[str, str]:
    return {rel: sha(tmp / rel) for rel in EVIDENCE}


def main() -> int:
    real_before = {rel: sha(ROOT / rel) for rel in [*EVIDENCE, "output/mcp_smoke.json", "output/audit_trail.json"]}

    tmp = make_copy()
    try:
        before = snapshot(tmp)
        r = run(tmp, "build_problem9_outputs.py")
        check(r.returncode == 0 and snapshot(tmp) == before,
              "unchanged simulation: generator succeeds and the evidence is byte-identical")

        trail_path = tmp / "output" / "audit_trail.json"
        trail = json.loads(trail_path.read_text(encoding="utf-8"))
        trail.append({"run_id": None, "ticket_id": None, "agent": None, "action": "database_reset",
                      "reset_by": "someone else", "time": "2026-12-01T00:00:00+00:00"})
        trail_path.write_text(json.dumps(trail), encoding="utf-8")
        r = run(tmp, "build_problem9_outputs.py")
        check(r.returncode != 0 and snapshot(tmp) == before, "after a new reset: generator refuses and writes nothing")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = make_copy()
    try:
        before = snapshot(tmp)
        conn = sqlite3.connect(tmp / "data" / "campus_customs_new.db")
        conn.execute("INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
                     "VALUES ('purchase', 99, 1.0, 'checking', '2026-08-31', 'someone else')")
        conn.execute("UPDATE cash_accounts SET balance = balance - 1 WHERE name = 'checking'")
        conn.commit()
        conn.close()
        r = run(tmp, "build_problem9_outputs.py")
        check(r.returncode != 0 and snapshot(tmp) == before, "after an extra payment: generator refuses and writes nothing")

        smoke = tmp / "output" / "mcp_smoke.json"
        s0 = sha(smoke)
        r = run(tmp, "verify_mcp_smoke.py", "--record")
        check("REFUSED" in r.stdout and sha(smoke) == s0, "verify_mcp_smoke --record refuses while the databases differ")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    real_after = {rel: sha(ROOT / rel) for rel in real_before}
    check(real_after == real_before, "the project's real evidence files were not touched")

    failed = [label for ok, label in results if not ok]
    for ok, label in results:
        print(("PASS " if ok else "FAIL ") + label)
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
