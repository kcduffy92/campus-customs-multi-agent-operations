"""Lightweight checks for the Problem 3 MCP tools.

Calls each tool through FastMCP's in-memory client against a temporary copy of the
original database (no network, no model calls), so the Problem 2 values hold whatever
state the working copy is in (for example after the Problem 9 run). Also confirms that
neither database file in data/ changed, and that the read-only tools wrote nothing.

Run from the Homework 5 folder:  .venv/Scripts/python.exe tests/check_mcp_tools.py
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))
TMP = Path(tempfile.mkdtemp(prefix="hw5_mcp_tools_"))
TEST_DB = TMP / "original_copy.db"
shutil.copyfile(ROOT / "data" / "campus_customs.db", TEST_DB)
os.environ["CAMPUS_CUSTOMS_DB"] = str(TEST_DB)  # the server reads this on every call

from fastmcp import Client  # noqa: E402

from server import mcp  # noqa: E402

DBS = [ROOT / "data" / "campus_customs.db", ROOT / "data" / "campus_customs_new.db"]
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(("PASS " if ok else "FAIL ") + label)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def call(client: Client, tool: str, **args):
    res = await client.call_tool(tool, args, raise_on_error=False)
    return res


async def main() -> None:
    before = {p: sha256(p) for p in DBS}
    copy_before = sha256(TEST_DB)

    async with Client(mcp) as client:
        names = sorted(t.name for t in await client.list_tools())
        # Problem 5 added more tools; the three Problem 3 tools must still be exposed.
        original = {"check_rent_due", "check_stock_and_pricing", "get_vendor_invoice_status"}
        check(original <= set(names), f"server still exposes the three Problem 3 tools: {sorted(original)}")

        # Ticket 101: invoice 501 blocks the tee reprint.
        r = (await call(client, "get_vendor_invoice_status", invoice_id=501)).data
        inv, ven = r["invoice"], r["vendor"]
        check(r["found"] and r["today"] == "2026-08-31", "101: invoice 501 found, today is desk.date_today 2026-08-31")
        check(inv["amount"] == 840.0 and inv["status"] == "open" and inv["due_date"] == "2026-08-28",
              "101: invoice 501 is $840.00, open, due 2026-08-28")
        check(inv["days_past_due"] == 3 and inv["is_overdue"], "101: invoice 501 is 3 days past due")
        check(ven["name"] == "Bulldog Print Co" and ven["lead_days"] == 5, "101: vendor Bulldog Print Co, 5 lead days")
        check(r["vendor_blocked_from_shipping"], "101: vendor blocked from shipping while invoice is open")

        r = (await call(client, "check_stock_and_pricing", sku="CC-TEE-WHITE", size="S", requested_quantity=1)).data
        check(r["qty_on_hand"] == 0 and not r["in_stock"] and r["order"]["shortage"] == 1,
              "101: CC-TEE-WHITE size S has 0 on hand, shortage 1")
        check(r["list_price"] == 28.0 and r["unit_cost"] == 8.0, "101: tee list $28.00, cost $8.00")

        # Ticket 102: rent vs. cash.
        r = (await call(client, "check_rent_due", lease_id=1)).data
        lease, acct = r["lease"], r["cash_accounts"][0]
        check(lease["monthly_rent"] == 2400.0 and lease["next_due"] == "2026-09-02" and lease["days_until_due"] == 2,
              "102: rent $2,400.00 due 2026-09-02, 2 days away")
        check(lease["landlord"] == "Elm City Properties", "102: landlord matches ticket requester")
        check(acct["name"] == "checking" and acct["balance"] == 3400.0 and acct["covers_rent"]
              and acct["balance_after_rent"] == 1000.0, "102: checking $3,400.00 covers rent, $1,000.00 after")

        # Ticket 103: 20 hoodies in M.
        r = (await call(client, "check_stock_and_pricing", sku="CC-HOOD-NAVY", size="M", requested_quantity=20)).data
        o = r["order"]
        check(r["qty_on_hand"] == 8 and r["location"] == "Aisle A", "103: CC-HOOD-NAVY size M has 8 in Aisle A")
        check(not o["can_fill_from_stock"] and o["shortage"] == 12, "103: 20 requested, 12 short")
        check(o["total_at_list_price"] == 1160.0 and o["total_at_unit_cost"] == 440.0,
              "103: totals $1,160.00 at list, $440.00 at cost")
        r = (await call(client, "check_stock_and_pricing", sku=" cc-hood-navy ", size="m")).data
        check(r["found"] and "order" not in r, "103: lookup is case/space tolerant; no order block without a quantity")

        # Missing records and invalid input.
        r = (await call(client, "get_vendor_invoice_status", invoice_id=999)).data
        check(r == {"found": False, "invoice_id": 999, "message": "No invoice with id 999"}, "missing invoice -> found False")
        r = (await call(client, "check_rent_due", lease_id=42)).data
        check(r["found"] is False, "missing lease -> found False")
        r = (await call(client, "check_stock_and_pricing", sku="CC-TEE-WHITE", size="XXL")).data
        check(r["found"] is False and r["sizes_on_record"] == ["L", "M", "S", "XL"], "unknown size -> found False, real sizes listed")
        r = (await call(client, "check_stock_and_pricing", sku="NOPE", size="M")).data
        check(r["found"] is False and r["sizes_on_record"] == [], "unknown sku -> found False")
        for args, label in [
            ({"sku": "CC-HOOD-NAVY", "size": "M", "requested_quantity": 0}, "quantity 0"),
            ({"sku": "CC-HOOD-NAVY", "size": "M", "requested_quantity": -5}, "negative quantity"),
            ({"sku": "", "size": "M"}, "empty sku"),
            ({"invoice_id": "abc"}, "non-integer invoice_id"),
        ]:
            tool = "get_vendor_invoice_status" if "invoice_id" in args else "check_stock_and_pricing"
            check((await call(client, tool, **args)).is_error, f"invalid input rejected: {label}")

    # The tools' connection must refuse writes (read-only mode), not just avoid them.
    import sqlite3
    from server import _read_only_connection

    with _read_only_connection() as conn:
        try:
            conn.execute("UPDATE cash_accounts SET balance = balance WHERE 0")
            check(False, "read-only connection refuses writes")
        except sqlite3.OperationalError as e:
            check("readonly" in str(e), f"read-only connection refuses writes ({e})")

    after = {p: sha256(p) for p in DBS}
    check(before == after, "neither database file in data/ changed")
    check(sha256(TEST_DB) == copy_before == sha256(DBS[0]), "the read-only tools wrote nothing (copy still equals the original)")
    shutil.rmtree(TMP, ignore_errors=True)

    failed = [label for ok, label in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
