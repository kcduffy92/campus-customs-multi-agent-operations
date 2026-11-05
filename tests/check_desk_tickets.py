"""Checks output/desk_tickets.html (Problems 6 and 9) without a browser, a model or any network.

- The page is standalone: no external URLs, scripts, styles, fonts, images or audio files.
- It has the five tabs (Ticket 101, Ticket 102, Ticket 103, Cash, Reflection) and their panels.
- Each ticket's Expected section still contains the student's approved wording, word for word (Problem 6).
- Each ticket's command network lists the expected routes and dims the agents who sit out.
- The official ticket details and starting facts match the ORIGINAL database (the state before the run).
- Problem 9: each Actual section is filled from the real run (with embedded audit entries), the status
  pill matches the working database, the Cash tab reconciles with cash_accounts, and Reflection is
  filled (Problem 10, word for word from docs/problem10_reflection.md). Cross-checks: tests/check_problem9_outputs.py.
- The original database is unchanged (its SHA-256 is pinned below).

Run: .venv/Scripts/python.exe tests/check_desk_tickets.py
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "output" / "desk_tickets.html"
ORIGINAL_DB = ROOT / "data" / "campus_customs.db"
WORKING_DB = ROOT / "data" / "campus_customs_new.db"
# The untouched course database, used for every reset. It must never change.
ORIGINAL_SHA256 = "23686a90d698f7fa6f901a3f0a9774db9cbb31e13151c9e5717275f3321f360a"

# The student's approved Expected wording (Problem 6 follow-up prompt 1 in AI_prompts.md).
EXPECTED = {
    "101": [
        "I expect the Boss to contact Inventory first because we need to determine whether the shirt is available "
        "before promising anything to the customer. Inventory should check the stock and investigate the supplier "
        "invoice. If the unpaid invoice is preventing a reprint, Accounting needs to assess the payment and submit an "
        "approval request. Customer Service should then prepare an accurate response explaining the situation and any "
        "confirmed next steps.",
        "Boss (Mario) → Inventory (Crash) → Accounting (Spyro), with Boss coordinating Customer Service (Sonic) for "
        "the customer response.",
        "get_ticket, check_stock_and_pricing, get_vendor_invoice_status, get_cash_balance, request_invoice_payment, "
        "list_approval_requests, update_ticket.",
        "Human approval gate: The $840 supplier invoice requires approval before any payment.",
    ],
    "102": [
        "I expect the Boss to contact Facilities first because the rent notice needs to be checked against the actual "
        "lease. Once Facilities confirms the amount and due date, Accounting should verify our available cash and "
        "prepare a payment request for human approval. Inventory and Customer Service shouldn't be involved because "
        "neither contributes anything necessary to resolving the rent issue.",
        "Boss (Mario) → Facilities (Ryu) → Accounting (Spyro).",
        "get_ticket, check_rent_due, get_cash_balance, list_approval_requests, request_rent_payment, update_ticket.",
        "Human approval gate: The $2,400 rent payment requires approval.",
    ],
    "103": [
        "I expect the Boss to contact Inventory first to confirm whether we have enough hoodies to fulfill the request. "
        "Accounting should then evaluate the pricing and whether a discount makes financial sense, without offering "
        "anything below our unit cost. Customer Service should prepare a response explaining what we can actually "
        "offer, including any inventory limitations. We shouldn't commit to a discount or delivery date until the "
        "necessary approvals and supply information are confirmed.",
        "Boss (Mario) → Inventory (Crash), followed by Accounting (Spyro) and Customer Service (Sonic) as needed.",
        "get_ticket, check_stock_and_pricing, list_vendors, get_cash_balance, request_discount, list_approval_requests, "
        "update_ticket.",
        "Human approval gate: Any proposed discount requires authorization before it becomes a confirmed offer.",
        "Do not assume the hoodie supplier, the availability of additional stock, or that the customer would accept a "
        "partial order without verified information.",
    ],
}
FIRST_CALL = {"101": "Inventory (Crash)", "102": "Facilities (Ryu)", "103": "Inventory (Crash)"}
# Expected command-network routes (Problem 6 follow-up prompt 2): (from, to, kind), and who sits out.
ROUTES = {
    "101": [("mario", "crash", "definite"), ("crash", "spyro", "conditional"), ("mario", "sonic", "definite")],
    "102": [("mario", "ryu", "definite"), ("ryu", "spyro", "definite")],
    "103": [("mario", "crash", "definite"), ("mario", "spyro", "definite"), ("mario", "sonic", "definite")],
}
SITTING_OUT = {"101": {"ryu"}, "102": {"crash", "sonic"}, "103": {"ryu"}}
LEVELS = {"101": "Operation Missing Tee", "102": "Operation Keep the Lights On", "103": "Operation Hoodie Negotiation"}

results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    results.append((bool(ok), label))


def text(fragment: str) -> str:
    fragment = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->", " ", fragment, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def norm(s: str) -> str:
    # Inline <code> chips add spaces before commas when tags are stripped.
    return re.sub(r"\s+([,.])", r"\1", re.sub(r"\s+", " ", s)).strip()


def panel(raw: str, pid: str) -> str:
    m = re.search(rf'<section class="panel"[^>]*id="panel-{pid}".*?(?=<!-- =+ |</main>)', raw, flags=re.S)
    return m.group(0) if m else ""


def money(x: float) -> str:
    return f"${x:,.2f}"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    raw = PAGE.read_text(encoding="utf-8")
    check(PAGE.exists(), "output/desk_tickets.html exists")

    # --- standalone ---
    # The SVG namespace string is an identifier, not a network request.
    no_ns = raw.replace("http://www.w3.org/2000/svg", "")
    check(not re.search(r"https?://|//cdn|@import", no_ns), "no external URLs, CDNs or @import")
    check(not re.search(r"<(link|img|audio|source|iframe)\b", raw, flags=re.I), "no <link>, <img>, <audio>, <source> or <iframe>")
    check(not re.search(r"<script[^>]+src=", raw, flags=re.I), "no external <script src>")
    check(not re.search(r"\bfetch\(|XMLHttpRequest|WebSocket", raw), "no network calls in the script")

    # --- tabs ---
    tabs = re.findall(r'role="tab"[^>]*id="tab-([a-z0-9]+)"[^>]*aria-controls="panel-([a-z0-9]+)"', raw)
    check([t for t, _ in tabs] == ["101", "102", "103", "cash", "reflection"], "five tabs in order: 101, 102, 103, Cash, Reflection")
    check(all(t == p for t, p in tabs), "each tab controls its own panel")
    tab_names = [text(m) for m in re.findall(r'<button[^>]*role="tab".*?</button>', raw, flags=re.S)]
    for want in ("Ticket 101", "Ticket 102", "Ticket 103", "Cash", "Reflection"):
        check(any(want in n for n in tab_names), f"tab labelled '{want}'")
    for tid, name in LEVELS.items():
        check(any(f"LEVEL {tid}" in n and name in n for n in tab_names), f"tab {tid} shows 'Level {tid}: {name}'")
    check(len(re.findall(r'role="tabpanel"', raw)) == 5, "five tab panels")

    # --- Expected / Actual per ticket ---
    for tid, parts in EXPECTED.items():
        p = panel(raw, tid)
        check(bool(p), f"panel {tid} found")
        exp_html = p.split('class="actual', 1)[0].split('class="expected', 1)[-1]
        exp = norm(text("<x " + exp_html))
        for i, part in enumerate(parts, 1):
            check(norm(part) in exp, f"{tid} Expected contains approved wording, part {i}")
        check(f"Boss calls first {FIRST_CALL[tid]}" in exp, f"{tid} Expected names the first call: {FIRST_CALL[tid]}")
        act = re.search(r'<section class="actual[^>]*data-actual="' + tid + r'".*?</section>', p, flags=re.S)
        check(bool(act), f"{tid} has an Actual section")
        act_html = act.group(0) if act else ""
        slots = re.findall(r'<dd class="slot filled">(.*?)</dd>', act_html, flags=re.S)
        check(len(slots) >= 6 and all(text(s_) for s_ in slots), f"{tid} Actual slots are filled from the run ({len(slots)})")
        check("From the real Problem 9 run" in text(act_html) and "Insert coin" not in act_html,
              f"{tid} Actual is labelled as the real run")
        ev_json = re.search(r'<script type="application/json" id="actual-events-' + tid + r'">(.*?)</script>', p, flags=re.S)
        check(bool(ev_json) and all(e.get("ticket_id") == int(tid) for e in json.loads(ev_json.group(1).replace("<\\/", "</"))),
              f"{tid} Actual network embeds this ticket's real audit entries")

        net = re.search(r'<section class="network-block[^>]*data-network="' + tid + r'".*?</section>', p, flags=re.S)
        check(bool(net), f"{tid} has a command network block")
        net_html = net.group(0) if net else ""
        routes = re.findall(r'<li data-from="(\w+)" data-to="(\w+)" data-kind="(\w+)"', net_html)
        check(routes == ROUTES[tid], f"{tid} network routes are {ROUTES[tid]}")
        out = re.search(r'data-out="([^"]*)"', net_html)
        check(bool(out) and set(out.group(1).split()) == SITTING_OUT[tid], f"{tid} network dims {sorted(SITTING_OUT[tid])}")
        check("Expected plan" in text(net_html) and "No agent has run" in text(net_html), f"{tid} network is labelled as the expected plan")
        check("demo, not a real run" in text(net_html), f"{tid} preview button is labelled as a demo")
        check(p.index('class="network-block') < p.index('class="versus"'), f"{tid} network sits above Expected vs. Actual")

    # The event adapter is called once, only for networks that embed real audit entries (Problem 9).
    script = re.search(r"<script>(.*?)</script>", raw, flags=re.S).group(1)
    check("applyAuditEvents = function" in script and len(re.findall(r"\.applyAuditEvents\(", script)) == 1
          and 'getAttribute("data-events")' in script, "audit-event adapter runs only on embedded real audit entries")

    # Problem 10: the Reflection tab holds the student's text word for word (only Markdown markup converted).
    source = (ROOT / "docs" / "problem10_reflection.md").read_text(encoding="utf-8")
    plain = re.sub(r"\s+", " ", re.sub(r"^#+ ", "", source, flags=re.M).replace("**", "").replace("`", "")).strip()
    refl = norm(text(panel(raw, "reflection")))  # norm() drops the space tag-stripping leaves before , and .
    check(norm(plain) in refl and "Coming in a later level" not in refl, "Reflection tab holds the student's reflection word for word")
    for q in ("1. How did the agents perform", "2. How did the actual results compare", "3. What would have been simpler",
              "4. What three new problems could", "5. What three new problems couldn't"):
        check(q in refl, f"Reflection answers: {q}…")

    # --- Problem 9: status pills and the Cash tab against the working database (read-only) ---
    wcon = sqlite3.connect(f"file:{WORKING_DB.as_posix()}?mode=ro", uri=True)
    for tid in EXPECTED:
        st = wcon.execute("SELECT status FROM tickets WHERE id = ?", (int(tid),)).fetchone()[0]
        check(f"DB status: {st}" in norm(text(panel(raw, tid))), f"{tid} status pill matches the working database ({st})")
    end = wcon.execute("SELECT balance FROM cash_accounts WHERE name = 'checking'").fetchone()[0]
    paid = wcon.execute("SELECT COALESCE(SUM(amount), 0) FROM payments").fetchone()[0]
    wcon.close()
    cash_tab = norm(text(panel(raw, "cash")))
    check(f"Ending balance {money(end)}" in cash_tab and "reconciled" in cash_tab,
          f"Cash tab ending balance {money(end)} matches cash_accounts")
    check(f"Paid out (human-approved) {money(paid)}" in cash_tab, f"Cash tab total paid {money(paid)} matches payments")

    # --- the official ticket and starting facts against the ORIGINAL database (read-only) ---
    con = sqlite3.connect(f"file:{ORIGINAL_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    q = lambda sql, *a: con.execute(sql, a).fetchone()
    today = q("SELECT date_today FROM desk")["date_today"]
    check(f"Shop date {today}" in text(raw), f"shop date {today} shown")
    for tid in EXPECTED:
        t = q("SELECT * FROM tickets WHERE id = ?", int(tid))
        p = norm(text(panel(raw, tid)))
        for field in ("type", "requester", "subject", "notes", "created_at"):
            check(str(t[field]) in p, f"{tid} shows ticket {field} = {t[field]!r}")
        check(f"Status at start {t['status']}" in p, f"{tid} shows its starting status ({t['status']})")
        if t["sku"]:
            check(f"{t['sku']}, size {t['size']}, qty {t['qty']}" in p, f"{tid} shows item {t['sku']} {t['size']} x{t['qty']}")
    cash = q("SELECT balance FROM cash_accounts WHERE name = 'checking'")["balance"]
    tee = q("SELECT i.qty, i.location, p.unit_cost, p.list_price FROM inventory i JOIN pricing p USING (sku) WHERE sku='CC-TEE-WHITE' AND size='S'")
    hood = q("SELECT i.qty, i.location, p.unit_cost, p.list_price FROM inventory i JOIN pricing p USING (sku) WHERE sku='CC-HOOD-NAVY' AND size='M'")
    inv = q("SELECT i.*, v.name AS vendor, v.lead_days FROM invoices i JOIN vendors v ON v.id = i.vendor_id WHERE i.id = 501")
    lease = q("SELECT * FROM leases WHERE id = 1")
    n_pay = q("SELECT COUNT(*) AS n FROM payments")["n"]
    p101, p102, p103 = (norm(text(panel(raw, t))) for t in ("101", "102", "103"))
    check(f"{tee['qty']} on hand ({tee['location']})" in p101, f"101 tee stock {tee['qty']} ({tee['location']})")
    check(f"List price {money(tee['list_price'])}; unit cost {money(tee['unit_cost'])}" in p101, "101 tee price and cost")
    check(f"Invoice 501, {inv['vendor']}: {money(inv['amount'])}, {inv['status']}" in p101, "101 invoice 501 vendor, amount, status")
    check(f"due {inv['due_date']}" in p101 and inv["description"] in p101, "101 invoice due date and description")
    from datetime import date
    days = (date.fromisoformat(today) - date.fromisoformat(inv["due_date"])).days
    check(f"{days} days overdue" in p101, f"101 invoice {days} days overdue")
    check(f"lead time: {inv['lead_days']} days" in p101, "101 vendor lead time")
    check(f"{lease['space_name']}, landlord {lease['landlord']}" in p102, "102 lease space and landlord")
    check(f"Monthly rent {money(lease['monthly_rent'])}, next due {lease['next_due']}" in p102, "102 rent amount and due date")
    check(f"Payments recorded so far: {n_pay}" in p102, f"102 payments recorded ({n_pay})")
    check(f"{hood['qty']} on hand ({hood['location']}); 20 requested, so {20 - hood['qty']} short" in p103, "103 hoodie stock and shortfall")
    check(f"List price {money(hood['list_price'])}; unit cost {money(hood['unit_cost'])}" in p103, "103 hoodie price and cost floor")
    for tid, p in (("101", p101), ("102", p102), ("103", p103)):
        check(f"Checking balance: {money(cash)}" in p, f"{tid} checking balance {money(cash)}")
    con.close()

    # --- original database untouched ---
    check(sha(ORIGINAL_DB) == ORIGINAL_SHA256, "original database unchanged (pinned SHA-256)")

    failed = [label for ok, label in results if not ok]
    for ok, label in results:
        print(("PASS " if ok else "FAIL ") + label)
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
