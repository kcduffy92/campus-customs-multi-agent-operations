"""Deterministic checks for the agent team's guardrails. Makes no model calls.

Covers the model lock, per-agent tool allowlists, payment-execution isolation,
identity stamping on MCP calls, delegation limits (self, circular, depth,
per-ticket, duplicate), audit-trail integrity under concurrent writers, secret
redaction, and the HTTP MCP transport on an isolated database copy.

Run from the Homework 5 folder:  .venv/Scripts/python.exe tests/check_agent_team.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
PY = sys.executable
TMP = Path(tempfile.mkdtemp(prefix="hw5_agents_"))
AUDIT = TMP / "audit_trail.json"
FAKE_SECRET = "pk-test-redaction-0123456789"
os.environ["AUDIT_TRAIL_PATH"] = str(AUDIT)
os.environ["PORTKEY_API_KEY"] = FAKE_SECRET  # fake value, only to prove redaction; no model is called
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "mcp_server"))

import agents  # noqa: E402
import audit  # noqa: E402
import config  # noqa: E402
from models import AgentReport  # noqa: E402

DBS = [ROOT / "data" / "campus_customs.db", ROOT / "data" / "campus_customs_new.db"]
results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((ok, label))
    print(("PASS " if ok else "FAIL ") + label)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_rows() -> list[dict]:
    return json.loads(AUDIT.read_text(encoding="utf-8")) if AUDIT.exists() else []


def deps(agent: str, chain: tuple[str, ...], run: agents.TicketRun | None = None) -> agents.TeamDeps:
    return agents.TeamDeps(run=run or agents.TicketRun(run_id="test-run", ticket_id=101), agent=agent, chain=chain)


def check_model_lock() -> None:
    check(config.MODEL_NAME == "gpt-6-luna", "configured model is gpt-6-luna")
    env = {**os.environ, "OPENAI_MODEL": "not-the-assignment-model"}
    proc = subprocess.run([PY, "-c", "import config"], cwd=BACKEND, env=env, capture_output=True, text=True)
    check(proc.returncode != 0 and "must use only 'gpt-6-luna'" in proc.stderr,
          "a different OPENAI_MODEL stops startup (no silent fallback)")
    src = "\n".join(p.read_text(encoding="utf-8") for p in BACKEND.rglob("*.py"))
    dotenv_calls = [ln.strip() for ln in src.splitlines() if ln.strip().startswith("load_dotenv(")]
    check(dotenv_calls == ["load_dotenv(ENV_PATH)"] and config.ENV_PATH == ROOT / ".env" and "ROOT.parent" not in src,
          "backend loads .env only from Homework 5/.env (explicit path)")


async def check_tool_isolation() -> None:
    from fastmcp import Client

    os.environ["CAMPUS_CUSTOMS_DB"] = str(TMP / "unused.db")
    from server import mcp

    async with Client(mcp) as c:
        server_tools = {t.name for t in await c.list_tools()}
    all_allowed = set().union(*agents.AGENT_TOOLS.values())
    check(all_allowed <= server_tools, "every allowlisted tool exists on the MCP server")
    check(agents.BACKEND_ONLY_TOOLS <= server_tools and not (all_allowed & agents.BACKEND_ONLY_TOOLS),
          "execute_approved_request / reject_request are in no agent's toolset")
    requesters = {a for a, t in agents.AGENT_TOOLS.items() if any(n.startswith("request_") for n in t)}
    check(requesters == {"accounting"}, "only Accounting can file approval requests")
    check({a for a, t in agents.AGENT_TOOLS.items() if "update_ticket" in t} == {"boss"},
          "only the Boss can update a ticket")

    calls: list[tuple[str, dict]] = []

    async def fake_call_tool(name, args, **_):
        calls.append((name, args))
        return {"ok": True}

    for agent in agents.AGENT_TOOLS:
        ctx = SimpleNamespace(deps=deps(agent, (agent,)))
        out = await agents._process_tool_call(ctx, fake_call_tool, "execute_approved_request",
                                              {"request_id": 1, "approved_by": "Kate"})
        assert "not allowed" in out["error"], out
    check(calls == [], "process_tool_call blocks payment execution for all five agents")
    ctx = SimpleNamespace(deps=deps("inventory", ("boss", "inventory")))
    out = await agents._process_tool_call(ctx, fake_call_tool, "request_purchase", {"vendor_id": 1})
    check("not allowed" in out["error"] and calls == [], "tool outside an agent's allowlist is refused")
    ctx = SimpleNamespace(deps=deps("accounting", ("boss", "accounting")))
    await agents._process_tool_call(ctx, fake_call_tool, "request_rent_payment",
                                    {"ticket_id": 999, "lease_id": 1, "reason": "x", "requested_by": "boss"})
    check(calls[-1][1]["requested_by"] == "accounting" and calls[-1][1]["ticket_id"] == 101,
          "requested_by and ticket_id are stamped by code, not trusted from the model")
    ctx = SimpleNamespace(deps=deps("boss", ("boss",)))
    await agents._process_tool_call(ctx, fake_call_tool, "update_ticket",
                                    {"ticket_id": 102, "status": "awaiting_approval", "note": "x", "updated_by": "someone"})
    check(calls[-1][1]["updated_by"] == "boss" and calls[-1][1]["ticket_id"] == 101,
          "update_ticket is stamped with the Boss and the current ticket")
    before = len(calls)
    out = await agents._process_tool_call(ctx, fake_call_tool, "update_ticket",
                                          {"ticket_id": 101, "status": " Resolved ", "note": "done", "updated_by": "boss"})
    check(len(calls) == before and out.get("updated") is False and "cannot mark a ticket resolved" in out["error"],
          "agents cannot mark a ticket resolved (only the dashboard can)")
    rows = audit_rows()
    check(sum(r["action"] == "mcp_tool_refused" for r in rows) == 7 and sum(r["action"] == "mcp_tool_call" for r in rows) == 2,
          "refused and allowed MCP calls are both audited")


async def check_delegation() -> None:
    d = deps("boss", ("boss",))
    check(agents.check_delegation(d, "inventory", "Check stock for CC-TEE-WHITE S") is None, "boss -> inventory allowed")
    check("itself" in agents.check_delegation(d, "boss", "x"), "self-delegation refused")
    check("Unknown" in agents.check_delegation(d, "marketing", "x"), "unknown agent refused")
    check("empty" in agents.check_delegation(d, "inventory", "  ?! "), "empty task refused")
    d2 = deps("accounting", ("boss", "inventory", "accounting"))
    check("Circular" in agents.check_delegation(d2, "inventory", "x"), "circular delegation refused (A -> B -> A)")
    check("Circular" in agents.check_delegation(d2, "boss", "x"), "delegating back up to the Boss refused")
    d3 = deps("facilities", ("boss", "inventory", "accounting", "facilities"))
    check("depth" in agents.check_delegation(d3, "customer_service", "x"), "depth limit (3) enforced")
    every = set(agents.AGENT_TOOLS)
    reachable = all(agents.check_delegation(deps(a, (a,)), b, "task") is None for a in every for b in every - {a})
    check(reachable, "full connectivity: every agent can reach every other agent")

    run = agents.TicketRun(run_id="limit-run", ticket_id=103, delegations=config.MAX_DELEGATIONS_PER_TICKET)
    check("Per-ticket" in agents.check_delegation(deps("boss", ("boss",), run), "inventory", "x"),
          "per-ticket delegation limit (8) enforced")

    run = agents.TicketRun(run_id="cache-run", ticket_id=103)
    cached = AgentReport(agent="inventory", summary="8 on hand, 12 short")
    run.seen_tasks[("inventory", agents.normalize_task("Check stock: CC-HOOD-NAVY M x20"))] = cached
    ctx = SimpleNamespace(deps=deps("boss", ("boss",), run), usage=None)
    res = await agents.delegate(ctx, "inventory", "check stock  CC-HOOD-NAVY m x20!")
    check(res.accepted and res.cached and res.report == cached and run.delegations == 0,
          "repeated task returns the earlier report without running the agent again")
    res = await agents.delegate(ctx, "boss", "do it")
    check(not res.accepted and "itself" in res.refusal and run.records[-1].outcome == "refused",
          "refused delegation is returned to the model and recorded")
    acts = [r["action"] for r in audit_rows() if r.get("run_id") == "cache-run"]
    check(acts == ["delegation_cached", "delegation_refused"], "cached and refused delegations are audited")


def check_audit_trail() -> None:
    AUDIT.unlink(missing_ok=True)
    audit.append_event({"run_id": "keep", "action": "existing"})
    threads = [threading.Thread(target=lambda i=i: [audit.append_event({"run_id": f"t{i}", "action": "x", "n": n})
                                                     for n in range(25)]) for i in range(6)]
    code = ("import sys; sys.path.insert(0, r'%s'); import audit\n"
            "for n in range(25): audit.append_event({'run_id': 'p' + sys.argv[1], 'action': 'x', 'n': n})") % BACKEND
    procs = [subprocess.Popen([PY, "-c", code, str(i)], env=os.environ.copy()) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for p in procs:
        p.wait()
    rows = audit_rows()
    check(len(rows) == 1 + 6 * 25 + 3 * 25 and rows[0]["action"] == "existing",
          f"concurrent appends (6 threads + 3 processes): {len(rows)} rows, nothing lost or wiped")
    per_writer = {}
    for r in rows[1:]:
        per_writer.setdefault(r["run_id"], []).append(r["n"])
    check(all(v == list(range(25)) for v in per_writer.values()) and len(per_writer) == 9,
          "every writer's entries are complete and in order")
    check(not list(TMP.glob("*.tmp")) and not list(TMP.glob("*.lock")), "no leftover temp or lock files")

    audit.append_event({"run_id": "secret", "action": "x", "args": {"note": f"key={FAKE_SECRET}"}})
    text = AUDIT.read_text(encoding="utf-8")
    check(FAKE_SECRET not in text and "[REDACTED]" in text, "secret values are redacted from the audit trail")

    AUDIT.write_text("[{broken", encoding="utf-8")
    audit.append_event({"run_id": "after-corrupt", "action": "x"})
    backups = list(TMP.glob("audit_trail.corrupt-*.json"))
    check(len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "[{broken" and len(audit_rows()) == 1,
          "an unreadable trail is preserved as a backup, never overwritten")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def check_http_transport() -> None:
    from fastmcp import Client

    test_db = TMP / "http_copy.db"
    shutil.copyfile(DBS[0], test_db)
    port = free_port()
    env = {**os.environ, "CAMPUS_CUSTOMS_DB": str(test_db), "MCP_PORT": str(port)}
    proc = subprocess.Popen([PY, str(ROOT / "mcp_server" / "server.py"), "--http"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        for _ in range(100):
            try:
                async with Client(url) as c:
                    names = {t.name for t in await c.list_tools()}
                    cash = (await c.call_tool("get_cash_balance", {})).data
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("HTTP MCP server did not start")
        check(len(names) == 15 and cash["cash_accounts"][0]["balance"] == 3400.0,
              f"HTTP transport on 127.0.0.1:{port}: 15 tools, get_cash_balance returns $3,400")
        check(config.MCP_SERVER_URL == "http://127.0.0.1:8001/mcp", "agents default to http://127.0.0.1:8001/mcp")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


async def main() -> None:
    before = [sha256(p) for p in DBS]
    check_model_lock()
    await check_tool_isolation()
    await check_delegation()
    check_audit_trail()
    await check_http_transport()
    check([sha256(p) for p in DBS] == before, "original and working databases unchanged (SHA-256)")


if __name__ == "__main__":
    real_audit = ROOT / "output" / "audit_trail.json"
    real_before = sha256(real_audit) if real_audit.exists() else None
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    real_after = sha256(real_audit) if real_audit.exists() else None
    check(real_before == real_after, "output/audit_trail.json untouched by the tests")
    passed = sum(ok for ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) else 1)
