"""Independent checks of the Problem 9 evidence. No model calls, no writes.

It recomputes everything from the working database and output/audit_trail.json (read-only) and does not
import the generator (tests/build_problem9_outputs.py), so a bug there cannot hide itself here.

- Cash: starting balance (original database) − every payment = cash_accounts, and the Cash tab, the JSON and
  the board all show those figures.
- Approvals: every payment belongs to exactly one executed request, decided by a person (not an agent).
- Tickets: all three are resolved in the database, and the resolution type on record matches the evidence.
- Actual sections: list every real delegation and every MCP tool from each ticket's final run.
- Safety: no agent marked a ticket resolved, exactly one reset in the simulation, and every run completed.
- resolved_board.html: a genuine screenshot per resolved ticket, embedded byte for byte, with no external files.
- harness.md: covers tables, MCP tools, the five agents, API routes, the dashboard and safety rules.

Run: .venv/Scripts/python.exe tests/check_problem9_outputs.py
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKING = ROOT / "data" / "campus_customs_new.db"
ORIGINAL = ROOT / "data" / "campus_customs.db"
ORIGINAL_SHA256 = "23686a90d698f7fa6f901a3f0a9774db9cbb31e13151c9e5717275f3321f360a"
AGENTS = {"boss", "inventory", "accounting", "facilities", "customer_service"}
CHAR = {"boss": "Mario", "inventory": "Crash", "accounting": "Spyro", "facilities": "Ryu", "customer_service": "Sonic"}
RESOLVED_SHOTS = {101: "04_ticket101_resolved_administrative.jpg", 102: "02_ticket102_resolved.jpg",
                  103: "07_ticket103_resolved_administrative.jpg"}

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))


def money(x: float) -> str:
    return f"${x:,.2f}"


def text(fragment: str) -> str:
    fragment = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->", " ", fragment, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def main() -> int:
    trail = json.loads((ROOT / "output" / "audit_trail.json").read_text(encoding="utf-8"))
    resets = [i for i, e in enumerate(trail) if e.get("action") == "database_reset"]
    check(len(resets) == 1, f"exactly one database reset in the trail (entry {resets[-1] if resets else '-'})")
    r0 = resets[-1]
    sim = trail[r0:]

    con = sqlite3.connect(f"file:{WORKING.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = lambda sql: [dict(r) for r in con.execute(sql)]  # noqa: E731
    tickets = {t["id"]: t for t in rows("SELECT id, status FROM tickets")}
    reqs = rows("SELECT * FROM approval_requests ORDER BY id")
    pays = rows("SELECT * FROM payments ORDER BY id")
    end = con.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()[0]
    con.close()
    ocon = sqlite3.connect(f"file:{ORIGINAL.as_posix()}?mode=ro", uri=True)
    start = ocon.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()[0]
    ocon.close()
    paid = round(sum(p["amount"] for p in pays), 2)

    # --- cash and approvals (database) ---
    check(round(start - paid, 2) == round(end, 2), f"cash reconciles: {money(start)} − {money(paid)} = {money(end)}")
    for p in pays:
        owners = [r for r in reqs if r["payment_id"] == p["id"]]
        check(len(owners) == 1 and owners[0]["status"] == "executed" and round(owners[0]["amount"], 2) == round(p["amount"], 2),
              f"payment {p['id']} ({money(p['amount'])}) belongs to exactly one executed request")
        check(p["approved_by"] not in AGENTS and owners and owners[0]["decided_by"] == p["approved_by"],
              f"payment {p['id']} approved by a person ({p['approved_by']})")
    check(all(r["decided_by"] and r["decided_by"].lower().replace(" ", "_") not in AGENTS for r in reqs if r["status"] != "pending"),
          "every decided request was decided by a person, not an agent")
    check(not [r for r in reqs if r["status"] == "pending"], "no request is left pending")
    check(all(tickets[t]["status"] == "resolved" for t in (101, 102, 103)), "tickets 101, 102 and 103 are resolved in the database")

    # --- safety in the audit trail ---
    agent_resolves = [e for e in sim if e.get("action") == "mcp_tool_call" and e.get("tool") == "update_ticket"
                      and str((e.get("args") or {}).get("status", "")).lower() == "resolved"]
    check(not agent_resolves, "no agent marked a ticket resolved")
    resolved_ev = {e["ticket_id"]: e for e in sim if e.get("action") == "ticket_updated" and e.get("status") == "resolved"}
    check(set(resolved_ev) == {101, 102, 103} and all(e.get("updated_by") not in AGENTS for e in resolved_ev.values()),
          "each resolution was recorded by a person or the backend rule")
    runs = {}
    for i, e in enumerate(trail):
        if i >= r0 and e.get("action") == "run_started":
            runs[e["run_id"]] = {"ticket": e["ticket_id"], "start": i}
        if i >= r0 and e.get("action") == "run_finished" and e.get("run_id") in runs:
            runs[e["run_id"]]["status"] = e.get("status")
    check(runs and all(r.get("status") == "completed" for r in runs.values()), f"all {len(runs)} runs after the reset completed")
    check(all(e.get("model") == "gpt-6-luna" for e in sim if e.get("action") == "run_started"), "every run requested gpt-6-luna")

    # --- resolved_tickets.json ---
    doc = json.loads((ROOT / "output" / "resolved_tickets.json").read_text(encoding="utf-8"))
    jt = {t["id"]: t for t in doc["tickets"]}
    check(set(jt) == {101, 102, 103}, "resolved_tickets.json has tickets 101, 102 and 103")
    check(doc["cash"]["starting_balance"] == start and doc["cash"]["ending_balance"] == end and doc["cash"]["total_paid"] == paid,
          "resolved_tickets.json cash figures match the database")
    for tid in (101, 102, 103):
        t = jt[tid]
        check(t["final_status"] == tickets[tid]["status"], f"{tid}: final_status matches the database")
        check(t["resolution_type"] == resolved_ev[tid].get("resolution_type"), f"{tid}: resolution_type matches the audit trail")
        db_reqs = [(r["id"], r["kind"], r["amount"], r["status"], r["decided_by"]) for r in reqs if r["ticket_id"] == tid]
        js_reqs = [(a["request_id"], a["kind"], a["amount"], a["status"], a["decided_by"]) for a in t["human_approvals"]]
        check(db_reqs == js_reqs, f"{tid}: human approvals match approval_requests")
        check(all(a["contribution"] for a in t["agents"]), f"{tid}: every agent that ran has its contribution recorded")
        if t["resolution_type"] == "administrative":
            check(len(t["outstanding"]) >= 1, f"{tid}: an administrative resolution lists what is still outstanding")
        if t.get("customer_reply_draft"):
            check(t["customer_reply_draft"]["sent"] is False, f"{tid}: the customer reply is recorded as a draft, not sent")
    check(any(r["superseded"] for r in jt[103]["runs"]) and len(jt[103]["runs"]) == 2, "103 records both runs, the first marked superseded")

    # --- desk_tickets.html: Actual sections and Cash tab ---
    page = (ROOT / "output" / "desk_tickets.html").read_text(encoding="utf-8")
    for tid in (101, 102, 103):
        final = max((r for r in runs.items() if r[1]["ticket"] == tid), key=lambda kv: kv[1]["start"])[0]
        evs = [e for e in sim if e.get("run_id") == final]
        dels = []
        for e in evs:
            if e.get("action") == "delegation_started":
                m = re.search(r"""["']to_agent["']\s*:\s*["'](\w+)["']""", json.dumps(e.get("delegation")) if not isinstance(e.get("delegation"), str) else e["delegation"])
                dels.append((e["agent"], m.group(1)))
        tools = {e["tool"] for e in evs if e.get("action") == "mcp_tool_call"}
        act = re.search(rf'data-actual="{tid}".*?</dl>', page, re.S)
        act_text = text(act.group(0)) if act else ""
        check(all(f"{CHAR[a]} ({ROLE_OF[a]}) → {CHAR[b]} ({ROLE_OF[b]})" in act_text for a, b in dels),
              f"{tid}: Actual lists every real delegation ({len(dels)})")
        check(all(tool in act_text for tool in tools), f"{tid}: Actual lists every MCP tool used ({len(tools)})")
    cash_panel = re.search(r'<section class="panel" role="tabpanel" id="panel-cash".*?(?=<!-- =+ |</main>)', page, re.S).group(0)
    cash_text = text(cash_panel)
    check(all(money(p["amount"]) in cash_text for p in pays) and money(end) in cash_text and money(start) in cash_text,
          "Cash tab itemizes every payment and shows the start and end balances")

    # --- resolved_board.html ---
    board = (ROOT / "output" / "resolved_board.html").read_text(encoding="utf-8")
    imgs = re.findall(r'src="data:image/jpeg;base64,([^"]+)"', board)
    shots = {tid: (ROOT / "docs" / "problem9_screenshots" / name).read_bytes() for tid, name in RESOLVED_SHOTS.items()}
    decoded = [base64.b64decode(b) for b in imgs]
    check(all(s in decoded for s in shots.values()), "resolved_board.html embeds each resolved-ticket screenshot byte for byte")
    check(not re.search(r'(src|href)="(?!data:)[^"#]', board) and "<link" not in board and "<script src" not in board,
          "resolved_board.html loads no external files")
    check(all(f"Ticket {tid}" in board for tid in (101, 102, 103)) and money(end) in board, "resolved_board.html covers all three tickets and the ending balance")

    # --- harness.md ---
    harness = (ROOT / "output" / "harness.md").read_text(encoding="utf-8")
    for heading in ("## Tables", "## MCP tools", "## The five agents", "## Backend API routes", "## The dashboard", "## Safety",
                    "## Verified full run (Problem 9)"):
        check(heading in harness, f"harness.md has a '{heading.lstrip('# ')}' section")

    # --- original database ---
    check(hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == ORIGINAL_SHA256, "original database unchanged (pinned SHA-256)")

    failed = [label for ok, label in results if not ok]
    for ok, label in results:
        print(("PASS " if ok else "FAIL ") + label)
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


ROLE_OF = {"boss": "Boss", "inventory": "Inventory", "accounting": "Accounting", "facilities": "Facilities",
           "customer_service": "Customer Service"}

if __name__ == "__main__":
    sys.exit(main())
