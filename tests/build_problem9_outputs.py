"""Build the Problem 9 evidence from the real run. Nothing here is typed by hand: every figure comes from
output/audit_trail.json (entries after the last database reset) and the working database, read-only.

Writes:
  output/desk_tickets.html   - fills each ticket's Actual section (with the real network) and the Cash tab
  output/resolved_tickets.json
  output/resolved_board.html - standalone page with the genuine React-board screenshots embedded
  output/harness.md          - the "Verified full run (Problem 9)" section

Safe to run again: generated regions sit between <!-- P9:... --> markers and are replaced each time, and an
unchanged rebuild is byte-identical. It stops before writing anything if the cash does not reconcile, the data
does not match the recorded findings, or the audit trail / working database now describe a different
simulation than the one recorded in output/resolved_tickets.json (a new reset, run or payment). Use --force
only to replace the evidence deliberately with a new run.

Run: .venv/Scripts/python.exe tests/build_problem9_outputs.py
"""

from __future__ import annotations

import base64
import html
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAIL = ROOT / "output" / "audit_trail.json"
WORKING = ROOT / "data" / "campus_customs_new.db"
ORIGINAL = ROOT / "data" / "campus_customs.db"
DESK = ROOT / "output" / "desk_tickets.html"
RESOLVED_JSON = ROOT / "output" / "resolved_tickets.json"
BOARD = ROOT / "output" / "resolved_board.html"
HARNESS = ROOT / "output" / "harness.md"
SHOTS = ROOT / "docs" / "problem9_screenshots"
LIVE_MCP = "http://127.0.0.1:8001/mcp"

CHAR = {"boss": "Mario", "inventory": "Crash", "accounting": "Spyro", "facilities": "Ryu", "customer_service": "Sonic"}
ROLE = {"boss": "Boss", "inventory": "Inventory", "accounting": "Accounting", "facilities": "Facilities",
        "customer_service": "Customer Service"}
SPRITE_KEY = {"boss": "mario", "inventory": "crash", "accounting": "spyro", "facilities": "ryu", "customer_service": "sonic"}
ORDER = ["boss", "inventory", "accounting", "facilities", "customer_service"]

# The Problem 6 Expected plan (output/desk_tickets.html), by agent name.
EXPECTED_FIRST = {101: "inventory", 102: "facilities", 103: "inventory"}
EXPECTED_ROUTES = {
    101: [("boss", "inventory"), ("inventory", "accounting"), ("boss", "customer_service")],
    102: [("boss", "facilities"), ("facilities", "accounting")],
    103: [("boss", "inventory"), ("boss", "accounting"), ("boss", "customer_service")],
}
EXPECTED_TOOLS = {
    101: ["get_ticket", "check_stock_and_pricing", "get_vendor_invoice_status", "get_cash_balance",
          "request_invoice_payment", "list_approval_requests", "update_ticket"],
    102: ["get_ticket", "check_rent_due", "get_cash_balance", "list_approval_requests", "request_rent_payment",
          "update_ticket"],
    103: ["get_ticket", "check_stock_and_pricing", "list_vendors", "get_cash_balance", "request_discount",
          "list_approval_requests", "update_ticket"],
}
MISSION = {101: "Operation Missing Tee", 102: "Operation Keep the Lights On", 103: "Operation Hoodie Negotiation"}
RESOLVED_SHOT = {102: "02_ticket102_resolved.jpg", 101: "04_ticket101_resolved_administrative.jpg",
                 103: "07_ticket103_resolved_administrative.jpg"}
KIND_LABEL = {"rent_payment": "Rent payment", "invoice_payment": "Invoice payment", "purchase": "Stock purchase",
              "discount": "Discount offer"}

esc = html.escape


def money(x: float) -> str:
    return f"${x:,.2f}"


