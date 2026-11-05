"""Campus Customs backend API (Homework 5, Problem 7).

Start it from the backend/ folder (Problem 7, Panel B):

    uvicorn main:app --reload --port 8000

The API serves http://localhost:8000 for the React dashboard (Problem 8). When it starts it
launches the campus-customs MCP server on MCP_SERVER_URL (default 127.0.0.1:8001), and it
stops that server when it shuts down. Every database read and write goes through the MCP
tools, so the safeguards in mcp_server/server.py apply here too.

Money rules:
- Agents can only *request* payments, purchases and discounts (pending approval_requests).
- POST /approvals/{id}/approve is the only route that executes one, and only after a person
  names themselves, confirms, and repeats the amount they saw.
- Approver names are recorded, not authenticated. This is a classroom simulation on
  localhost, not production-grade authentication.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import Client
from pydantic import BaseModel, Field

import agents
import config
from audit import append_event

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
ORIGINAL_DB = ROOT / "data" / "campus_customs.db"


def working_db() -> Path:
    """The database the MCP server uses: CAMPUS_CUSTOMS_DB if set, else the working copy."""
    override = os.getenv("CAMPUS_CUSTOMS_DB", "").strip()
    return Path(override).resolve() if override else ROOT / "data" / "campus_customs_new.db"


# Agent and character names can never approve, reject or resolve anything.
CHARACTERS = {"boss": "mario", "inventory": "crash", "accounting": "spyro",
              "facilities": "ryu", "customer_service": "sonic"}
_NOT_HUMAN = set(CHARACTERS) | set(CHARACTERS.values()) | {
    "crash bandicoot", "customer service", "agent", "system", "dashboard", "backend", "ai", "bot"}

FRONTEND_ORIGINS = [o.strip() for o in os.getenv(
    "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# MCP server lifecycle
# ---------------------------------------------------------------------------


class MCPProcess:
    """Starts mcp_supervised.py on the MCP port and stops it again. Never starts a second one."""

    def __init__(self, url: str, wait_for_free_port: float = 5.0) -> None:
        parsed = urlparse(url)
        self.url, self.host, self.port = url, parsed.hostname or "127.0.0.1", parsed.port or 8001
        self.wait_for_free_port = wait_for_free_port
        self.proc: subprocess.Popen | None = None

    def port_in_use(self) -> bool:
        with socket.socket() as s:
            s.settimeout(0.3)
            return s.connect_ex((self.host, self.port)) == 0

    async def start(self) -> None:
        # A server left by a reloaded worker exits within a moment (see mcp_supervised.py).
        deadline = time.monotonic() + self.wait_for_free_port
        while self.port_in_use():
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"Port {self.port} is already in use, so the campus-customs MCP server was not started "
                    f"(the backend never starts a second one). Find and stop whatever is listening there, e.g. in "
                    f"PowerShell: netstat -ano | findstr :{self.port}  then  taskkill /PID <pid> /T /F"
                )
            await asyncio.sleep(0.2)
        # On Windows, uvicorn --reload stops its worker with a console Ctrl+C. A separate process
        # group keeps that Ctrl+C away from the MCP server; it stops when we close its stdin instead.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "mcp_supervised.py"), "--host", self.host, "--port", str(self.port)],
            stdin=subprocess.PIPE, cwd=str(ROOT), creationflags=flags,
        )
        for _ in range(100):
            if self.proc.poll() is not None:
                raise RuntimeError(f"The campus-customs MCP server exited during startup (code {self.proc.returncode}).")
            with contextlib.suppress(Exception):
                async with Client(self.url) as c:
                    await c.list_tools()
                return
            await asyncio.sleep(0.2)
        await self.stop()
        raise RuntimeError(f"The campus-customs MCP server did not answer on {self.url}.")

    async def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        with contextlib.suppress(Exception):
            proc.stdin.close()  # the launcher exits when its stdin closes
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# MCP calls
# ---------------------------------------------------------------------------


class ToolFailure(Exception):
    """An MCP tool refused the call (e.g. an agent name used as approver)."""


async def mcp_call(tool: str, **args: Any) -> dict:
    try:
        async with Client(config.MCP_SERVER_URL) as client:
            res = await client.call_tool(tool, args, raise_on_error=False)
    except Exception as exc:
        raise HTTPException(503, f"The campus-customs MCP server is unavailable ({type(exc).__name__}).") from exc
    if res.is_error:
        raise ToolFailure(" ".join(getattr(c, "text", "") for c in res.content).strip() or f"{tool} failed")
    return res.data if res.data is not None else res.structured_content


# ---------------------------------------------------------------------------
# Run, transaction and reset state (one API process)
# ---------------------------------------------------------------------------


class State:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()  # serialises starting runs, approvals and resets
        self.active_run: str | None = None
        self.transaction_active = False
        self.runs: dict[str, dict[str, Any]] = {}
        self.tasks: dict[str, asyncio.Task] = {}


STATE = State()


def _busy_reason() -> str | None:
    if STATE.active_run:
        run = STATE.runs[STATE.active_run]
        return f"An agent run is active (ticket {run['ticket_id']}, run {run['run_id']}). Wait for it to finish."
    if STATE.transaction_active:
        return "A human approval is being processed. Try again in a moment."
    return None


def human_name(name: str, field: str) -> str:
    who = " ".join((name or "").split())
    key = who.lower()
    if len(who) < 2:
        raise HTTPException(422, f"{field} must be the name of the person making this decision.")
    if key in _NOT_HUMAN or key.replace(" ", "_") in _NOT_HUMAN:
        raise HTTPException(403, f"'{who}' is an agent or system name. Only a person can make this decision.")
    return who


# ---------------------------------------------------------------------------
# Audit trail -> dashboard events
# ---------------------------------------------------------------------------


def _load_trail() -> list[dict]:
    path = config.AUDIT_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _epochs(trail: list[dict]) -> list[int]:
    """Epoch of each entry: how many database resets came before it (a reset starts a new epoch)."""
    out, epoch = [], 0
    for ev in trail:
        if ev.get("action") == "database_reset":
            epoch += 1
        out.append(epoch)
    return out


def _to_agent(ev: dict) -> str | None:
    raw = ev.get("delegation")
    text = raw if isinstance(raw, str) else json.dumps(raw or {})
    m = re.search(r"""["']to_agent["']\s*:\s*["'](\w+)["']""", text)
    return m.group(1) if m else None


