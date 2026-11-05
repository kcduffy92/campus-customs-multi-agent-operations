"""Checks for the Problem 5 MCP tools and the approval queue.

Every write happens on a temporary copy of the ORIGINAL database, chosen with
CAMPUS_CUSTOMS_DB before the server is imported. The original and the working
copy are hashed before and after to prove neither changed. No model calls.

Run from the Homework 5 folder:  .venv/Scripts/python.exe tests/check_problem5_tools.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = ROOT / "data" / "campus_customs.db"
WORKING = ROOT / "data" / "campus_customs_new.db"
ORIGINAL_TABLES = ["cash_accounts", "desk", "inventory", "invoices", "leases", "payments", "pricing", "tickets", "vendors"]

TMP = Path(tempfile.mkdtemp(prefix="hw5_p5_"))
TEST_DB = TMP / "campus_customs_test.db"
shutil.copyfile(ORIGINAL, TEST_DB)
os.environ["CAMPUS_CUSTOMS_DB"] = str(TEST_DB)
sys.path.insert(0, str(ROOT / "mcp_server"))

from fastmcp import Client  # noqa: E402

from server import mcp  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(("PASS " if ok else "FAIL ") + label)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def db(sql: str, params=()):
    conn = sqlite3.connect(f"{TEST_DB.as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


async def call(client: Client, tool: str, **args):
    res = await client.call_tool(tool, args, raise_on_error=False)
    if res.is_error:
        return {"_error": " ".join(getattr(c, "text", "") for c in res.content)}
    return res.data if res.data is not None else res.structured_content


async def main() -> None:
    before = {p.name: sha256(p) for p in (ORIGINAL, WORKING)}

    async with Client(mcp) as c:
        names = {t.name for t in await c.list_tools()}
        new_tools = {"list_tickets", "get_ticket", "list_vendors", "get_cash_balance", "list_approval_requests",
                     "request_invoice_payment", "request_rent_payment", "request_purchase", "request_discount",
                     "update_ticket", "execute_approved_request", "reject_request"}
        check(new_tools | {"get_vendor_invoice_status", "check_rent_due", "check_stock_and_pricing"} == names,
              f"server exposes 3 original + {len(new_tools)} new tools")
        tags = {t.name: set((t.meta or {}).get("fastmcp", {}).get("tags", [])) for t in await c.list_tools()}
        check(tags["execute_approved_request"] == {"backend-only"} and tags["reject_request"] == {"backend-only"},
              "execute/reject tools are tagged backend-only")

        # --- read tools -------------------------------------------------------
        t = await call(c, "list_tickets")
        check(t["count"] == 3 and [x["id"] for x in t["tickets"]] == [101, 102, 103]
              and all(x["status"] == "open" for x in t["tickets"]), "list_tickets: 101-103, all open")
        t = await call(c, "get_ticket", ticket_id=103)
        check(t["found"] and t["ticket"]["sku"] == "CC-HOOD-NAVY" and t["ticket"]["qty"] == 20
              and t["approval_requests"] == [], "get_ticket 103: hoodie order, no requests yet")
        check((await call(c, "get_ticket", ticket_id=999)) == {"found": False, "ticket_id": 999},
              "get_ticket 999: found false")
        v = await call(c, "list_vendors")
        bulldog = v["vendors"][0]
        check(v["count"] == 3 and bulldog["name"] == "Bulldog Print Co" and bulldog["blocked_from_shipping"]
              and bulldog["open_invoice_total"] == 840.0 and not v["vendors"][1]["blocked_from_shipping"],
              "list_vendors: Bulldog blocked by $840 invoice, others not")
        cash = await call(c, "get_cash_balance")
        acct = cash["cash_accounts"][0]
        check(acct["balance"] == 3400.0 and acct["pending_outflow"] == 0 and acct["available_after_pending"] == 3400.0,
              "get_cash_balance: $3,400, nothing pending")
        check((await call(c, "list_approval_requests"))["count"] == 0, "list_approval_requests: empty before writes")
        check(db("SELECT name FROM sqlite_master WHERE name='approval_requests'") == [],
              "read tools did not create the approval table")

        # --- request creation and validation ----------------------------------
        r = await call(c, "request_invoice_payment", ticket_id=101, invoice_id=501, reason="Unblock tee reprint",
                       requested_by="accounting")
        req501 = r["request"]
        check(r["created"] and req501["amount"] == 840.0 and req501["status"] == "pending"
              and req501["kind"] == "invoice_payment" and len(req501["request_uid"]) == 36,
              "request_invoice_payment: pending $840 request with unique uid")
        check(r["cash_check"]["covers_all_pending_plus_this"], "invoice request reports cash coverage")
        dup = await call(c, "request_invoice_payment", ticket_id=101, invoice_id=501, reason="again",
                         requested_by="accounting")
        check(not dup["created"] and dup["duplicate"] and dup["request"]["id"] == req501["id"],
              "duplicate invoice request refused and points to the existing one")
        rent = await call(c, "request_rent_payment", ticket_id=102, lease_id=1, reason="Rent due 2026-09-02",
                          requested_by="accounting")
        check(rent["created"] and rent["request"]["amount"] == 2400.0
              and rent["request"]["details"]["due_date"] == "2026-09-02", "request_rent_payment: $2,400 for 2026-09-02")
        check(not (await call(c, "request_rent_payment", ticket_id=102, lease_id=1, reason="x",
                              requested_by="facilities"))["created"], "duplicate rent request refused")
        bad = await call(c, "request_discount", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=20,
                         unit_price=21.99, reason="too low", requested_by="accounting")
        check(not bad["created"] and "below unit cost" in bad["message"], "discount below unit cost refused")
        bad = await call(c, "request_discount", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=20,
                         unit_price=58, reason="not a discount", requested_by="accounting")
        check(not bad["created"], "discount at list price refused")
        # Simulation discount policy: orders of 10+ units, at most 10% off list, above cost, only stock on hand.
        bad = await call(c, "request_discount", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=8,
                         unit_price=49.3, reason="15% off", requested_by="accounting")
        check(not bad["created"] and "more than 10% off" in bad["message"] and "52.2" in bad["message"],
              "policy: more than 10% off list refused (floor $52.20)")
        bad = await call(c, "request_discount", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=8,
                         unit_price=22.0, reason="at cost", requested_by="accounting")
        check(not bad["created"] and "at or below unit cost" in bad["message"], "policy: price at unit cost refused")
        bad = await call(c, "request_discount", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=20,
                         unit_price=52.2, reason="all 20", requested_by="accounting")
        check(not bad["created"] and "Only 8 on hand" in bad["message"] and "12 short" in bad["message"],
              "policy: discount on more units than are on hand refused, shortfall reported")
        bad = await call(c, "request_discount", ticket_id=101, sku="CC-TEE-WHITE", size="S", quantity=1,
                         unit_price=25.2, reason="single tee", requested_by="accounting")
        check(not bad["created"] and "needs an order of 10 or more" in bad["message"],
              "policy: order under 10 units refused")
        disc = await call(c, "request_discount", ticket_id=103, sku="cc-hood-navy", size="m", quantity=8,
                          unit_price=52.2, reason="Student group bulk", requested_by="accounting")
        d = disc["request"]
        check(disc["created"] and d["amount"] == 417.6 and d["cash_effect"] == 0
              and d["details"]["discount_pct"] == 10.0 and d["details"]["margin_per_unit"] == 30.2,
              "request_discount: 8 x $52.20 = $417.60, 10% off, no cash effect")
        check(d["details"]["order_quantity"] == 20 and d["details"]["shortfall"] == 12
              and "assumption" in d["details"]["policy"], "discount records the order size, shortfall and policy note")
        pur = await call(c, "request_purchase", ticket_id=103, vendor_id=1, sku="CC-HOOD-NAVY", size="M",
                         quantity=12, reason="Cover shortage", requested_by="accounting")
        check(pur["created"] and pur["request"]["amount"] == 264.0 and pur["vendor_blocked_from_shipping"],
              "request_purchase: 12 x $22 = $264, flagged vendor blocked")
        err = await call(c, "request_invoice_payment", ticket_id=101, invoice_id=501, reason="x", requested_by="human")
        check("_error" in err, "requested_by must be an agent name")
        err = await call(c, "request_rent_payment", ticket_id=555, lease_id=1, reason="x", requested_by="accounting")
        check("_error" in err, "request for a missing ticket refused")
        err = await call(c, "request_rent_payment", ticket_id=102, lease_id=1, reason="  ", requested_by="accounting")
        check("_error" in err or not err.get("created"), "request without a reason refused")
        cash = (await call(c, "get_cash_balance"))["cash_accounts"][0]
        check(cash["pending_outflow"] == 3504.0 and cash["available_after_pending"] == -104.0 and cash["balance"] == 3400.0,
              "pending outflow $3,504 tracked; balance still $3,400 (nothing paid)")
        check(db("SELECT COUNT(*) FROM payments")[0][0] == 0, "no payment rows after requests")

        # --- update_ticket ----------------------------------------------------
        u = await call(c, "update_ticket", ticket_id=101, status="resolved", note="done", updated_by="boss")
        check(not u["updated"], "update_ticket refuses 'resolved' while requests are pending")
        u = await call(c, "update_ticket", ticket_id=101, status="awaiting_approval", note="Invoice 501 queued",
                       updated_by="boss")
        check(u["updated"] and u["ticket"]["status"] == "awaiting_approval"
              and u["ticket"]["notes"].startswith("Needs a tee in size S. | [2026-08-31 boss]"),
              "update_ticket: awaiting_approval, note appended, original note kept")
        check("_error" in await call(c, "update_ticket", ticket_id=101, status="closed", note="x", updated_by="boss"),
              "update_ticket rejects unknown status")

        # --- backend-only execution (human decisions) -------------------------
        err = await call(c, "execute_approved_request", request_id=req501["id"], approved_by="accounting")
        check("_error" in err, "an agent name cannot approve a request")
        err = await call(c, "execute_approved_request", request_id=req501["id"], approved_by="  ")
        check("_error" in err, "a blank approver is refused")
        blocked = await call(c, "execute_approved_request", request_id=pur["request"]["id"], approved_by="Kate Duffy")
        check(not blocked["executed"] and "open invoice" in blocked["message"],
              "purchase refused while vendor has an open invoice")
        ok = await call(c, "execute_approved_request", request_id=req501["id"], approved_by="Kate Duffy", note="test")
        check(ok["executed"] and ok["result"]["balance_after"] == 2560.0 and ok["request"]["status"] == "executed"
              and ok["request"]["decided_by"] == "Kate Duffy", "invoice executed once: $3,400 -> $2,560")
        check(db("SELECT status FROM invoices WHERE id=501")[0][0] == "paid"
              and db("SELECT kind, ref_id, amount, approved_by FROM payments")
              == [("invoice", 501, 840.0, "Kate Duffy")], "invoice marked paid; one payment row with approver")
        again = await call(c, "execute_approved_request", request_id=req501["id"], approved_by="Kate Duffy")
        check(not again["executed"] and "already executed" in again["message"]
              and db("SELECT COUNT(*) FROM payments")[0][0] == 1, "executing the same request twice is refused")
        check(not (await call(c, "request_invoice_payment", ticket_id=101, invoice_id=501, reason="x",
                              requested_by="accounting"))["created"], "paid invoice cannot be requested again")

        rent_ok = await call(c, "execute_approved_request", request_id=rent["request"]["id"], approved_by="Kate Duffy")
        check(rent_ok["executed"] and rent_ok["result"]["balance_after"] == 160.0
              and rent_ok["result"]["lease_next_due"] == "2026-10-02", "rent executed: $2,560 -> $160, next due 2026-10-02")

        # Cash can't go negative: $264 purchase against $160, now that the vendor is unblocked.
        snapshot = db("SELECT (SELECT balance FROM cash_accounts), (SELECT COUNT(*) FROM payments)")
        broke = await call(c, "execute_approved_request", request_id=pur["request"]["id"], approved_by="Kate Duffy")
        check(not broke["executed"] and "cannot go negative" in broke["message"], "purchase refused: would overdraw $160")
        check(db("SELECT (SELECT balance FROM cash_accounts), (SELECT COUNT(*) FROM payments)") == snapshot
              and db("SELECT status FROM approval_requests WHERE id=?", (pur["request"]["id"],))[0][0] == "pending",
              "refused execution is atomic: no cash, payment or status change")

        rej = await call(c, "reject_request", request_id=pur["request"]["id"], decided_by="Kate Duffy", note="no cash")
        check(rej["rejected"] and rej["request"]["status"] == "rejected", "reject_request: pending -> rejected")
        check(not (await call(c, "reject_request", request_id=pur["request"]["id"], decided_by="Kate Duffy"))["rejected"],
              "a rejected request cannot be decided again")
        disc_ok = await call(c, "execute_approved_request", request_id=d["id"], approved_by="Kate Duffy")
        check(disc_ok["executed"] and disc_ok["result"]["balance_after"] == 160.0
              and db("SELECT list_price FROM pricing WHERE sku='CC-HOOD-NAVY'")[0][0] == 58.0,
              "discount approval moves no cash and leaves pricing unchanged")
        check(db("SELECT balance FROM cash_accounts")[0][0] >= 0, "cash never negative")

    # --- schema safety --------------------------------------------------------
    tables = sorted(r[0] for r in db("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
    check(tables == sorted(ORIGINAL_TABLES + ["approval_requests"]), "test copy has the nine tables + approval_requests")
    conn = sqlite3.connect(TEST_DB)
    schema_before = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    conn.close()
    async with Client(mcp) as c:  # another write transaction re-runs the IF NOT EXISTS schema
        await call(c, "request_rent_payment", ticket_id=102, lease_id=1, reason="next month", requested_by="accounting")
    conn = sqlite3.connect(TEST_DB)
    check(conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == schema_before,
          "schema initialization is repeatable (no change on re-run)")
    conn.close()
    orig = sqlite3.connect(f"{ORIGINAL.as_uri()}?mode=ro", uri=True)
    check(sorted(r[0] for r in orig.execute("SELECT name FROM sqlite_master WHERE type='table'")) == ORIGINAL_TABLES,
          "original database still has exactly the nine tables")
    orig.close()

    # The server must refuse to run against the original database.
    os.environ["CAMPUS_CUSTOMS_DB"] = str(ORIGINAL)
    async with Client(mcp) as c:
        check("_error" in await call(c, "list_tickets"), "server refuses CAMPUS_CUSTOMS_DB = original database")
    os.environ["CAMPUS_CUSTOMS_DB"] = str(TEST_DB)

    after = {p.name: sha256(p) for p in (ORIGINAL, WORKING)}
    check(after == before, "original and working databases unchanged (SHA-256)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    passed = sum(ok for ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) else 1)