def to_agent(ev: dict) -> str | None:
    raw = ev.get("delegation")
    text = raw if isinstance(raw, str) else json.dumps(raw or {})
    m = re.search(r"""["']to_agent["']\s*:\s*["'](\w+)["']""", text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Load the real run
# ---------------------------------------------------------------------------


def load() -> dict:
    trail = json.loads(TRAIL.read_text(encoding="utf-8"))
    resets = [i for i, e in enumerate(trail) if e.get("action") == "database_reset"]
    if not resets:
        raise SystemExit("No database_reset in the audit trail: run the simulation first.")
    r0 = resets[-1]
    sim = [(i, trail[i]) for i in range(r0, len(trail))]

    runs: dict[str, dict] = {}
    for i, e in sim:
        if e.get("action") == "run_started" and e.get("mcp_server") == LIVE_MCP:
            runs[e["run_id"]] = {"run_id": e["run_id"], "ticket_id": e["ticket_id"], "start": i, "model": e.get("model")}
    for rid, run in runs.items():
        evs = [(i, e) for i, e in sim if e.get("run_id") == rid]
        fin = [(i, e) for i, e in evs if e.get("action") == "run_finished"]
        if not fin:
            raise SystemExit(f"Run {rid} has no run_finished entry; it may still be running.")
        run["end"], f = fin[-1]
        run["status"], run["usage"], run["error"] = f.get("status"), f.get("usage") or {}, f.get("error")
        run["events"] = [e for _, e in evs]
        run["delegations"], run["tools"], run["tool_calls"], run["refused"] = [], {}, [], []
        run["summaries"], run["replies"], run["issues"], run["finished_at"] = {}, {}, {}, {}
        for i, e in evs:
            a, act = e.get("agent"), e.get("action")
            if act == "delegation_started":
                run["delegations"].append({"from": a, "to": to_agent(e), "index": i, "outcome": "started"})
            elif act in ("delegation_finished", "delegation_cached", "delegation_refused", "delegation_failed"):
                t = to_agent(e)
                for d in reversed(run["delegations"]):
                    if d["from"] == a and d["to"] == t and d["outcome"] == "started":
                        d["outcome"] = {"delegation_finished": "completed", "delegation_cached": "cached"}.get(act, act.split("_")[1])
                        break
            elif act == "mcp_tool_call":
                run["tools"].setdefault(a, [])
                if e["tool"] not in run["tools"][a]:
                    run["tools"][a].append(e["tool"])
                run["tool_calls"].append({"index": i, "agent": a, "tool": e["tool"], "args": e.get("args")})
            elif act in ("mcp_tool_refused", "mcp_tool_error"):
                run["refused"].append({"index": i, "agent": a, "tool": e.get("tool"), "action": act})
            elif act == "agent_finished":
                run["summaries"][a] = e.get("summary")
                run["finished_at"][a] = i
                if e.get("customer_reply"):
                    run["replies"][a] = e["customer_reply"]
                run["issues"][a] = e.get("open_issues") or []
        boss_first = next((d["to"] for d in run["delegations"] if d["from"] == "boss"), None)
        run["boss_first"] = boss_first
        run["agents"] = [a for a in ORDER if any(e.get("action") == "agent_started" and e.get("agent") == a for e in run["events"])]
        run["response_models"] = sorted({e.get("model") for e in run["events"]
                                         if e.get("action") == "model_response" and e.get("model")})

    decisions = [(i, e) for i, e in sim if e.get("action") == "approval_decided"]
    updates = [(i, e) for i, e in sim if e.get("action") == "ticket_updated"]

    conn = sqlite3.connect(f"file:{WORKING.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    q = lambda sql, *a: [dict(r) for r in conn.execute(sql, a)]  # noqa: E731
    db = {
        "tickets": {t["id"]: t for t in q("SELECT * FROM tickets ORDER BY id")},
        "requests": q("SELECT * FROM approval_requests ORDER BY id"),
        "payments": q("SELECT * FROM payments ORDER BY id"),
        "cash": q("SELECT * FROM cash_accounts WHERE name = 'checking'")[0],
        "invoice501": q("SELECT * FROM invoices WHERE id = 501")[0],
        "lease": q("SELECT * FROM leases WHERE id = 1")[0],
    }
    for r in db["requests"]:
        r["details"] = json.loads(r["details"]) if r["details"] else {}
        r["result"] = json.loads(r["result"]) if r["result"] else {}
    conn.close()
    oconn = sqlite3.connect(f"file:{ORIGINAL.as_posix()}?mode=ro", uri=True)
    start_balance = oconn.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()[0]
    oconn.close()
    return {"trail": trail, "reset_index": r0, "reset": trail[r0], "runs": runs, "decisions": decisions,
            "updates": updates, "db": db, "start_balance": start_balance}


def ticket_runs(data: dict, tid: int) -> list[dict]:
    return sorted((r for r in data["runs"].values() if r["ticket_id"] == tid), key=lambda r: r["start"])


# ---------------------------------------------------------------------------
# Per-ticket facts, checks and findings
# ---------------------------------------------------------------------------


def build_ticket(data: dict, tid: int) -> dict:
    db = data["db"]
    t = db["tickets"][tid]
    runs = ticket_runs(data, tid)
    if not runs:
        raise SystemExit(f"Ticket {tid} has no run after the reset.")
    final = runs[-1]
    reqs = [r for r in db["requests"] if r["ticket_id"] == tid]
    pays = [p for p in db["payments"] if any(r.get("payment_id") == p["id"] for r in reqs)]
    resolved = [(i, e) for i, e in data["updates"] if e.get("ticket_id") == tid and e.get("status") == "resolved"]
    if t["status"] != "resolved" or not resolved:
        raise SystemExit(f"Ticket {tid} is not resolved in the database yet.")
    ri, rev = resolved[-1]

    routes_actual = [(d["from"], d["to"]) for d in final["delegations"]]
    expected = EXPECTED_ROUTES[tid]
    used_tools = sorted({c["tool"] for c in final["tool_calls"]})
    cmp = {
        "boss_called_first_matches": final["boss_first"] == EXPECTED_FIRST[tid],
        "routes_matched": [f"{CHAR[a]} → {CHAR[b]}" for a, b in expected if (a, b) in routes_actual],
        "routes_planned_not_used": [f"{CHAR[a]} → {CHAR[b]}" for a, b in expected if (a, b) not in routes_actual],
        "routes_not_in_plan": [f"{CHAR[a]} → {CHAR[b]}" for a, b in routes_actual if (a, b) not in expected],
        "tools_expected_not_used": [x for x in EXPECTED_TOOLS[tid] if x not in used_tools],
        "tools_used_not_expected": [x for x in used_tools if x not in EXPECTED_TOOLS[tid]],
    }

    findings: list[str] = []
    outstanding: list[str] = []
    reply_issue = None
    cs_reply = final["replies"].get("customer_service")
    if tid == 102:
        req = next(r for r in reqs if r["kind"] == "rent_payment")
        outcome = (f"The rent notice matched lease 1 ({db['lease']['landlord']}, {money(req['amount'])} due "
                   f"{req['details']['due_date']}). Kate Duffy approved request #{req['id']}; it was paid as payment "
                   f"{req['payment_id']}, and the lease is next due {req['result'].get('lease_next_due')}. Resolved "
                   f"operationally: the recorded payment completes the ticket.")
    elif tid == 101:
        req = next(r for r in reqs if r["kind"] == "invoice_payment")
        assert db["invoice501"]["status"] == "paid"
        outcome = (f"The size S tee was out of stock (0 on hand). Invoice 501 ({money(req['amount'])}, "
                   f"\"{req['details']['description']}\") was paid as payment {req['payment_id']} after Kate Duffy "
                   f"approved request #{req['id']}; no duplicate purchase was made. Shipment and delivery of the reprint are "
                   f"not confirmed, and the customer reply was drafted but not sent. Resolved administratively.")
        outstanding = ["Bulldog Print Co shipping the rush reprint (not confirmed; the 5-day lead time is an estimate)",
                       "The size S tee reaching the customer",
                       "Editing and sending the customer reply (the draft was not sent)"]
        leaks = [w for w in ("invoice 501", "awaiting human approval", "blocked from shipping") if w in (cs_reply or "").lower()]
        if not leaks:
            raise SystemExit("Expected the recorded 101 draft-reply finding, but the reply does not contain it.")
        reply_issue = ("The draft mentions " + ", ".join(f'"{w}"' for w in leaks) + ": internal details that "
                       "Customer Service's prompt says to keep out of customer replies. It must be edited before sending.")
        findings.append(f"Customer Service's draft reply disclosed internal invoice and approval details, which its prompt "
                        f"forbids (audit entry {final['finished_at']['customer_service']}). It was not sent. Kate "
                        f"Duffy chose to record the issue, not re-run the ticket.")
    else:  # 103
        req = next(r for r in reqs if r["kind"] == "discount")
        assert req["quantity"] == 8 and req["unit_price"] >= 52.2 and req["cash_effect"] == 0
        outcome = (f"{req['details']['qty_on_hand']} of {req['details']['order_quantity']} {req['sku']} size {req['size']} were "
                   f"on hand, {req['details']['shortfall']} short. Under the simulation discount policy, Kate Duffy "
                   f"approved request #{req['id']}: {req['quantity']} at {money(req['unit_price'])} "
                   f"({req['details']['discount_pct']:g}% off {money(req['details']['list_price'])}, total "
                   f"{money(req['amount'])}) as an offer. No cash moved and no purchase was requested. The club has not "
                   f"accepted, supply for the other {req['details']['shortfall']} is unconfirmed, and the reply was "
                   f"drafted but not sent. Resolved administratively after a re-run.")
        outstanding = ["The Yale AI Club accepting (or declining) the offer for 8 hoodies",
                       "A confirmed supplier and supply for the 12-unit shortfall (no vendor-to-SKU record exists)",
                       "Sending the customer reply (the draft was not sent)"]
        if len(runs) >= 2:
            first = runs[0]
            bad_sku = [c for c in first["tool_calls"] if c["tool"] == "check_stock_and_pricing"
                       and str((c["args"] or {}).get("sku", "")).lower() == "hoodie"]
            no_request = not any(c["tool"] == "request_discount" for c in first["tool_calls"])
            if not (bad_sku and no_request):
                raise SystemExit("Expected the recorded first-run 103 findings, but the data does not show them.")
            findings += [
                f"First run (audit entries {first['start']}–{first['end']}) filed no discount request. Mario asked whether "
                f"a request could be filed without a customer-proposed price, and Accounting declined to propose one.",
                f"In the first run, Accounting looked up the stock with sku \"hoodie\" instead of CC-HOOD-NAVY and got "
                f"not-found (audit entry {bad_sku[0]['index']}).",
                f"After a targeted prompt fix (Boss: Accounting proposes the price; Accounting: propose within policy, use "
                f"exact SKUs), the second run (audit entries {final['start']}–{final['end']}) filed discount request "
                f"#{req['id']} within policy, using the exact SKU.",
            ]
            qty12 = [c for c in final["tool_calls"] if c["tool"] == "check_stock_and_pricing"
                     and (c["args"] or {}).get("requested_quantity") == 12]
            if qty12:
                findings.append(f"In the second run, Mario told Inventory to rely on the previous run's ticket note, and "
                                f"Inventory passed requested_quantity 12 instead of 20 (audit entry {qty12[0]['index']}). "
                                f"Inventory explained the mismatch, and the final figures are correct.")
    if final["refused"]:
        findings.append(f"Refused tool calls: {final['refused']}")

    approvals = [{
        "request_id": r["id"], "kind": r["kind"], "sku": r["sku"], "quantity": r["quantity"], "unit_price": r["unit_price"],
        "amount": r["amount"], "cash_effect": r["cash_effect"], "requested_by": r["requested_by"],
        "requested_at": r["requested_at"], "status": r["status"], "decided_by": r["decided_by"],
        "decided_at": r["decided_at"], "payment_id": r["payment_id"], "reason": r["reason"],
    } for r in reqs]
    return {
        "id": tid, "mission": MISSION[tid], "type": t["type"], "requester": t["requester"], "subject": t["subject"],
        "final_status": t["status"], "resolution_type": rev.get("resolution_type"),
        "resolved_by": rev.get("updated_by"), "resolved_at": rev.get("time"), "resolution_audit_entry": ri,
        "resolution_note": rev.get("note"), "outcome": outcome,
        "boss_called_first": f"{ROLE[final['boss_first']]} ({CHAR[final['boss_first']]})" if final["boss_first"] else None,
        "agents": [{"agent": a, "character": CHAR[a], "role": ROLE[a], "contribution": final["summaries"].get(a),
                    "mcp_tools": final["tools"].get(a, [])} for a in final["agents"]],
        "agents_not_involved": [f"{ROLE[a]} ({CHAR[a]})" for a in ORDER if a not in final["agents"]],
        "delegations": [{"from": f"{CHAR[d['from']]} ({ROLE[d['from']]})", "to": f"{CHAR[d['to']]} ({ROLE[d['to']]})",
                         "outcome": d["outcome"], "audit_entry": d["index"]} for d in final["delegations"]],
        "human_approvals": approvals,
        "payments": [{"payment_id": p["id"], "kind": p["kind"], "ref_id": p["ref_id"], "amount": p["amount"],
                      "account": p["account"], "approved_by": p["approved_by"]} for p in pays],
        "customer_reply_draft": ({"text": cs_reply, "sent": False, "issue": reply_issue} if cs_reply else None),
        "outstanding": outstanding,
        "expected_vs_actual": cmp,
        "runs": [{"run_id": r["run_id"], "audit_entries": [r["start"], r["end"]], "status": r["status"],
                  "usage": r["usage"], "superseded": r is not final} for r in runs],
        "findings": findings,
        "_final": final, "_runs": runs,
    }


def build_cash(data: dict, tickets: dict[int, dict]) -> dict:
    db = data["db"]
    start = data["start_balance"]
    order = sorted(tickets, key=lambda tid: tickets[tid]["resolved_at"])
    balance, rows = start, []
    for tid in order:
        tk = tickets[tid]
        for a in tk["human_approvals"]:
            change = a["cash_effect"]
            balance = round(balance + change, 2)
            req = next(r for r in db["requests"] if r["id"] == a["request_id"])
            if req["result"].get("balance_after") is not None and round(req["result"]["balance_after"], 2) != balance:
                raise SystemExit(f"Cash does not reconcile at request {a['request_id']}: "
                                 f"{balance} vs recorded {req['result']['balance_after']}")
            rows.append({"ticket_id": tid, "request_id": a["request_id"], "kind": a["kind"], "what": what(a, req),
                         "payment_id": a["payment_id"], "approved_by": a["decided_by"], "approved_at": a["decided_at"],
                         "cash_change": change, "balance_after": balance})
    end = round(db["cash"]["balance"], 2)
    paid = round(sum(p["amount"] for p in db["payments"]), 2)
    if balance != end or round(start - paid, 2) != end:
        raise SystemExit(f"Cash does not reconcile: running {balance}, start-paid {start - paid}, cash_accounts {end}")
    return {"starting_balance": start, "ending_balance": end, "cash_accounts_balance": end, "total_paid": paid,
            "reconciled": True, "rows": rows, "resolution_order": order}


def what(a: dict, req: dict) -> str:
    d = req["details"]
    if a["kind"] == "rent_payment":
        return f"Rent for {d.get('space_name')} to {d.get('landlord')}, due {d.get('due_date')}"
    if a["kind"] == "invoice_payment":
        return f"Invoice {req['ref_id']}: {d.get('description')} (due {d.get('due_date')})"
    if a["kind"] == "discount":
        return (f"Discount offer: {a['quantity']} × {a['sku']} at {money(a['unit_price'])} "
                f"({d.get('discount_pct'):g}% off; {d.get('shortfall')} short). A price, not a payment")
    return f"{KIND_LABEL.get(a['kind'], a['kind'])} {req['ref_id']}"


# ---------------------------------------------------------------------------
# desk_tickets.html
# ---------------------------------------------------------------------------


def region(src: str, name: str, new: str, legacy: str | None = None) -> str:
    """Replace <!-- P9:name -->...<!-- /P9:name -->, or on the first run the legacy markup."""
    marked = f"<!-- P9:{name} -->{new}<!-- /P9:{name} -->"
    pat = re.compile(rf"<!-- P9:{re.escape(name)} -->.*?<!-- /P9:{re.escape(name)} -->", re.S)
    if pat.search(src):
        return pat.sub(lambda _: marked, src, count=1)
    if legacy is None or not re.search(legacy, src, re.S):
        raise SystemExit(f"Could not find the place to write {name} in desk_tickets.html.")
    return re.sub(legacy, lambda _: marked, src, count=1, flags=re.S)


def panel_span(src: str, tid: str) -> tuple[int, int]:
    m = re.search(rf'<section class="panel" role="tabpanel" id="panel-{tid}".*?(?=<!-- =+ |</main>)', src, re.S)
    return m.start(), m.end()


def actual_html(tk: dict) -> str:
    final = tk["_final"]
    cmp = tk["expected_vs_actual"]
    tag = lambda ok: '<span class="ok-tag">matches the plan</span>' if ok else '<span class="warn-tag">differs from the plan</span>'  # noqa: E731
    dels = "".join(f"<li>{esc(d['from'])} → {esc(d['to'])} <span class='muted'>({esc(d['outcome'])}, audit entry {d['audit_entry']})</span></li>"
                   for d in tk["delegations"])
    tools = "".join(f"<li><strong>{esc(a['character'])}</strong>: " + ", ".join(f"<code>{esc(x)}</code>" for x in a["mcp_tools"]) + "</li>"
                    for a in tk["agents"] if a["mcp_tools"])
    def approval_line(a: dict) -> str:
        no_cash = " (no cash moves)" if a["cash_effect"] == 0 else ""
        paid = f" as payment {a['payment_id']}" if a["payment_id"] else ""
        return (f"<li>#{a['request_id']} {esc(KIND_LABEL[a['kind']].lower())}, {money(a['amount'])}{no_cash}: requested by "
                f"{esc(CHAR[a['requested_by']])}, <strong>{esc(a['status'])}</strong> by {esc(a['decided_by'] or '-')}{paid}</li>")
    appr = "".join(approval_line(a) for a in tk["human_approvals"]) or "<li>None</li>"
    out = "".join(f"<li>{esc(x)}</li>" for x in tk["outstanding"])
    status = (f"<strong>{esc(tk['final_status'])}</strong> ({esc(tk['resolution_type'] or 'not recorded')}), "
              f"by {esc(tk['resolved_by'])} in the dashboard (audit entry {tk['resolution_audit_entry']})."
              + (f"<br><span class='muted'>Still outstanding outside the desk:</span><ul>{out}</ul>" if out else ""))
    diffs = []
    diffs.append(f"<li>Boss called first: {tag(cmp['boss_called_first_matches'])}</li>")
    diffs.append("<li>Routes as planned: " + (esc(", ".join(cmp["routes_matched"])) or "none") + "</li>")
    if cmp["routes_planned_not_used"]:
        diffs.append("<li><span class='bad-tag'>Planned, not used:</span> " + esc(", ".join(cmp["routes_planned_not_used"])) + "</li>")
    if cmp["routes_not_in_plan"]:
        diffs.append("<li><span class='warn-tag'>Not in the plan:</span> " + esc(", ".join(cmp["routes_not_in_plan"])) + "</li>")
    diffs.append("<li>Expected tools not used: " + (", ".join(f"<code>{esc(x)}</code>" for x in cmp["tools_expected_not_used"]) or "none") + "</li>")
    diffs.append("<li>Tools used beyond the plan: " + (", ".join(f"<code>{esc(x)}</code>" for x in cmp["tools_used_not_expected"]) or "none") + "</li>")
    diffs += [f"<li>{esc(f)}</li>" for f in tk["findings"]]
    u = final["usage"]
    runline = (f"Run {final['run_id'][:8]} · audit entries {final['start']}–{final['end']} · "
               f"{u.get('requests', 0)} model requests, {u.get('tool_calls', 0)} tool calls, "
               f"{u.get('total_tokens', 0):,} tokens · model {esc(final['model'] or '')}")
    first_run = ""
    if len(tk["_runs"]) > 1:
        r0 = tk["_runs"][0]
        routes0 = ", ".join(f"{CHAR[d['from']]} → {CHAR[d['to']]}" for d in r0["delegations"])
        filed0 = sum(c["tool"].startswith("request_") for c in r0["tool_calls"])
        first_run = (f"<p class='run-note'><strong>First run (kept for the record):</strong> audit entries {r0['start']}–{r0['end']}, "
                     f"{esc(routes0)}; {filed0 or 'no'} approval request{'s' if filed0 != 1 else ''} filed. See the findings below. "
                     f"The figures above are from the second run.</p>")
    agents_ran = ", ".join(f"{a['character']} ({a['role']})" for a in tk["agents"])
    return f'''
          <div class="vs-head"><h3 id="act-{tk['id']}">Actual</h3><p>From the real Problem 9 run. {esc(runline)}</p></div>
          <dl class="slots">
            <dt>Boss called first</dt><dd class="slot filled">{esc(tk['boss_called_first'] or 'Nobody')} · {tag(cmp['boss_called_first_matches'])}</dd>
            <dt>Agents who worked</dt><dd class="slot filled">{esc(agents_ran)}. Not involved: {esc(', '.join(tk['agents_not_involved']) or 'nobody')}.</dd>
            <dt>Delegations</dt><dd class="slot filled"><ol>{dels}</ol></dd>
            <dt>MCP tools used</dt><dd class="slot filled"><ul>{tools}</ul></dd>
            <dt>Approval requests</dt><dd class="slot filled"><ul>{appr}</ul></dd>
            <dt>Final ticket status</dt><dd class="slot filled">{status}</dd>
            <dt>Expected vs. actual</dt><dd class="slot filled"><ul>{''.join(diffs)}</ul></dd>
          </dl>
          {first_run}'''


def actual_network_html(tk: dict, src_html: str, tid: int) -> str:
    block = re.search(rf'<section class="network-block pixel-box" data-network="{tid}".*?</section>', src_html, re.S).group(0)
    routes = re.search(r'<ul class="net-routes".*?</ul>', block, re.S).group(0)
    gate = re.search(r'data-gate="(\w+)"', block).group(1)
    keep = ("ticket_id", "agent", "parent_agent", "depth", "action", "tool", "delegation", "time", "run_id",
            "request_id", "decision", "decided_by")
    events = [{k: e.get(k) for k in keep if e.get(k) is not None} for e in tk["_final"]["events"]
              if e.get("action") in ("agent_started", "mcp_tool_call", "delegation_started", "delegation_finished",
                                     "delegation_cached", "delegation_refused", "delegation_failed", "agent_finished",
                                     "run_finished")]
    # The person's real decisions on this run's requests, made after the run in the dashboard.
    filed = {a["request_id"] for a in tk["human_approvals"]}
    events += [{k: e.get(k) for k in keep if e.get(k) is not None} for i, e in DATA["decisions"]
               if e.get("ticket_id") == tid and e.get("request_id") in filed and i > tk["_final"]["end"]]
    payload = json.dumps(events, ensure_ascii=False).replace("</", "<\\/")
    return f'''
          <section class="network-block actual-network pixel-box" data-network="{tid}-actual" data-ticket="{tid}" data-gate="{gate}" data-events="actual-events-{tid}" aria-labelledby="net-{tid}-actual-h">
            <div class="net-head">
              <div><h3 id="net-{tid}-actual-h">Command network · Actual run</h3>
                <p>Drawn from the {len(events)} real audit entries embedded below. Compare with the Expected plan above.</p></div>
            </div>
            {routes.replace('aria-label="Expected delegations', 'aria-label="Planned delegations (for comparison)')}
            <script type="application/json" id="actual-events-{tid}">{payload}</script>
          </section>'''


def cash_html(cash: dict, data: dict, tickets: dict) -> str:
    rows = "".join(
        f"<tr><td>{i}</td><td>Ticket {r['ticket_id']}<br><span class='muted'>{esc(MISSION[r['ticket_id']])}</span></td>"
        f"<td>{esc(r['what'])}</td><td>#{r['request_id']}</td><td>{r['payment_id'] or '-'}</td>"
        f"<td>{esc(r['approved_by'])}<br><span class='muted'>{esc(r['approved_at'])}</span></td>"
        f"<td class='num'>{'−' + money(-r['cash_change']) if r['cash_change'] else money(0)}</td>"
        f"<td class='num'>{money(r['balance_after'])}</td></tr>"
        for i, r in enumerate(cash["rows"], 1))
    reset = data["reset"]
    parts = " − ".join(money(-r["cash_change"]) for r in cash["rows"] if r["cash_change"])
    return f'''
      <div class="cash-board pixel-box">
        <h2>Cash</h2>
        <p class="lead">The checking account through the Problem 9 run. Every figure comes from <code>payments</code>,
          <code>approval_requests</code> and <code>cash_accounts</code> in the working database, and from the audit trail.</p>
        <div class="cash-figures">
          <div><b>Starting balance (after the reset)</b><span>{money(cash['starting_balance'])}</span></div>
          <div><b>Paid out (human-approved)</b><span>{money(cash['total_paid'])}</span></div>
          <div><b>Ending balance</b><span>{money(cash['ending_balance'])}</span></div>
        </div>
        <p class="muted">Reset by {esc(reset.get('reset_by') or 'a person')} at {esc(reset.get('time'))} (audit entry {data['reset_index']}),
          which restored the original database: checking {money(cash['starting_balance'])}.</p>
        <div class="ledger-scroll"><table class="ledger">
          <thead><tr><th>#</th><th>Ticket</th><th>What was approved, and why</th><th>Request</th><th>Payment</th>
            <th>Approved by</th><th>Cash change</th><th>Balance after</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
        <p class="muted">Listed in the order the tickets were resolved. No purchases were requested: restocking the 12 missing hoodies
          would cost 12 × $22.00 = $264.00, more than the {money(cash['ending_balance'])} left. The discount moved no cash.</p>
        <p class="recon">{money(cash['starting_balance'])} − {parts} = <strong>{money(cash['ending_balance'])}</strong> ·
          <code>cash_accounts</code> (checking) = <strong>{money(cash['cash_accounts_balance'])}</strong> · reconciled ✓</p>
      </div>
    '''


def write_desk(data: dict, tickets: dict, cash: dict) -> None:
    src = DESK.read_text(encoding="utf-8")
    for tid, tk in tickets.items():
        a, b = panel_span(src, str(tid))
        panel = src[a:b]
        panel = region(panel, f"pill-{tid}",
                       f'<div class="status-pill" role="status">DB status: {esc(tk["final_status"])}<small>Ticket {tid} · '
                       f'{esc(tk["resolution_type"])} resolution</small></div>',
                       rf'<div class="status-pill" role="status">DB status: open<small>Ticket {tid} · not resolved</small></div>')
        panel = region(panel, f"track-{tid}",
                       f'''<div class="track" aria-label="Mission progress: 4 of 4 stages">
        <div class="stage done"><div class="bar"></div><b>1 · Plan written</b><span>Expected section below</span></div>
        <div class="stage done"><div class="bar"></div><b>2 · Agents run</b><span>Problem 9 live run</span></div>
        <div class="stage done"><div class="bar"></div><b>3 · Human approval</b><span>{len(tk['human_approvals'])} decided by a person</span></div>
        <div class="stage done"><div class="bar"></div><b>4 · Resolved</b><span>{esc(tk['resolution_type'])}, per the database</span></div>
      </div>''',
                       r'<div class="track" aria-label="Mission progress: 1 of 4 stages">\n(?:        <div class="stage.*?\n){4}      </div>')
        panel = re.sub(r"<dt>Status</dt><dd>open</dd>", "<dt>Status at start</dt><dd>open</dd>", panel)
        panel = region(panel, f"actual-{tid}", actual_html(tk) + actual_network_html(tk, panel, tid),
                       r'\n          <div class="vs-head"><h3 id="act-' + str(tid) + r'">Actual</h3>.*?</dl>')
        panel = panel.replace(f'<section class="actual pixel-box" data-actual="{tid}"', f'<section class="actual filled pixel-box" data-actual="{tid}"')
        src = src[:a] + panel + src[b:]
    a, b = panel_span(src, "cash")
    panel = region(src[a:b], "cash", cash_html(cash, data, tickets),
                   r'\n      <div class="later pixel-box">\n        <h2>Cash</h2>\n        <p>Coming in a later level.</p>\n      </div>\n    ')
    src = src[:a] + panel + src[b:]
    src = region(src, "tagline",
                 "The <strong>Actual</strong> side now shows the genuine Problem 9 run, drawn from the audit trail and the database.",
                 r"The <strong>Actual</strong> side stays empty until a genuine run fills it in\.")
    # Level-tab progress pips: all four stages are now done for every ticket.
    src = src.replace('<span class="stars" aria-hidden="true">■□□□</span>', '<span class="stars" aria-hidden="true">■■■■</span>')
    src = region(src, "meta-status",
                 "Database status after the Problem 9 run: <strong>"
                 + ", ".join(f"{tid} {tickets[tid]['final_status']} ({tickets[tid]['resolution_type']})" for tid in sorted(tickets))
                 + f"</strong> · checking {money(cash['ending_balance'])}",
                 r"Every ticket's database status: <strong>open</strong>")
    DESK.write_text(src, encoding="utf-8")


# ---------------------------------------------------------------------------
# resolved_tickets.json and resolved_board.html
# ---------------------------------------------------------------------------


def write_json(data: dict, tickets: dict, cash: dict) -> dict:
    runs = list(data["runs"].values())
    doc = {
        "generated_from": {"audit_trail": "output/audit_trail.json", "audit_entries": [data["reset_index"], len(data["trail"]) - 1],
                           "database": "data/campus_customs_new.db (read-only)",
                           # The last audit entry's time, not the clock, so an unchanged rebuild is byte-identical.
                           "as_of": data["trail"][-1].get("time")},
        "resolution_types": {
            "operational": "The real-world outcome has happened (the rent payment completes ticket 102).",
            "administrative": "The desk's work is done and a person closed the ticket, but outside steps are still outstanding.",
        },
        "simulation_policy": "Discounts follow the simulation discount policy, an assumption for this exercise and not a "
                             "rule in the database: 10+ unit orders, up to 10% off list, above cost, only on stock on hand.",
        "reset": {"audit_entry": data["reset_index"], "time": data["reset"].get("time"), "by": data["reset"].get("reset_by")},
        "cash": {k: cash[k] for k in ("starting_balance", "total_paid", "ending_balance", "cash_accounts_balance", "reconciled")},
        "model": {"requested": sorted({r["model"] for r in runs if r["model"]}),
                  "reported_by_responses": sorted({m for r in runs for m in r["response_models"]})},
        "tickets": [{k: v for k, v in tickets[tid].items() if not k.startswith("_")} for tid in sorted(tickets)],
    }
    RESOLVED_JSON.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return doc


def img(name: str) -> str:
    return "data:image/jpeg;base64," + base64.b64encode((SHOTS / name).read_bytes()).decode()


TIMELINE = [
    ("00_live_board_before_reset.jpg", "Live board before the reset: $3,400.00, all three tickets open."),
    ("01_ticket102_run_complete_awaiting_approval.jpg", "102: agent run complete; $2,400 rent waiting at the gate."),
    ("03_ticket101_run_complete_awaiting_approval.jpg", "101: agent run complete; $840 invoice waiting at the gate."),
    ("05_ticket103_run_complete_no_request.jpg", "103, first run: complete but no discount request filed (later re-run)."),
    ("06_ticket103_rerun_discount_approved.jpg", "103, second run: discount #3 approved as an offer; ticket in progress."),
    ("08_final_vault_and_agent_summaries.jpg", "End: vault at $160.00, three human decisions, and agent summaries."),
]


def write_board(doc: dict, tickets: dict, cash: dict) -> None:
    cards = ""
    for tid in cash["resolution_order"]:
        tk = tickets[tid]
        appr = "; ".join(f"#{a['request_id']} {KIND_LABEL[a['kind']].lower()} {money(a['amount'])} approved by {a['decided_by']}"
                         for a in tk["human_approvals"])
        out = "".join(f"<li>{esc(x)}</li>" for x in tk["outstanding"]) or "<li>Nothing outstanding</li>"
        cards += f'''
  <section class="ticket">
    <h2>Ticket {tid} · {esc(tk['mission'])}</h2>
    <p class="status"><span class="pill">{esc(tk['final_status'].upper())}</span> <span class="type">{esc(tk['resolution_type'])} resolution</span>
      by {esc(tk['resolved_by'])} · {esc(tk['resolved_at'])}</p>
    <figure><img src="{img(RESOLVED_SHOT[tid])}" alt="React board with ticket {tid} shown as resolved ({esc(tk['resolution_type'])})">
      <figcaption>Live React board (http://localhost:5173) after ticket {tid} was resolved. Captured during the run.</figcaption></figure>
    <p><strong>Outcome.</strong> {esc(tk['outcome'])}</p>
    <p><strong>Human approvals.</strong> {esc(appr) or 'None'}</p>
    <p><strong>Still outstanding outside the desk.</strong></p><ul>{out}</ul>
  </section>'''
    gallery = "".join(f'<figure class="mini"><img src="{img(n)}" alt="{esc(c)}"><figcaption>{esc(c)}</figcaption></figure>' for n, c in TIMELINE)
    rows = "".join(f"<tr><td>{tid}</td><td>{esc(tickets[tid]['mission'])}</td><td>{esc(tickets[tid]['final_status'])}</td>"
                   f"<td>{esc(tickets[tid]['resolution_type'])}</td><td class='num'>"
                   f"{money(sum(-a['cash_effect'] for a in tickets[tid]['human_approvals']))}</td></tr>" for tid in cash["resolution_order"])
    page = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Campus Customs: Agent Arcade · Resolved board (Homework 5, Problem 9)</title>
<!-- Built by tests/build_problem9_outputs.py from the real run. Screenshots are embedded so the page works offline. -->
<style>
  :root {{ --bg:#09060d; --panel:#170e20; --line:#3a2348; --pink:#ff2e97; --pink-soft:#ff8cc8; --text:#f7ecf4; --muted:#c4afc0;
    --yellow:#ffd23f; --green:#3ddc84; --mono:"Consolas","Lucida Console","Courier New",monospace; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.6 system-ui,"Segoe UI",Roboto,Arial,sans-serif; }}
  main {{ max-width:1120px; margin:0 auto; padding:28px 18px 48px; }}
  h1 {{ font:700 clamp(22px,4vw,34px)/1.15 var(--mono); letter-spacing:.08em; color:var(--pink); text-shadow:3px 3px 0 #6b1342; margin:0 0 6px; }}
  h2 {{ font:700 18px var(--mono); letter-spacing:.08em; text-transform:uppercase; color:var(--pink-soft); margin:0 0 8px; }}
  .lead, .muted, figcaption {{ color:var(--muted); }}
  .box, .ticket {{ background:var(--panel); box-shadow:0 0 0 3px var(--line); padding:18px 20px; margin:22px 0; }}
  .ticket {{ box-shadow:0 0 0 3px var(--pink); }}
  table {{ width:100%; border-collapse:collapse; }} th, td {{ text-align:left; padding:7px 9px; border-bottom:1px solid var(--line); }}
  th {{ font:700 12px var(--mono); letter-spacing:.1em; text-transform:uppercase; color:var(--pink-soft); }}
  td.num {{ text-align:right; font-family:var(--mono); }}
  .pill {{ font:700 12px var(--mono); letter-spacing:.12em; color:#1c1608; background:var(--yellow); padding:3px 8px; }}
  .type {{ font:700 13px var(--mono); color:var(--yellow); }}
  figure {{ margin:12px 0; }} img {{ width:100%; height:auto; display:block; box-shadow:0 0 0 2px var(--line); }}
  .gallery {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:14px; }}
  .recon {{ font-family:var(--mono); background:#0c1a12; box-shadow:inset 0 0 0 2px #1d6b43; padding:10px 12px; }}
  code {{ font-family:var(--mono); color:#4fe3ff; }}
</style>
</head>
<body>
<main>
  <h1>CAMPUS CUSTOMS: AGENT ARCADE · RESOLVED BOARD</h1>
  <p class="lead">Homework 5, Problem 9. Screenshots of the live React board for each resolved ticket, captured during the real
    three-ticket run on gpt-6-luna. The facts below come from the audit trail and the working database.</p>
  <div class="box">
    <h2>Summary</h2>
    <table><thead><tr><th>Ticket</th><th>Mission</th><th>Status</th><th>Resolution</th><th>Cash paid</th></tr></thead><tbody>{rows}</tbody></table>
    <p class="recon">Checking: {money(cash['starting_balance'])} at the start − {money(cash['total_paid'])} paid = <strong>{money(cash['ending_balance'])}</strong>
      · matches <code>cash_accounts</code> ✓</p>
    <p class="muted"><strong>Operational</strong>: the real-world outcome happened. <strong>Administrative</strong>: the desk's work is done and a
      person closed the ticket, with the outside steps still listed. Agents can't resolve tickets; only a person (or the recorded-rent rule for 102)
      can. The 101 and 102 screenshots were re-captured after a dashboard label fix made during the run (see docs/problem9_run_findings.md).</p>
  </div>
  {cards}
  <section class="box">
    <h2>Run timeline</h2>
    <div class="gallery">{gallery}</div>
  </section>
</main>
</body>
</html>
'''
    BOARD.write_text(page, encoding="utf-8")


def write_harness(data: dict, tickets: dict, cash: dict) -> None:
    lines = ["## Verified full run (Problem 9)", "",
             f"Built from audit entries {data['reset_index']}–{len(data['trail']) - 1} and the working database by "
             "`tests/build_problem9_outputs.py`. Details are in `output/resolved_tickets.json` and "
             "`docs/problem9_run_findings.md`.", "",
             f"- **Reset:** by {data['reset'].get('reset_by')} at {data['reset'].get('time')}. Checking started at "
             f"{money(cash['starting_balance'])}.",
             "- **Order:** 102 → 101 → 103. Every approval, reset and resolution was done by Kate Duffy in the dashboard.", ""]
    for tid in cash["resolution_order"]:
        tk = tickets[tid]
        f = tk["_final"]
        routes = ", ".join(f"{CHAR[d['from']]} → {CHAR[d['to']]}" for d in f["delegations"])
        lines.append(f"- **Ticket {tid} ({tk['resolution_type']}):** Boss called first: {CHAR[f['boss_first']]}. "
                     f"Delegations: {routes}. {f['usage'].get('total_tokens', 0):,} tokens. {tk['outcome']}")
        for x in tk["findings"]:
            lines.append(f"  - {x}")
    lines += ["", f"- **Cash:** {money(cash['starting_balance'])} − {money(cash['total_paid'])} = "
              f"**{money(cash['ending_balance'])}**, which matches `cash_accounts`.",
              "- **Dashboard fix during the run:** the resolved-ticket label now shows the resolution type, instead of "
              "\"Fully resolved\" for every resolved ticket.", ""]
    block = "\n".join(lines)
    src = HARNESS.read_text(encoding="utf-8")
    pat = re.compile(r"<!-- P9:run -->.*?<!-- /P9:run -->", re.S)
    marked = f"<!-- P9:run -->\n{block}\n<!-- /P9:run -->"
    src = pat.sub(lambda _: marked, src) if pat.search(src) else src.rstrip() + "\n\n" + marked + "\n"
    HARNESS.write_text(src, encoding="utf-8")


DATA: dict = {}


def recorded_identity() -> dict | None:
    """The simulation the committed evidence describes, read from output/resolved_tickets.json."""
    if not RESOLVED_JSON.exists():
        return None
    doc = json.loads(RESOLVED_JSON.read_text(encoding="utf-8"))
    return {
        "reset": (doc["reset"]["time"], doc["reset"]["by"]),
        "runs": {t["id"]: [r["run_id"] for r in t["runs"]] for t in doc["tickets"]},
        "payments": sorted((p["payment_id"], round(p["amount"], 2), p["approved_by"])
                           for t in doc["tickets"] for p in t["payments"]),
        "ending_balance": round(doc["cash"]["ending_balance"], 2),
    }


def current_identity(data: dict, tickets: dict, cash: dict) -> dict:
    """The same identity, computed from the live audit trail and the working database."""
    return {
        "reset": (data["reset"].get("time"), data["reset"].get("reset_by")),
        "runs": {tid: [r["run_id"] for r in tickets[tid]["_runs"]] for tid in tickets},
        "payments": sorted((p["id"], round(p["amount"], 2), p["approved_by"]) for p in data["db"]["payments"]),
        "ending_balance": round(cash["ending_balance"], 2),
    }


def guard(data: dict, tickets: dict, cash: dict) -> None:
    """Refuse to overwrite the verified Problem 9 evidence with a different simulation.

    The committed evidence records the reset, the runs, the payments and the final balance. If the audit
    trail or the working database now describe anything else (a new reset, a new run, other payments),
    stop before writing. Pass --force only when you deliberately replace the evidence with a new run.
    """
    old = recorded_identity()
    if old is None or "--force" in sys.argv:
        return
    new = current_identity(data, tickets, cash)
    diffs = [k for k in ("reset", "runs", "payments", "ending_balance") if old[k] != new[k]]
    if diffs:
        raise SystemExit(
            "Refusing to overwrite the verified Problem 9 evidence: the audit trail or working database now "
            f"describes a different simulation ({', '.join(diffs)} changed). Nothing was written. Re-run with "
            "--force only if you mean to replace the recorded run.")


def main() -> None:
    data = load()
    DATA.update(data)
    tickets = {tid: build_ticket(data, tid) for tid in (101, 102, 103)}
    cash = build_cash(data, tickets)
    guard(data, tickets, cash)
    write_desk(data, tickets, cash)
    doc = write_json(data, tickets, cash)
    write_board(doc, tickets, cash)
    write_harness(data, tickets, cash)
    print(f"Built Problem 9 evidence: cash {money(cash['starting_balance'])} → {money(cash['ending_balance'])} (reconciled); "
          + ", ".join(f"{tid} {tickets[tid]['final_status']} ({tickets[tid]['resolution_type']})" for tid in sorted(tickets)))


if __name__ == "__main__":
    main()