def _approval_info(result: Any) -> dict:
    text = result if isinstance(result, str) else json.dumps(result or {})
    created = re.search(r'"created":\s*(true|false)', text)
    rid = re.search(r'"request":\s*\{\s*"id":\s*(\d+)', text)
    return {"created": created.group(1) == "true" if created else None,
            "duplicate": '"duplicate": true' in text,
            "request_id": int(rid.group(1)) if rid else None}


def simplify(index: int, ev: dict, epoch: int, verbose: bool = False) -> dict | None:
    """One audit entry in the shape the dashboard needs, or None to skip it."""
    action = ev.get("action", "")
    agent = ev.get("agent")
    base = {
        "index": index, "epoch": epoch, "time": ev.get("time"), "run_id": ev.get("run_id"),
        "ticket_id": ev.get("ticket_id"), "action": action, "agent": agent, "character": CHARACTERS.get(agent),
        "parent_agent": ev.get("parent_agent"), "parent_character": CHARACTERS.get(ev.get("parent_agent")),
        "depth": ev.get("depth"),
    }
    if action == "run_started":
        # this_database is False for runs made on another copy (e.g. the Problem 5 isolated live test).
        return {**base, "kind": "run_started", "model": ev.get("model"), "run_label": ev.get("run_label"),
                "this_database": ev.get("mcp_server") == config.MCP_SERVER_URL}
    if action == "run_finished":
        return {**base, "kind": "run_finished", "status": ev.get("status"), "error": ev.get("error"),
                "usage": ev.get("usage")}
    if action == "agent_started":
        return {**base, "kind": "agent_active"}
    if action == "agent_finished":
        said = ev.get("summary")
        if not said:  # entries written before Problem 7 only have the truncated report
            m = re.search(r'"summary":\s*"((?:[^"\\]|\\.)*)', str(ev.get("result", "")))
            said = m.group(1) if m else None
        return {**base, "kind": "agent_finished", "said": said, "customer_reply": ev.get("customer_reply"),
                "recommended_ticket_status": ev.get("recommended_ticket_status"),
                "open_issues": ev.get("open_issues"), "approval_request_ids": ev.get("approval_request_ids")}
    if action == "mcp_tool_call":
        tool = ev.get("tool") or ""
        out = {**base, "kind": "tool_used", "tool": tool, "args": ev.get("args")}
        if tool.startswith("request_"):
            info = _approval_info(ev.get("result"))
            out.update(approval=info)
            if info["created"] or info["duplicate"]:
                out["kind"] = "approval_requested"
        return out
    if action in ("mcp_tool_refused", "mcp_tool_error"):
        return {**base, "kind": "tool_failed", "tool": ev.get("tool"), "error": ev.get("result")}
    if action in ("delegation_started", "delegation_finished", "delegation_cached", "delegation_refused",
                  "delegation_failed"):
        to = _to_agent(ev)
        kind = {"delegation_started": "delegation_started", "delegation_finished": "delegation_finished",
                "delegation_cached": "delegation_finished"}.get(action, "delegation_failed")
        out = {**base, "kind": kind, "to_agent": to, "to_character": CHARACTERS.get(to)}
        if kind == "delegation_failed":
            out["reason"] = ev.get("result")
        return out
    if action == "model_response":
        text = [t for t in (ev.get("text") or []) if t]
        if text:
            return {**base, "kind": "said", "said": " ".join(text)}
        return {**base, "kind": "model_step", "tool_calls": ev.get("tool_calls")} if verbose else None
    if action == "model_request":
        return {**base, "kind": "model_step"} if verbose else None
    if action in ("database_reset", "approval_decided", "ticket_updated"):
        extra = {k: v for k, v in ev.items() if k not in base and k not in ("action", "kind")}
        if "kind" in ev:  # an approval's request kind (rent_payment, ...) must not replace the event kind
            extra["request_kind"] = ev["kind"]
        return {**base, **extra, "kind": action}
    return {**base, "kind": action} if verbose else None


