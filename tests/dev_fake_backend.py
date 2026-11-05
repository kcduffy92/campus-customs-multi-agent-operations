"""Development backend for testing the React desk (Problem 8) without model calls or Portkey tokens.

It runs the real API (backend/main.py) and the real MCP server, but on a TEMPORARY copy of the original
database with a temporary audit trail. agents.run_team is replaced by scripted runs that write the same
audit events the real agents write and make real MCP tool calls (so approval requests, cash and tickets
are real on the copy). Every run is labelled "SCRIPTED TEST RUN" in the dashboard.

Ticket 103's script deliberately differs from the Problem 6 plan (Crash hands the discount to Spyro
instead of Mario doing it), so the "not in the plan" and "planned, not used" states can be checked.

    .venv/Scripts/python.exe tests/dev_fake_backend.py            # API on http://127.0.0.1:8000
    .venv/Scripts/python.exe tests/dev_fake_backend.py --fail 101 # make ticket 101's run fail midway

The original and working databases in data/ are never opened for writing.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = ROOT / "data" / "campus_customs.db"
TMP = Path(tempfile.mkdtemp(prefix="hw5_fake_backend_"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--port", type=int, default=8000)
parser.add_argument("--step", type=float, default=float(os.getenv("FAKE_STEP_SECONDS", "0.8")), help="seconds between events")
parser.add_argument("--fail", type=int, action="append", default=[], help="ticket id whose run should fail")
ARGS = parser.parse_args()

shutil.copyfile(ORIGINAL, TMP / "fake_copy.db")
os.environ.update({
    "CAMPUS_CUSTOMS_DB": str(TMP / "fake_copy.db"),
    "AUDIT_TRAIL_PATH": str(TMP / "audit_trail.json"),
    "MCP_SERVER_URL": f"http://127.0.0.1:{free_port()}/mcp",
    "AGENT_RUN_LABEL": "SCRIPTED TEST RUN (no model calls)",
})
os.environ.setdefault("PORTKEY_API_KEY", "not-used-by-scripted-runs")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn  # noqa: E402
from fastmcp import Client  # noqa: E402

import agents  # noqa: E402
import audit  # noqa: E402
import config  # noqa: E402
import main  # noqa: E402
from models import AgentReport, TeamRunResult, UsageSummary  # noqa: E402


class Script:
    """Writes audit events in the real agents' format, pausing between steps so the board can animate."""

    def __init__(self, ticket_id: int, run_id: str) -> None:
        self.ticket_id, self.run_id = ticket_id, run_id

    async def ev(self, chain: list[str], action: str, pause: bool = True, **fields) -> None:
        audit.append_event({"run_id": self.run_id, "ticket_id": self.ticket_id, "agent": chain[-1],
                            "parent_agent": chain[-2] if len(chain) > 1 else None, "depth": len(chain) - 1,
                            "chain": chain, "action": action, **fields})
        if pause:
            await asyncio.sleep(ARGS.step)

    async def tool(self, chain: list[str], name: str, **args) -> dict:
        if name.startswith("request_"):
            args.update(ticket_id=self.ticket_id, requested_by=chain[-1])
        if name == "update_ticket":
            args.update(ticket_id=self.ticket_id, updated_by=chain[-1])
        async with Client(config.MCP_SERVER_URL) as c:
            res = await c.call_tool(name, args, raise_on_error=False)
        data = res.data if res.data is not None else res.structured_content
        await self.ev(chain, "mcp_tool_call", tool=name, args=args, result=audit.preview(data))
        return data or {}

    async def delegate(self, chain: list[str], to: str, task: str) -> list[str]:
        await self.ev(chain, "delegation_started", delegation={"to_agent": to, "task": task, "number": 1})
        sub = chain + [to]
        await self.ev(sub, "agent_started", prompt=task)
        return sub

    async def finish_delegation(self, chain: list[str], to: str, task: str) -> None:
        await self.ev(chain, "delegation_finished", delegation={"to_agent": to, "task": task})

    async def done(self, chain: list[str], summary: str, **fields) -> None:
        await self.ev(chain, "agent_finished", summary=summary, open_issues=fields.pop("open_issues", []), **fields)


async def script_101(s: Script) -> str:
    boss = ["boss"]
    await s.tool(boss, "get_ticket", ticket_id=101)
    t1 = "Check stock for CC-TEE-WHITE size S and whether invoice 501 blocks a reprint"
    inv = await s.delegate(boss, "inventory", t1)
    stock = await s.tool(inv, "check_stock_and_pricing", sku="CC-TEE-WHITE", size="S", requested_quantity=1)
    invoice = await s.tool(inv, "get_vendor_invoice_status", invoice_id=501)
    if 101 in ARGS.fail:
        await s.ev(inv, "delegation_refused", delegation={"to_agent": "accounting", "task": "pay invoice"},
                   result="Scripted failure for testing the error state.")
        raise RuntimeError("Scripted test failure on ticket 101")
    t2 = "Invoice 501 blocks the reprint; assess paying it and file an approval request"
    acc = await s.delegate(inv, "accounting", t2)
    await s.tool(acc, "get_cash_balance")
    req = await s.tool(acc, "request_invoice_payment", invoice_id=501, reason="Overdue invoice blocks the size S reprint")
    rid = (req.get("request") or {}).get("id")
    await s.done(acc, f"Filed request #{rid} to pay invoice 501 (${(invoice.get('invoice') or {}).get('amount', 0):,.2f}). Nothing is paid until a person approves.",
                 approval_request_ids=[rid] if rid else [], recommended_ticket_status="awaiting_approval")
    await s.finish_delegation(inv, "accounting", t2)
    qty = stock.get("qty_on_hand")
    await s.done(inv, f"Size S tee has {qty} on hand: a shortage. Bulldog Print Co won't reprint while invoice 501 is overdue.")
    await s.finish_delegation(boss, "inventory", t1)
    t3 = "Draft an honest reply to the customer about the size S tee"
    cs = await s.delegate(boss, "customer_service", t3)
    await s.tool(cs, "get_ticket", ticket_id=101)
    await s.done(cs, "Drafted a reply: the tee is out of stock and a reprint depends on an approval.",
                 customer_reply="Hi Tauhid, the size S Bulldog tee is out of stock right now. We're working on a reprint "
                                "and will confirm a date once it's scheduled.")
    await s.finish_delegation(boss, "customer_service", t3)
    await s.tool(boss, "update_ticket", status="awaiting_approval", note="Scripted test run: invoice payment request filed.")
    return "Inventory found the shortage; Accounting filed the invoice payment request; Customer Service drafted a reply."


