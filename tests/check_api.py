"""Deterministic checks for backend/main.py (Problem 7). No model calls, no Portkey tokens.

The API runs in-process with FastAPI's TestClient. Its lifespan starts the real MCP server
(backend/mcp_supervised.py) on a free port, pointed at a temporary copy of the original
database, with a temporary audit trail. agents.run_team is replaced by a scripted fake that
writes realistic audit events and files one real approval request through the MCP tools.

Run: .venv/Scripts/python.exe tests/check_api.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = ROOT / "data" / "campus_customs.db"
WORKING = ROOT / "data" / "campus_customs_new.db"
TMP = Path(tempfile.mkdtemp(prefix="hw5_api_"))
TEST_DB = TMP / "api_copy.db"
TRAIL = TMP / "audit_trail.json"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Environment must be set before backend/config.py is imported (dotenv never overrides it).
shutil.copyfile(ORIGINAL, TEST_DB)
MCP_PORT = free_port()
os.environ.update({
    "CAMPUS_CUSTOMS_DB": str(TEST_DB),
    "AUDIT_TRAIL_PATH": str(TRAIL),
    "MCP_SERVER_URL": f"http://127.0.0.1:{MCP_PORT}/mcp",
    "AGENT_RUN_LABEL": "api-test (fake run, no model calls)",
    # The run is faked, so no model is ever called. A placeholder key lets POST /run pass its key check in a
    # clean checkout with no .env, and keeps any real key out of this test process (dotenv never overrides it).
    "PORTKEY_API_KEY": "placeholder-key-for-mocked-tests",
})
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from fastmcp import Client  # noqa: E402

import agents  # noqa: E402
import audit  # noqa: E402
import main  # noqa: E402
from models import AgentReport, TeamRunResult, UsageSummary  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))


def db(sql: str, *params):
    conn = sqlite3.connect(f"{TEST_DB.as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


async def mcp(tool: str, **args):
    async with Client(main.config.MCP_SERVER_URL) as c:
        return (await c.call_tool(tool, args)).data


# ---------------------------------------------------------------------------
# Fake agent run: scripted audit events plus one real request_rent_payment call
# ---------------------------------------------------------------------------

RELEASE = threading.Event()
FAKE_CALLS: list[int] = []


async def fake_run_team(ticket_id: int, run_id: str | None = None) -> TeamRunResult:
    FAKE_CALLS.append(ticket_id)
    base = {"run_id": run_id, "ticket_id": ticket_id}

    def ev(agent, action, chain, **f):
        audit.append_event({**base, "agent": agent, "parent_agent": chain[-2] if len(chain) > 1 else None,
                            "depth": len(chain) - 1, "chain": list(chain), "action": action, **f})

    ev("boss", "run_started", ["boss"], model="gpt-6-luna", mcp_server=main.config.MCP_SERVER_URL)
    ev("boss", "agent_started", ["boss"])
    ev("boss", "mcp_tool_call", ["boss"], tool="get_ticket", args={"ticket_id": ticket_id}, result='{"found": true}')
    ev("boss", "delegation_started", ["boss"], delegation="{'to_agent': 'facilities', 'task': 'check lease', 'number': 1}")
    ev("facilities", "agent_started", ["boss", "facilities"])
    ev("facilities", "delegation_started", ["boss", "facilities"],
       delegation="{'to_agent': 'accounting', 'task': 'queue rent', 'number': 2}")
    ev("accounting", "agent_started", ["boss", "facilities", "accounting"])
    created = await mcp("request_rent_payment", ticket_id=ticket_id, lease_id=1, reason="Rent due 2026-09-02",
                        requested_by="accounting")
    ev("accounting", "mcp_tool_call", ["boss", "facilities", "accounting"], tool="request_rent_payment",
       args={"lease_id": 1}, result=audit.preview(created))
    ev("accounting", "agent_finished", ["boss", "facilities", "accounting"], summary="Queued $2,400 rent for approval.",
       recommended_ticket_status="awaiting_approval", approval_request_ids=[created["request"]["id"]], open_issues=[])
    ev("facilities", "delegation_finished", ["boss", "facilities"], delegation="{'to_agent': 'accounting', 'task': 'queue rent'}")
    ev("facilities", "agent_finished", ["boss", "facilities"], summary="Notice matches lease 1.")
    ev("boss", "delegation_finished", ["boss"], delegation="{'to_agent': 'facilities', 'task': 'check lease'}")
    while not RELEASE.is_set():  # the test holds the run open to try duplicate runs and resets
        await asyncio.sleep(0.05)
    ev("boss", "agent_finished", ["boss"], summary="Rent request filed; waiting for a human.")
    ev("boss", "run_finished", ["boss"], status="completed", error=None)
    report = AgentReport(agent="boss", summary="Rent request filed; waiting for a human.")
    return TeamRunResult(run_id=run_id, ticket_id=ticket_id, model="gpt-6-luna", status="completed",
                         final_report=report, usage=UsageSummary())


agents.run_team = fake_run_team


def wait_for(predicate, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def main_checks(c: TestClient) -> None:
    # --- health, index, tickets, cash ---
    h = c.get("/health")
    check(h.status_code == 200 and h.json()["model"] == "gpt-6-luna" and h.json()["mcp_tools"] == 15,
          "GET /health: 200, model gpt-6-luna, MCP server with 15 tools")
    check(h.json()["database"] == TEST_DB.name, "backend uses the temporary database copy")
    idx = c.get("/").json()
    check(len(idx["routes"]) == len(main.ROUTES) and all(r["purpose"] for r in idx["routes"]), "GET / lists every route")
    t = c.get("/tickets").json()["tickets"]
    check([x["id"] for x in t] == [101, 102, 103], "GET /tickets returns tickets 101, 102, 103")
    check(all(x["open_or_resolved"] == "open" and not x["is_resolved"] and x["stage"] == "not_started" for x in t),
          "all three start open / not_started")
    check(c.get("/tickets/102").json()["notes"] == "Email: shop rent due in 2 days.", "GET /tickets/102 includes notes")
    check(c.get("/tickets/999").status_code == 404, "GET /tickets/999 -> 404")
    cash = c.get("/cash").json()
    check(cash["balance"] == 3400.0 and cash["pending_outflow"] == 0 and cash["as_of"] == "2026-08-31",
          "GET /cash: checking $3,400.00, nothing pending")

    # --- runs ---
    check(c.post("/tickets/999/run").status_code == 404, "POST /tickets/999/run -> 404")
    cursor = c.get("/events").json()["next_cursor"]
    r = c.post("/tickets/102/run")
    run_id = r.json()["run_id"]
    check(r.status_code == 202 and r.json()["status"] == "running", "POST /tickets/102/run -> 202 running")
    check(wait_for(lambda: c.get(f"/events?run_id={run_id}").json()["events"]), "run writes events while running")
    dup = c.post("/tickets/101/run")
    check(dup.status_code == 409 and "active" in dup.json()["detail"], "a second run (any ticket) -> 409 while one is active")
    check(c.post("/tickets/102/run").status_code == 409, "the same ticket again -> 409")
    rs = c.post("/reset", json={"confirm": "RESET"})
    check(rs.status_code == 409, "POST /reset during an active run -> 409")
    check(c.get(f"/runs/{run_id}").json()["status"] == "running", "GET /runs/{id}: running")
    check(c.get("/tickets/102").json()["stage"] == "agents_working", "ticket 102 stage: agents_working")
    RELEASE.set()
    check(wait_for(lambda: c.get(f"/runs/{run_id}").json()["status"] == "completed"), "GET /runs/{id}: completed")
    run = c.get(f"/runs/{run_id}").json()
    check(run["result"]["final_report"]["summary"].startswith("Rent request filed"), "run result has the final report")
    check(c.get("/runs").json()["active_run"] is None, "GET /runs: no active run after it finishes")
    check(FAKE_CALLS == [102], "only one run actually started")
    check(c.get("/runs/nope").status_code == 404, "GET /runs/unknown -> 404")

    # --- events ---
    evs = c.get(f"/events?since={cursor}").json()
    kinds = [e["kind"] for e in evs["events"]]
    for k in ("run_started", "agent_active", "tool_used", "delegation_started", "approval_requested",
              "agent_finished", "delegation_finished", "run_finished"):
        check(k in kinds, f"GET /events reports '{k}'")
    d = [e for e in evs["events"] if e["kind"] == "delegation_started"]
    check([(e["character"], e["to_character"]) for e in d] == [("mario", "ryu"), ("ryu", "spyro")],
          "delegations map to characters: mario -> ryu, ryu -> spyro")
    tool = next(e for e in evs["events"] if e["kind"] == "tool_used")
    check(tool["tool"] == "get_ticket" and tool["character"] == "mario", "tool event names the tool and the character")
    appr = next(e for e in evs["events"] if e["kind"] == "approval_requested")
    check(appr["approval"]["created"] is True and appr["approval"]["request_id"] == 1, "approval event has request id 1")
    said = [e["said"] for e in evs["events"] if e["kind"] == "agent_finished"]
    check("Queued $2,400 rent for approval." in said and "Notice matches lease 1." in said,
          "agent_finished events carry readable summaries")
    started = next(e for e in evs["events"] if e["kind"] == "run_started")
    check(started["this_database"] is True, "run_started says the run used this database")
    fin = [e for e in evs["events"] if e["kind"] == "run_finished"]
    check(fin and fin[-1]["status"] == "completed", "run_finished reports completed")
    check(not any(e["kind"] == "model_step" for e in evs["events"]), "model steps are hidden unless verbose")
    check(evs["next_cursor"] == len(json.loads(TRAIL.read_text(encoding="utf-8"))), "next_cursor = trail length")
    check(c.get(f"/events?since={evs['next_cursor']}").json()["events"] == [], "polling from next_cursor returns nothing new")
    page = c.get(f"/events?since={cursor}&limit=3").json()
    check(len(page["events"]) == 3 and page["next_cursor"] == page["events"][-1]["index"] + 1, "limit pages the events")
    check(c.get("/tickets/102").json()["stage"] == "awaiting_approval", "ticket 102 stage: awaiting_approval")

    # --- more requests, filed as the agents would ---
    async def file_more():
        inv = await mcp("request_invoice_payment", ticket_id=101, invoice_id=501, reason="Unblock reprint",
                        requested_by="accounting")
        dis = await mcp("request_discount", ticket_id=103, sku="CC-HOOD-NAVY", size="M", quantity=8, unit_price=52.2,
                        reason="Bulk student order", requested_by="accounting")
        pur = await mcp("request_purchase", ticket_id=103, vendor_id=1, sku="CC-HOOD-NAVY", size="M", quantity=12,
                        reason="Restock for the club", requested_by="accounting")
        return inv["request"]["id"], dis["request"]["id"], pur["request"]["id"]
    inv_id, dis_id, pur_id = asyncio.run(file_more())
    pend = c.get("/approvals").json()
    check(pend["count"] == 4 and {r["status"] for r in pend["requests"]} == {"pending"}, "GET /approvals: 4 pending")
    check(c.get("/approvals?status=all&ticket_id=103").json()["count"] == 2, "GET /approvals filters by ticket")
    check(c.get("/cash").json()["pending_outflow"] == 2400 + 840 + 264, "GET /cash shows money committed to pending requests")

    # --- approvals: who, what, how much ---
    for name in ("accounting", "Boss", "Customer Service", "Spyro", "Mario", "system"):
        res = c.post("/approvals/1/approve", json={"approved_by": name, "expected_amount": 2400, "confirm": True})
        check(res.status_code == 403, f"approve as '{name}' -> 403")
    check(c.post("/approvals/1/approve", json={"approved_by": "Kate Duffy", "expected_amount": 2400}).status_code == 422,
          "approve without confirm -> 422")
    check(c.post("/approvals/1/approve", json={"approved_by": "Kate Duffy", "expected_amount": 240,
                                              "confirm": True}).status_code == 409, "approve with the wrong amount -> 409")
    check(db("SELECT COUNT(*) FROM payments")[0][0] == 0 and c.get("/cash").json()["balance"] == 3400,
          "refused approvals move no money")
    check(c.post("/approvals/999/approve", json={"approved_by": "Kate Duffy", "expected_amount": 1,
                                                "confirm": True}).status_code == 404, "approve unknown request -> 404")

    ok = c.post("/approvals/1/approve", json={"approved_by": "Kate Duffy", "expected_amount": 2400, "confirm": True,
                                             "note": "Rent is due Sept 2"})
    check(ok.status_code == 200 and ok.json()["result"]["balance_after"] == 1000.0, "approve rent: $2,400 paid, $1,000 left")
    again = c.post("/approvals/1/approve", json={"approved_by": "Kate Duffy", "expected_amount": 2400, "confirm": True})
    check(again.status_code == 409 and "already executed" in again.json()["detail"], "approving again -> 409, executes once")
    check(db("SELECT COUNT(*), SUM(amount), MAX(approved_by) FROM payments") == [(1, 2400.0, "Kate Duffy")],
          "one rent payment recorded, approved_by Kate Duffy")
    t102 = c.get("/tickets/102").json()
    check(t102["status"] == "resolved" and t102["stage"] == "resolved" and t102["open_or_resolved"] == "resolved",
          "ticket 102 resolved after the rent payment")
    check(db("SELECT next_due FROM leases WHERE id = 1")[0][0] == "2026-10-02", "lease next_due moved to 2026-10-02")

    # Insufficient cash: lower the temp copy's balance below the $840 invoice, then approve.
    conn = sqlite3.connect(TEST_DB)
    conn.execute("UPDATE cash_accounts SET balance = 500 WHERE name = 'checking'")
    conn.commit()
    conn.close()
    low = c.post(f"/approvals/{inv_id}/approve", json={"approved_by": "Kate Duffy", "expected_amount": 840, "confirm": True})
    check(low.status_code == 409 and "Not enough cash" in low.json()["detail"], "approve $840 with $500 -> 409 not enough cash")
    check(c.get("/cash").json()["balance"] == 500 and db("SELECT COUNT(*) FROM payments")[0][0] == 1,
          "insufficient cash: balance unchanged, no payment")
    check(db("SELECT status FROM approval_requests WHERE id = ?", inv_id)[0][0] == "pending", "the request stays pending")
    conn = sqlite3.connect(TEST_DB)
    conn.execute("UPDATE cash_accounts SET balance = 1000 WHERE name = 'checking'")
    conn.commit()
    conn.close()

    blocked = c.post(f"/approvals/{pur_id}/approve", json={"approved_by": "Kate Duffy", "expected_amount": 264, "confirm": True})
    check(blocked.status_code == 409 and "open invoice" in blocked.json()["detail"], "purchase from a blocked vendor -> 409")

    paid = c.post(f"/approvals/{inv_id}/approve", json={"approved_by": "Kate Duffy", "expected_amount": 840, "confirm": True})
    check(paid.status_code == 200 and paid.json()["result"]["balance_after"] == 160.0, "approve invoice 501: $160 left")
    t101 = c.get("/tickets/101").json()
    check(t101["status"] == "in_progress" and t101["stage"] == "approved_awaiting_external" and not t101["is_resolved"],
          "ticket 101 NOT resolved by paying the invoice (in_progress, awaiting supplier)")
    check(any("reprint" in w for w in t101["waiting_on"]) and "reach the customer" in t101["notes"],
          "ticket 101 says the reprint still has to reach the customer")

    rej = c.post(f"/approvals/{pur_id}/reject", json={"decided_by": "Kate Duffy", "confirm": True, "note": "No cash"})
    check(rej.status_code == 200 and rej.json()["request"]["status"] == "rejected", "reject the purchase -> rejected")
    check(c.post(f"/approvals/{pur_id}/reject", json={"decided_by": "Kate Duffy", "confirm": True}).status_code == 409,
          "rejecting again -> 409")
    check(c.post(f"/approvals/{dis_id}/reject", json={"decided_by": "inventory", "confirm": True}).status_code == 403,
          "reject as an agent -> 403")
    check(c.get("/tickets/103").json()["stage"] == "awaiting_approval", "ticket 103 still awaiting approval (discount)")
    dsc = c.post(f"/approvals/{dis_id}/approve", json={"approved_by": "Kate Duffy", "expected_amount": 417.6, "confirm": True})
    check(dsc.status_code == 200 and c.get("/cash").json()["balance"] == 160.0, "approve discount: no cash moves")
    t103 = c.get("/tickets/103").json()
    check(t103["status"] == "in_progress" and t103["stage"] == "approved_awaiting_external" and not t103["is_resolved"],
          "ticket 103 NOT resolved by the discount")
    check(any("not accepted" in w for w in t103["waiting_on"]), "ticket 103 says the customer has not accepted")

    # --- manual resolve by a person ---
    check(c.post("/tickets/101/resolve", json={"resolved_by": "boss", "confirmation": "x", "confirm": True}).status_code == 403,
          "resolve as an agent -> 403")
    check(c.post("/tickets/101/resolve", json={"resolved_by": "Kate Duffy", "confirmation": "", "confirm": True}).status_code == 422,
          "resolve without saying what was confirmed -> 422")
    check(c.post("/tickets/101/resolve", json={"resolved_by": "Kate Duffy", "confirmation": "test only", "confirm": True,
                                              "resolution_type": "finished"}).status_code == 422,
          "resolution_type must be operational or administrative")
    rv = c.post("/tickets/101/resolve", json={"resolved_by": "Kate Duffy", "confirm": True, "resolution_type": "administrative",
                                              "confirmation": "test only: invoice paid; reprint delivery still outstanding"})
    check(rv.status_code == 200 and c.get("/tickets/101").json()["status"] == "resolved"
          and rv.json()["resolution_type"] == "administrative", "a person can resolve 101 administratively")
    check("(administrative resolution)" in c.get("/tickets/101").json()["notes"], "the ticket note names the resolution type")
    t101 = c.get("/tickets/101").json()
    check(t101["resolution_type"] == "administrative" and t101["stage_label"].startswith("Resolved (administrative)")
          and "Fully" not in t101["stage_label"], "101's label says administrative, never 'fully resolved'")
    t102 = c.get("/tickets/102").json()
    check(t102["resolution_type"] == "operational" and t102["stage_label"] == "Resolved (operational)",
          "102's label says operational")
    check(c.post("/tickets/101/run").status_code == 409, "running a resolved ticket -> 409")

    # --- audit of human decisions ---
    trail = json.loads(TRAIL.read_text(encoding="utf-8"))
    decided = [e for e in trail if e.get("action") == "approval_decided"]
    check([e["decision"] for e in decided].count("approved") == 3 and all(e["decided_by"] == "Kate Duffy" for e in decided),
          "approval_decided events record the approver's name")
    check(any(e.get("action") == "ticket_updated" for e in trail), "ticket_updated events are recorded")
    res_types = {e["ticket_id"]: e.get("resolution_type") for e in trail
                 if e.get("action") == "ticket_updated" and e.get("status") == "resolved"}
    check(res_types == {102: "operational", 101: "administrative"},
          "audit trail records resolution_type: 102 operational (rent rule), 101 administrative (person)")
    dec = [e for e in c.get("/events?limit=1000").json()["events"] if e["action"] == "approval_decided"]
    check(dec and all(e["kind"] == "approval_decided" for e in dec) and dec[0]["request_kind"] == "rent_payment",
          "/events keeps kind=approval_decided and reports request_kind separately")

    # --- reset ---
    check(c.post("/reset", json={"confirm": "yes"}).status_code == 422, "reset without confirm RESET -> 422")
    main.STATE.transaction_active = True
    check(c.post("/reset", json={"confirm": "RESET"}).status_code == 409, "reset during a transaction -> 409")
    main.STATE.transaction_active = False
    before_len = len(trail)
    rs = c.post("/reset", json={"confirm": "RESET", "reset_by": "Kate Duffy"})
    check(rs.status_code == 200 and rs.json()["epoch"] == 1, "POST /reset -> 200, epoch 1")
    check(sha(TEST_DB) == sha(ORIGINAL), "reset restores the original database byte for byte")
    trail2 = json.loads(TRAIL.read_text(encoding="utf-8"))
    check(len(trail2) == before_len + 1 and trail2[:before_len] == trail, "reset keeps every earlier audit entry")
    ev2 = c.get(f"/events?since={before_len}").json()
    first = ev2["events"][0] if ev2["events"] else {}
    check(first.get("kind") == "database_reset" and first.get("epoch") == 1 and ev2["epoch"] == 1,
          "events after the reset are in epoch 1")
    check(c.get(f"/events?since={cursor}").json()["events"][0]["epoch"] == 0, "earlier events stay in epoch 0")
    t = c.get("/tickets").json()["tickets"]
    check(all(x["status"] == "open" and x["stage"] == "not_started" for x in t), "after reset: all open, not_started")
    check(c.get("/cash").json()["balance"] == 3400 and c.get("/approvals").json()["count"] == 0,
          "after reset: $3,400 and no approval requests")


def check_port_conflict() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        proc = main.MCPProcess(f"http://127.0.0.1:{port}/mcp", wait_for_free_port=0.5)
        try:
            asyncio.run(proc.start())
            check(False, "an occupied MCP port is refused")
        except RuntimeError as exc:
            check("already in use" in str(exc) and proc.proc is None,
                  "an occupied MCP port gives a clear error and starts no second server")


def check_isolation() -> None:
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    check(src.count('"execute_approved_request"') == 1 and "async def approve(" in src,
          "main.py calls execute_approved_request in one place: the approve route")
    check(not any("execute_approved_request" in t for t in agents.AGENT_TOOLS.values()),
          "no agent's tool list includes execute_approved_request")
    agent_src = (ROOT / "backend" / "agents.py").read_text(encoding="utf-8")
    check("execute_approved_request" not in agent_src.replace('"execute_approved_request", "reject_request"', ""),
          "agents.py only names execute_approved_request in BACKEND_ONLY_TOOLS")


def run() -> int:
    before = {p: sha(p) for p in (ORIGINAL, WORKING)}
    try:
        with TestClient(main.app) as c:
            main_checks(c)
        check(not main.MCPProcess(main.config.MCP_SERVER_URL).port_in_use(), "the MCP server stops with the API")
        check_port_conflict()
        check_isolation()
    finally:
        RELEASE.set()
    check({p: sha(p) for p in (ORIGINAL, WORKING)} == before, "original and grading working databases unchanged")
    failed = [label for ok, label in results if not ok]
    for ok, label in results:
        print(("PASS " if ok else "FAIL ") + label)
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