def _completed_runs(ticket_id: int) -> int:
    """Completed agent runs on this ticket, against this database, since the last reset.

    Runs that used another MCP server (e.g. the Problem 5 live test on an isolated copy) don't count.
    """
    trail = _load_trail()
    epochs = _epochs(trail)
    current = epochs[-1] if epochs else 0
    here = {ev.get("run_id") for ev, ep in zip(trail, epochs) if ep == current
            and ev.get("action") == "run_started" and ev.get("mcp_server") == config.MCP_SERVER_URL}
    return sum(1 for ev, ep in zip(trail, epochs) if ep == current and ev.get("action") == "run_finished"
               and ev.get("run_id") in here and ev.get("ticket_id") == ticket_id and ev.get("status") == "completed")


# ---------------------------------------------------------------------------
# Ticket stages (derived; the database keeps its four statuses)
# ---------------------------------------------------------------------------

# What still has to happen in the outside world after a human approves each kind of request.
WAITING_ON = {
    "invoice_payment": "The supplier invoice is paid; the reprint still has to arrive and reach the customer.",
    "purchase": "The purchase is approved; the vendor still has to deliver the stock.",
    "discount": "The discount is approved as an offer; the customer has not accepted it and the stock "
                "shortage is not solved.",
}
STAGE_LABELS = {
    "not_started": "Not started",
    "agents_working": "Agents working",
    "investigated": "Agent investigation completed",
    "awaiting_approval": "Awaiting human approval",
    "approved_awaiting_external": "Approved; awaiting supplier or customer",
    "needs_follow_up": "Request rejected; needs follow-up",
    "resolved": "Resolved",
}


RESOLVED_LABELS = {
    "operational": "Resolved (operational)",
    "administrative": "Resolved (administrative): outside steps outstanding",
}