async def script_102(s: Script) -> str:
    boss = ["boss"]
    await s.tool(boss, "get_ticket", ticket_id=102)
    t1 = "Check the rent notice against lease 1"
    fac = await s.delegate(boss, "facilities", t1)
    await s.tool(fac, "get_ticket", ticket_id=102)
    rent = await s.tool(fac, "check_rent_due", lease_id=1)
    t2 = "Rent confirmed; verify cash and queue the payment for approval"
    acc = await s.delegate(fac, "accounting", t2)
    await s.tool(acc, "get_cash_balance")
    await s.tool(acc, "list_approval_requests", ticket_id=102)
    req = await s.tool(acc, "request_rent_payment", lease_id=1, reason="Rent due 2026-09-02 per lease 1")
    rid = (req.get("request") or {}).get("id")
    await s.done(acc, f"Queued rent request #{rid}; checking covers it.", approval_request_ids=[rid] if rid else [])
    await s.finish_delegation(fac, "accounting", t2)
    await s.done(fac, f"The notice matches lease 1: rent ${(rent.get('lease') or {}).get('monthly_rent', 0):,.2f}, due {(rent.get('lease') or {}).get('next_due')}.")
    await s.finish_delegation(boss, "facilities", t1)
    await s.tool(boss, "update_ticket", status="awaiting_approval", note="Scripted test run: rent payment request filed.")
    return "Facilities confirmed the lease; Accounting queued the rent payment for approval."


async def script_103(s: Script) -> str:
    boss = ["boss"]
    await s.tool(boss, "get_ticket", ticket_id=103)
    t1 = "Check stock of CC-HOOD-NAVY size M for 20 and price the order"
    inv = await s.delegate(boss, "inventory", t1)
    await s.tool(inv, "check_stock_and_pricing", sku="CC-HOOD-NAVY", size="M", requested_quantity=20)
    t2 = "Only 8 in stock; propose a discount on those 8, never below cost"  # not in the Problem 6 plan
    acc = await s.delegate(inv, "accounting", t2)
    req = await s.tool(acc, "request_discount", sku="CC-HOOD-NAVY", size="M", quantity=8, unit_price=52.2,
                       reason="Bulk student order; 8 available now")
    rid = (req.get("request") or {}).get("id")
    await s.done(acc, f"Filed discount request #{rid}: 8 hoodies at $52.20, 10% off list (cost $22.00).", approval_request_ids=[rid] if rid else [])
    await s.finish_delegation(inv, "accounting", t2)
    await s.done(inv, "Only 8 hoodies in size M are on hand, 12 short of the 20 requested.")
    await s.finish_delegation(boss, "inventory", t1)
    t3 = "Draft a reply explaining what we can actually offer"
    cs = await s.delegate(boss, "customer_service", t3)
    await s.done(cs, "Drafted a reply offering the 8 in stock, with the discount still subject to approval.",
                 customer_reply="Hi Yale AI Club, we have 8 navy hoodies in size M now. A bulk price is pending approval; "
                                "we can't promise the other 12 yet.")
    await s.finish_delegation(boss, "customer_service", t3)
    await s.tool(boss, "update_ticket", status="awaiting_approval", note="Scripted test run: discount request filed.")
    return "Inventory found 8 of 20; Accounting filed a discount request; Customer Service drafted a reply."


SCRIPTS = {101: script_101, 102: script_102, 103: script_103}


async def scripted_run_team(ticket_id: int, run_id: str | None = None) -> TeamRunResult:
    s = Script(ticket_id, run_id or "scripted")
    await s.ev(["boss"], "run_started", model=config.MODEL_NAME, mcp_server=config.MCP_SERVER_URL, run_label=config.RUN_LABEL)
    await s.ev(["boss"], "agent_started", prompt=f"Work desk ticket {ticket_id}.")
    status, error, summary = "completed", None, ""
    try:
        summary = await SCRIPTS[ticket_id](s)
        await s.done(["boss"], summary, recommended_ticket_status="awaiting_approval")
    except Exception as exc:  # scripted failure path
        status, error = "error", f"{type(exc).__name__}: {exc}"
    await s.ev(["boss"], "run_finished", pause=False, status=status, error=error, usage=UsageSummary().model_dump())
    report = AgentReport(agent="boss", summary=summary or "Run failed.") if status == "completed" else None
    return TeamRunResult(run_id=s.run_id, ticket_id=ticket_id, model=config.MODEL_NAME, status=status,
                         final_report=report, usage=UsageSummary(), error=error)


agents.run_team = scripted_run_team

if __name__ == "__main__":
    print(f"Scripted dev backend on http://127.0.0.1:{ARGS.port} (temporary database {TMP / 'fake_copy.db'})", flush=True)
    uvicorn.run(main.app, host="127.0.0.1", port=ARGS.port, log_level="warning")
