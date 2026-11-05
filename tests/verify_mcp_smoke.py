"""Check the Problem 4 smoke evidence against the real working database.

output/mcp_smoke.json holds the tool outputs that Claude Code got through the MCP
connection. This script recomputes every value with its own read-only SQL (it
does not import the server code) and compares field by field.

Expected file shape:
    {"tests": [{"prompt": "...", "tool": "check_rent_due",
                "arguments": {"lease_id": 1}, "output": {...}}, ...]}

Run from the Homework 5 folder:
    .venv/Scripts/python.exe tests/verify_mcp_smoke.py [path/to/mcp_smoke.json] [--record]

--record writes the per-test result ("matches_database", "checked_fields",
"mismatches") and the database SHA-256 hashes back into the file.

--original compares against the untouched original database instead: the state the Problem 4 smoke
tests were recorded from. Use it after the Problem 9 run has changed the working copy (it never writes).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKING_DB = ROOT / "data" / "campus_customs_new.db"
ORIGINAL_DB = ROOT / "data" / "campus_customs.db"
DEFAULT_SMOKE = ROOT / "output" / "mcp_smoke.json"
REQUIRED_TOOLS = {"get_vendor_invoice_status", "check_rent_due", "check_stock_and_pricing"}


def connect() -> sqlite3.Connection:
    db = ORIGINAL_DB if "--original" in sys.argv else WORKING_DB
    conn = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def today(conn) -> date:
    return date.fromisoformat(conn.execute("SELECT date_today FROM desk").fetchone()[0])


def expected_invoice(conn, a: dict) -> dict:
    row = conn.execute(
        "SELECT i.*, v.name AS vname, v.lead_days FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?",
        (a["invoice_id"],),
    ).fetchone()
    if row is None:
        return {"found": False}
    late = (today(conn) - date.fromisoformat(row["due_date"])).days
    n_open = conn.execute("SELECT COUNT(*) FROM invoices WHERE vendor_id = ? AND status = 'open'", (row["vendor_id"],)).fetchone()[0]
    return {
        "found": True,
        "today": today(conn).isoformat(),
        "invoice.id": row["id"],
        "invoice.amount": round(row["amount"], 2),
        "invoice.due_date": row["due_date"],
        "invoice.status": row["status"],
        "invoice.description": row["description"],
        "invoice.days_past_due": max(late, 0),
        "vendor.id": row["vendor_id"],
        "vendor.name": row["vname"],
        "vendor.lead_days": row["lead_days"],
        "vendor_blocked_from_shipping": n_open > 0,
    }


def expected_rent(conn, a: dict) -> dict:
    row = conn.execute("SELECT * FROM leases WHERE id = ?", (a["lease_id"],)).fetchone()
    if row is None:
        return {"found": False}
    exp = {
        "found": True,
        "today": today(conn).isoformat(),
        "lease.id": row["id"],
        "lease.landlord": row["landlord"],
        "lease.space_name": row["space_name"],
        "lease.monthly_rent": round(row["monthly_rent"], 2),
        "lease.next_due": row["next_due"],
        "lease.days_until_due": (date.fromisoformat(row["next_due"]) - today(conn)).days,
    }
    for i, acct in enumerate(conn.execute("SELECT * FROM cash_accounts ORDER BY name")):
        exp[f"cash_accounts.{i}.name"] = acct["name"]
        exp[f"cash_accounts.{i}.balance"] = round(acct["balance"], 2)
        exp[f"cash_accounts.{i}.covers_rent"] = acct["balance"] >= row["monthly_rent"]
        exp[f"cash_accounts.{i}.balance_after_rent"] = round(acct["balance"] - row["monthly_rent"], 2)
    return exp


def expected_stock(conn, a: dict) -> dict:
    sku, size = a["sku"].strip().upper(), a["size"].strip().upper()
    row = conn.execute(
        "SELECT i.*, p.unit_cost, p.list_price FROM inventory i LEFT JOIN pricing p ON p.sku = i.sku WHERE i.sku = ? AND i.size = ?",
        (sku, size),
    ).fetchone()
    if row is None:
        return {"found": False}
    exp = {
        "found": True,
        "sku": row["sku"],
        "name": row["name"],
        "size": row["size"],
        "qty_on_hand": row["qty"],
        "location": row["location"],
        "unit_cost": round(row["unit_cost"], 2),
        "list_price": round(row["list_price"], 2),
    }
    q = a.get("requested_quantity")
    if q is not None:
        exp["order.requested_quantity"] = q
        exp["order.shortage"] = max(q - row["qty"], 0)
        exp["order.can_fill_from_stock"] = row["qty"] >= q
        exp["order.total_at_list_price"] = round(q * row["list_price"], 2)
        exp["order.total_at_unit_cost"] = round(q * row["unit_cost"], 2)
    return exp


EXPECTED = {
    "get_vendor_invoice_status": expected_invoice,
    "check_rent_due": expected_rent,
    "check_stock_and_pricing": expected_stock,
}


def get_path(obj, dotted: str):
    for part in dotted.split("."):
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    args = [a for a in sys.argv[1:] if a not in ("--record", "--original")]
    record = "--record" in sys.argv
    smoke_path = Path(args[0]) if args else DEFAULT_SMOKE
    if record and sha256(ORIGINAL_DB) != sha256(WORKING_DB):
        # The Problem 4 evidence was recorded while both databases were identical. Once a later problem has
        # changed the working copy, --record would write misleading mismatches into the evidence file.
        print("REFUSED: --record only runs while the original and working databases are identical. They differ now "
              "(the working copy holds the Problem 9 results), so output/mcp_smoke.json was left unchanged. "
              "Use --original to check the evidence without writing.")
        return 2
    if not smoke_path.exists():
        print(f"{smoke_path} does not exist yet. Run the three tool tests in Claude Code first.")
        return 1

    smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    tests = smoke.get("tests", [])
    ok_all = True
    with connect() as conn:
        for t in tests:
            missing = [k for k in ("prompt", "tool", "arguments", "output") if not t.get(k) and t.get(k) != {}]
            if missing or t["tool"] not in EXPECTED:
                print(f"FAIL entry {t.get('tool')}: missing {missing or 'known tool name'}")
                t.update(matches_database=False, mismatches=[f"missing {missing}"])
                ok_all = False
                continue
            exp = EXPECTED[t["tool"]](conn, t["arguments"])
            mismatches = []
            for field, want in exp.items():
                try:
                    got = get_path(t["output"], field)
                except (KeyError, IndexError, TypeError):
                    got = "<missing>"
                if got != want:
                    mismatches.append(f"{field}: output={got!r} database={want!r}")
            t.update(matches_database=not mismatches, checked_fields=len(exp), mismatches=mismatches)
            ok_all &= not mismatches
            print(("PASS " if not mismatches else "FAIL ") + f"{t['tool']} {t['arguments']} ({len(exp)} fields)")
            for m in mismatches:
                print("     " + m)

    covered = {t.get("tool") for t in tests}
    if not REQUIRED_TOOLS <= covered:
        print(f"FAIL missing tests for: {sorted(REQUIRED_TOOLS - covered)}")
        ok_all = False

    hashes = {"campus_customs.db": sha256(ORIGINAL_DB), "campus_customs_new.db": sha256(WORKING_DB)}
    same = hashes["campus_customs.db"] == hashes["campus_customs_new.db"]
    print(("PASS " if same else "NOTE ") + "original and working copy " + ("are identical" if same else "differ"))

    if record:
        smoke["verification"] = {
            "script": "tests/verify_mcp_smoke.py",
            "all_outputs_match_database": ok_all,
            "database_sha256": hashes,
            "databases_identical": same,
        }
        smoke_path.write_text(json.dumps(smoke, indent=2) + "\n", encoding="utf-8")
        print(f"Recorded results in {smoke_path}")
    print("\nALL MATCH" if ok_all else "\nMISMATCHES FOUND")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