def _resolution_type(ticket_id: int) -> str | None:
    """The resolution_type recorded when this ticket was last resolved, since the last reset."""
    trail = _load_trail()
    epochs = _epochs(trail)
    current = epochs[-1] if epochs else 0
    found = None
    for ev, ep in zip(trail, epochs):
        if (ep == current and ev.get("action") == "ticket_updated" and ev.get("ticket_id") == ticket_id
                and ev.get("status") == "resolved"):
            found = ev.get("resolution_type")
    return found


def ticket_stage(ticket: dict, requests: list[dict]) -> dict:
    status = ticket["status"]
    pending = [r for r in requests if r["status"] == "pending"]
    executed = [r for r in requests if r["status"] == "executed"]
    rejected = [r for r in requests if r["status"] == "rejected"]
    waiting_on = [WAITING_ON[k] for k in dict.fromkeys(r["kind"] for r in executed) if k in WAITING_ON]
    run = STATE.runs.get(STATE.active_run or "")
    if status == "resolved":
        stage = "resolved"
    elif run and run["ticket_id"] == ticket["id"]:
        stage = "agents_working"
    elif pending:
        stage = "awaiting_approval"
    elif executed:
        stage = "approved_awaiting_external"
    elif rejected:
        stage = "needs_follow_up"
    elif _completed_runs(ticket["id"]):
        stage = "investigated"
    else:
        stage = "not_started"
    resolution_type = _resolution_type(ticket["id"]) if stage == "resolved" else None
    label = RESOLVED_LABELS.get(resolution_type or "", STAGE_LABELS[stage]) if stage == "resolved" else STAGE_LABELS[stage]
    return {
        "stage": stage, "stage_label": label, "resolution_type": resolution_type,
        # An administrative resolution keeps its outside steps visible; an operational one has none.
        "waiting_on": waiting_on if stage != "resolved" or resolution_type == "administrative" else [],
        "pending_requests": len(pending), "executed_requests": len(executed), "rejected_requests": len(rejected),
    }


def _ticket_view(ticket: dict, requests: list[dict]) -> dict:
    mine = [r for r in requests if r["ticket_id"] == ticket["id"]]
    return {**ticket, "open_or_resolved": "resolved" if ticket["status"] == "resolved" else "open",
            "is_resolved": ticket["status"] == "resolved", **ticket_stage(ticket, mine)}


async def _all_requests() -> list[dict]:
    return (await mcp_call("list_approval_requests"))["requests"]


async def _after_decision(ticket_id: int, who: str, decision: str, request_id: int) -> dict:
    """Set the ticket's database status after a human decision, without claiming outside events.

    - Requests still pending      -> awaiting_approval
    - Rent notice, rent paid      -> resolved (the payment is the whole job), if nothing was rejected
    - Anything else approved      -> in_progress, with a note on what is still outstanding
    - Everything rejected         -> open, with a note that it needs another plan
    """
    data = await mcp_call("get_ticket", ticket_id=ticket_id)
    ticket, requests = data["ticket"], data["approval_requests"]
    pending = [r for r in requests if r["status"] == "pending"]
    executed = [r for r in requests if r["status"] == "executed"]
    rejected = [r for r in requests if r["status"] == "rejected"]
    head = f"{who} {decision} approval request {request_id} in the dashboard."
    if pending:
        status, note = "awaiting_approval", f"{head} {len(pending)} request(s) still wait for approval."
    elif (ticket["type"] == "rent_notice" and not rejected
          and any(r["kind"] == "rent_payment" for r in executed)):
        paid = [r for r in executed if r["kind"] == "rent_payment"][-1]
        res = paid.get("result") or {}
        status = "resolved"
        note = (f"{head} Rent of ${paid['amount']:,.2f} recorded as payment {res.get('payment_id')}; "
                f"lease next due {res.get('lease_next_due')}. Nothing else outstanding.")
    elif executed:
        outstanding = " ".join(WAITING_ON[k] for k in dict.fromkeys(r["kind"] for r in executed) if k in WAITING_ON)
        rej = f" {len(rejected)} request(s) were rejected." if rejected else ""
        status, note = "in_progress", f"{head}{rej} Not resolved yet: {outstanding}".strip()
    else:
        status, note = "open", f"{head} No request was approved, so the ticket needs another plan."
    if status == ticket["status"] and note in (ticket.get("notes") or ""):
        return ticket
    out = await mcp_call("update_ticket", ticket_id=ticket_id, status=status, note=note,
                         updated_by=f"dashboard ({who})")
    append_event({"run_id": None, "ticket_id": ticket_id, "agent": None, "action": "ticket_updated",
                  "status": status, "previous_status": ticket["status"], "note": note, "updated_by": who,
                  # The recorded rent payment is the whole job, so this resolution is operational.
                  "resolution_type": "operational" if status == "resolved" else None})
    return out.get("ticket", ticket)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    supervisor = MCPProcess(config.MCP_SERVER_URL)
    manage = os.getenv("BACKEND_MANAGE_MCP", "1").strip() != "0"
    if manage:
        await supervisor.start()
    app.state.mcp = supervisor
    try:
        yield
    finally:
        for task in list(STATE.tasks.values()):
            task.cancel()
        if manage:
            await supervisor.stop()


app = FastAPI(
    title="Campus Customs Agent Arcade API",
    description="Homework 5, Problem 7. Local classroom simulation; approver names are recorded, not authenticated.",
    version="1.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=FRONTEND_ORIGINS, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type"])


class ApproveBody(BaseModel):
    approved_by: str = Field(description="Name of the person approving")
    expected_amount: float = Field(description="The amount the person saw; must match the request")
    confirm: bool = Field(False, description="Must be true: the person deliberately approves")
    note: str = ""


class RejectBody(BaseModel):
    decided_by: str = Field(description="Name of the person rejecting")
    confirm: bool = Field(False, description="Must be true: the person deliberately rejects")
    note: str = ""


class ResolveBody(BaseModel):
    resolved_by: str = Field(description="Name of the person marking the ticket resolved")
    confirmation: str = Field(description="The resolution note: what has and has not happened")
    confirm: bool = False
    # operational: the real-world outcome is fulfilled. administrative: the desk's work is done and the
    # ticket is closed, but the note lists outside steps (delivery, stock, customer decision) still outstanding.
    resolution_type: Literal["operational", "administrative"] | None = None


class ResetBody(BaseModel):
    confirm: str = Field("", description='Must be exactly "RESET"')
    reset_by: str | None = None


ROUTES = [
    ("GET", "/health", "Backend, MCP server and model status"),
    ("GET", "/tickets", "The three tickets: open or resolved, plus their stage"),
    ("GET", "/tickets/{ticket_id}", "One ticket with notes, stage and approval requests"),
    ("POST", "/tickets/{ticket_id}/run", "Start the agent team on a ticket in the background (one run at a time)"),
    ("POST", "/tickets/{ticket_id}/resolve", "A person marks a ticket resolved after confirming the outside step"),
    ("GET", "/runs", "Runs started by this backend since it started"),
    ("GET", "/runs/{run_id}", "One run's status, final report, delegations and token use"),
    ("GET", "/events", "Recent agent events (who is active, delegations, tools, what each agent concluded)"),
    ("GET", "/approvals", "Approval requests (pending by default)"),
    ("POST", "/approvals/{request_id}/approve", "A person approves a request; the only route that moves cash"),
    ("POST", "/approvals/{request_id}/reject", "A person rejects a request; moves no cash"),
    ("GET", "/cash", "The checking balance from cash_accounts"),
    ("POST", "/reset", "Copy the original database over the working copy (needs confirm RESET)"),
]


@app.get("/")
async def index() -> dict:
    return {"app": "Campus Customs Agent Arcade API", "docs": "/docs",
            "routes": [{"method": m, "path": p, "purpose": d} for m, p, d in ROUTES]}


@app.get("/health")
async def health() -> dict:
    try:
        async with Client(config.MCP_SERVER_URL) as c:
            names = {t.name for t in await c.list_tools()}
    except Exception as exc:
        raise HTTPException(503, f"The campus-customs MCP server is unavailable at {config.MCP_SERVER_URL} "
                                 f"({type(exc).__name__}).") from exc
    epochs = _epochs(_load_trail())
    return {
        "status": "ok",
        "model": config.MODEL_NAME,
        "mcp_server": config.MCP_SERVER_URL,
        "mcp_tools": len(names),
        "backend_only_tools_present": sorted(names & agents.BACKEND_ONLY_TOOLS),
        "database": working_db().name,
        "portkey_key_configured": bool(os.getenv("PORTKEY_API_KEY", "").strip()),
        "active_run": STATE.active_run,
        "transaction_active": STATE.transaction_active,
        "epoch": epochs[-1] if epochs else 0,
        "authentication": "none: approver names are recorded, not verified (classroom simulation)",
    }


@app.get("/tickets")
async def list_tickets() -> dict:
    tickets = (await mcp_call("list_tickets"))["tickets"]
    requests = await _all_requests()
    return {"tickets": [_ticket_view(t, requests) for t in tickets]}


@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: int) -> dict:
    data = await mcp_call("get_ticket", ticket_id=ticket_id)
    if not data.get("found"):
        raise HTTPException(404, f"Ticket {ticket_id} not found.")
    return {**_ticket_view(data["ticket"], data["approval_requests"]), "today": data["today"],
            "approval_requests": data["approval_requests"]}


async def _run_in_background(run_id: str, ticket_id: int) -> None:
    info = STATE.runs[run_id]
    try:
        result = await agents.run_team(ticket_id, run_id=run_id)
        info.update(status=result.status, error=result.error, result=result.model_dump(mode="json"))
    except asyncio.CancelledError:
        info.update(status="cancelled", error="The backend shut down during the run.")
        raise
    except Exception as exc:  # run_team catches agent errors itself; this is a last resort
        info.update(status="error", error=f"{type(exc).__name__}: {exc}"[:500])
    finally:
        info["finished_at"] = _now()
        STATE.active_run = None
        STATE.tasks.pop(run_id, None)


@app.post("/tickets/{ticket_id}/run", status_code=202)
async def start_run(ticket_id: int) -> dict:
    async with STATE.lock:
        busy = _busy_reason()
        if busy:
            raise HTTPException(409, busy)
        data = await mcp_call("get_ticket", ticket_id=ticket_id)
        if not data.get("found"):
            raise HTTPException(404, f"Ticket {ticket_id} not found.")
        if data["ticket"]["status"] == "resolved":
            raise HTTPException(409, f"Ticket {ticket_id} is already resolved. Reset the database to run it again.")
        try:
            config.portkey_api_key()
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        run_id = str(uuid.uuid4())
        cursor = len(_load_trail())
        STATE.runs[run_id] = {"run_id": run_id, "ticket_id": ticket_id, "status": "running", "started_at": _now(),
                              "finished_at": None, "error": None, "result": None, "events_since": cursor}
        STATE.active_run = run_id
        STATE.tasks[run_id] = asyncio.create_task(_run_in_background(run_id, ticket_id))
    return {"run_id": run_id, "ticket_id": ticket_id, "status": "running",
            "poll": {"run": f"/runs/{run_id}", "events": f"/events?run_id={run_id}&since={cursor}"}}


@app.post("/tickets/{ticket_id}/resolve")
async def resolve_ticket(ticket_id: int, body: ResolveBody) -> dict:
    who = human_name(body.resolved_by, "resolved_by")
    if not body.confirm or not body.confirmation.strip():
        raise HTTPException(422, "Describe what you confirmed and set confirm to true.")
    async with STATE.lock:
        busy = _busy_reason()
        if busy:
            raise HTTPException(409, busy)
        data = await mcp_call("get_ticket", ticket_id=ticket_id)
        if not data.get("found"):
            raise HTTPException(404, f"Ticket {ticket_id} not found.")
        if any(r["status"] == "pending" for r in data["approval_requests"]):
            raise HTTPException(409, "This ticket still has pending approval requests; decide those first.")
        if data["ticket"]["status"] == "resolved":
            raise HTTPException(409, f"Ticket {ticket_id} is already resolved.")
        kind = f" ({body.resolution_type} resolution)" if body.resolution_type else ""
        note = f"Marked resolved by {who}{kind} in the dashboard: {body.confirmation.strip()}"
        out = await mcp_call("update_ticket", ticket_id=ticket_id, status="resolved", note=note,
                             updated_by=f"dashboard ({who})")
        if not out.get("updated"):
            raise HTTPException(409, out.get("message", "The ticket could not be resolved."))
        append_event({"run_id": None, "ticket_id": ticket_id, "agent": None, "action": "ticket_updated",
                      "status": "resolved", "previous_status": data["ticket"]["status"], "note": note,
                      "updated_by": who, "resolution_type": body.resolution_type})
    return {"resolved": True, "resolution_type": body.resolution_type, "ticket": out["ticket"]}


@app.get("/runs")
async def list_runs() -> dict:
    return {"active_run": STATE.active_run,
            "runs": sorted(STATE.runs.values(), key=lambda r: r["started_at"], reverse=True)}


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = STATE.runs.get(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} is not known to this backend (runs are kept until it restarts).")
    return run


@app.get("/events")
async def list_events(
    since: int | None = Query(None, ge=0, description="Return entries from this audit index on (polling cursor)"),
    run_id: str | None = None,
    ticket_id: int | None = None,
    limit: int = Query(200, ge=1, le=1000),
    verbose: bool = False,
) -> dict:
    trail = _load_trail()
    epochs = _epochs(trail)
    out = []
    for i, ev in enumerate(trail):
        if since is not None and i < since:
            continue
        if run_id and ev.get("run_id") != run_id:
            continue
        if ticket_id is not None and ev.get("ticket_id") != ticket_id:
            continue
        item = simplify(i, ev, epochs[i], verbose)
        if item:
            out.append(item)
    if since is None:
        out, next_cursor = out[-limit:], len(trail)
    elif len(out) > limit:
        out = out[:limit]
        next_cursor = out[-1]["index"] + 1
    else:
        next_cursor = len(trail)
    return {"events": out, "next_cursor": next_cursor, "epoch": epochs[-1] if epochs else 0,
            "active_run": STATE.active_run}


@app.get("/approvals")
async def list_approvals(status: str = Query("pending", pattern="^(pending|executed|rejected|all)$"),
                         ticket_id: int | None = None) -> dict:
    args: dict[str, Any] = {}
    if status != "all":
        args["status"] = status
    if ticket_id is not None:
        args["ticket_id"] = ticket_id
    data = await mcp_call("list_approval_requests", **args)
    return {"status": status, "count": data["count"], "requests": data["requests"]}


async def _pending_request(request_id: int) -> dict:
    req = next((r for r in await _all_requests() if r["id"] == request_id), None)
    if req is None:
        raise HTTPException(404, f"Approval request {request_id} not found.")
    if req["status"] != "pending":
        raise HTTPException(409, f"Approval request {request_id} is already {req['status']}; nothing was done.")
    return req


@app.post("/approvals/{request_id}/approve")
async def approve(request_id: int, body: ApproveBody) -> dict:
    who = human_name(body.approved_by, "approved_by")
    if not body.confirm:
        raise HTTPException(422, "Review the request and set confirm to true to approve it.")
    async with STATE.lock:
        busy = _busy_reason()
        if busy:
            raise HTTPException(409, busy)
        STATE.transaction_active = True
        try:
            req = await _pending_request(request_id)
            if round(body.expected_amount, 2) != round(req["amount"], 2):
                raise HTTPException(409, f"The request is for ${req['amount']:,.2f}, not ${body.expected_amount:,.2f}. "
                                         "Nothing was done; reload it and review again.")
            try:
                res = await mcp_call("execute_approved_request", request_id=request_id, approved_by=who,
                                     note=body.note)
            except ToolFailure as exc:
                raise HTTPException(403, str(exc)) from exc
            if not res.get("executed"):
                append_event({"run_id": None, "ticket_id": req["ticket_id"], "agent": None,
                              "action": "approval_decided", "decision": "approve_refused", "request_id": request_id,
                              "kind": req["kind"], "amount": req["amount"], "decided_by": who,
                              "message": res.get("message")})
                raise HTTPException(409, res.get("message", "The request could not be executed."))
            append_event({"run_id": None, "ticket_id": req["ticket_id"], "agent": None, "action": "approval_decided",
                          "decision": "approved", "request_id": request_id, "kind": req["kind"],
                          "amount": req["amount"], "decided_by": who, "result": res.get("result")})
            ticket = await _after_decision(req["ticket_id"], who, "approved", request_id)
        finally:
            STATE.transaction_active = False
    return {"approved": True, "request": res["request"], "result": res["result"], "ticket": ticket}


@app.post("/approvals/{request_id}/reject")
async def reject(request_id: int, body: RejectBody) -> dict:
    who = human_name(body.decided_by, "decided_by")
    if not body.confirm:
        raise HTTPException(422, "Review the request and set confirm to true to reject it.")
    async with STATE.lock:
        busy = _busy_reason()
        if busy:
            raise HTTPException(409, busy)
        STATE.transaction_active = True
        try:
            req = await _pending_request(request_id)
            try:
                res = await mcp_call("reject_request", request_id=request_id, decided_by=who, note=body.note)
            except ToolFailure as exc:
                raise HTTPException(403, str(exc)) from exc
            if not res.get("rejected"):
                raise HTTPException(409, res.get("message", "The request could not be rejected."))
            append_event({"run_id": None, "ticket_id": req["ticket_id"], "agent": None, "action": "approval_decided",
                          "decision": "rejected", "request_id": request_id, "kind": req["kind"],
                          "amount": req["amount"], "decided_by": who})
            ticket = await _after_decision(req["ticket_id"], who, "rejected", request_id)
        finally:
            STATE.transaction_active = False
    return {"rejected": True, "request": res["request"], "ticket": ticket}


@app.get("/cash")
async def cash() -> dict:
    data = await mcp_call("get_cash_balance")
    acct = next((a for a in data["cash_accounts"] if a["name"] == "checking"), None)
    if acct is None:
        raise HTTPException(404, "No checking account in cash_accounts.")
    return {"account": "checking", "balance": acct["balance"], "as_of": acct["as_of"], "today": data["today"],
            "pending_outflow": acct["pending_outflow"], "available_after_pending": acct["available_after_pending"]}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@app.post("/reset")
async def reset(body: ResetBody) -> dict:
    if body.confirm != "RESET":
        raise HTTPException(422, 'Type "RESET" in confirm to copy the original database over the working copy.')
    who = human_name(body.reset_by, "reset_by") if body.reset_by else None
    busy = _busy_reason() or ("Another run, approval or reset is being processed." if STATE.lock.locked() else None)
    if busy:  # refuse at once rather than queue behind a run or a transaction
        raise HTTPException(409, busy)
    async with STATE.lock:
        busy = _busy_reason()
        if busy:
            raise HTTPException(409, busy)
        target = working_db()
        if not ORIGINAL_DB.exists():
            raise HTTPException(503, "The original database is missing, so there is nothing to reset from.")
        if target.exists() and target.samefile(ORIGINAL_DB):
            raise HTTPException(500, "The working database path points at the original; refusing to touch it.")
        temp = target.with_name(target.name + ".resetting")
        shutil.copyfile(ORIGINAL_DB, temp)
        try:
            os.replace(temp, target)  # atomic swap where the OS allows it
        except PermissionError:
            # Windows refuses the swap while an idle reader (e.g. the MCP server) still holds the file
            # open. No run or transaction is active (we hold the lock), so overwrite it in place.
            data = temp.read_bytes()
            try:
                with open(target, "r+b") as f:
                    f.write(data)
                    f.truncate()
            except OSError as exc:
                raise HTTPException(503, f"The working database is in use; try the reset again ({exc}).") from exc
            finally:
                temp.unlink(missing_ok=True)
        if _sha(target) != _sha(ORIGINAL_DB):
            raise HTTPException(500, "The reset copy does not match the original.")
        append_event({"run_id": None, "ticket_id": None, "agent": None, "action": "database_reset",
                      "database": target.name, "reset_by": who,
                      "note": "Working database replaced with the original. Earlier events belong to the previous epoch."})
        trail = _load_trail()
    return {"reset": True, "database": target.name, "epoch": _epochs(trail)[-1], "next_cursor": len(trail)}
