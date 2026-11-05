"""Campus Customs MCP server (Homework 5).

Every agent in this homework uses the tools here. They talk to the working copy
data/campus_customs_new.db and never to the original data/campus_customs.db.

Read tools open the database with mode=ro, so they cannot change a record even
by accident. Every value they return comes from the database; missing records
come back as {"found": False, ...}, never as guesses.

Problem 5 adds ticket tools and a human-approval queue (approval_requests).
Agents may *request* a payment, purchase or discount; only the backend-only
tools at the bottom of this file can execute or reject a request, and the agent
toolsets never include them.

Run (stdio):  python mcp_server/server.py
Run (HTTP):   python mcp_server/server.py --http   ->  http://127.0.0.1:8001/mcp

CAMPUS_CUSTOMS_DB can point the server at an isolated copy (tests, live checks).
It may never point at the original data/campus_customs.db.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = ROOT / "data" / "campus_customs_new.db"
ORIGINAL_DB_PATH = ROOT / "data" / "campus_customs.db"
CASH_ACCOUNT = "checking"

mcp = FastMCP("campus-customs")


def _db_path() -> Path:
    """The working copy, or an isolated copy named by CAMPUS_CUSTOMS_DB. Never the original."""
    override = os.getenv("CAMPUS_CUSTOMS_DB", "").strip()
    path = Path(override).resolve() if override else DB_PATH
    if ORIGINAL_DB_PATH.exists() and path.exists() and path.samefile(ORIGINAL_DB_PATH):
        raise ToolError("Refusing to use the original database; it is kept untouched for resets.")
    return path


def _display(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _read_only_connection() -> sqlite3.Connection:
    """Open the working database read-only. Fails instead of creating a new file."""
    path = _db_path()
    if not path.exists():
        raise ToolError(f"Working database not found at {_display(path)}")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _today(conn: sqlite3.Connection) -> date:
    """The shop's "today" is desk.date_today, not the system clock."""
    row = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    if row is None:
        raise ToolError("desk.date_today is missing, so due dates cannot be checked")
    return date.fromisoformat(row["date_today"])


def _money(value: float) -> float:
    return round(value, 2)


@mcp.tool
def get_vendor_invoice_status(invoice_id: int) -> dict:
    """Look up a vendor invoice, how overdue it is, and whether the vendor is blocked from shipping.

    Reads invoices, vendors and desk. A vendor will not ship new product while it
    has an open unpaid invoice, so this tells you if a restock can happen.
    """
    with _read_only_connection() as conn:
        today = _today(conn)
        inv = conn.execute(
            """
            SELECT i.id, i.vendor_id, i.amount, i.due_date, i.status, i.description,
                   v.name AS vendor_name, v.specialty AS vendor_specialty, v.lead_days AS vendor_lead_days
            FROM invoices i
            LEFT JOIN vendors v ON v.id = i.vendor_id
            WHERE i.id = ?
            """,
            (invoice_id,),
        ).fetchone()
        if inv is None:
            return {"found": False, "invoice_id": invoice_id, "message": f"No invoice with id {invoice_id}"}

        open_invoices = conn.execute(
            "SELECT id, amount, due_date FROM invoices WHERE vendor_id = ? AND status = 'open' ORDER BY due_date",
            (inv["vendor_id"],),
        ).fetchall()

    days_past_due = (today - date.fromisoformat(inv["due_date"])).days
    return {
        "found": True,
        "today": today.isoformat(),
        "invoice": {
            "id": inv["id"],
            "amount": _money(inv["amount"]),
            "due_date": inv["due_date"],
            "status": inv["status"],
            "description": inv["description"],
            "days_past_due": max(days_past_due, 0),
            "is_overdue": inv["status"] == "open" and days_past_due > 0,
        },
        "vendor": {
            "id": inv["vendor_id"],
            "found": inv["vendor_name"] is not None,
            "name": inv["vendor_name"],
            "specialty": inv["vendor_specialty"],
            "lead_days": inv["vendor_lead_days"],
        },
        "vendor_open_invoices": [
            {"id": r["id"], "amount": _money(r["amount"]), "due_date": r["due_date"]} for r in open_invoices
        ],
        "vendor_blocked_from_shipping": len(open_invoices) > 0,
    }


@mcp.tool
def check_rent_due(lease_id: int) -> dict:
    """Check a lease's rent amount and due date against the cash on hand. Does not pay anything.

    Reads leases, cash_accounts and desk. Reports whether each cash account could
    cover the rent without going negative.
    """
    with _read_only_connection() as conn:
        today = _today(conn)
        lease = conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
            (lease_id,),
        ).fetchone()
        if lease is None:
            return {"found": False, "lease_id": lease_id, "message": f"No lease with id {lease_id}"}
        accounts = conn.execute("SELECT name, balance, date FROM cash_accounts ORDER BY name").fetchall()

    rent = _money(lease["monthly_rent"])
    days_until_due = (date.fromisoformat(lease["next_due"]) - today).days
    return {
        "found": True,
        "today": today.isoformat(),
        "lease": {
            "id": lease["id"],
            "space_name": lease["space_name"],
            "landlord": lease["landlord"],
            "monthly_rent": rent,
            "next_due": lease["next_due"],
            "notes": lease["notes"],
            "days_until_due": days_until_due,
            "is_overdue": days_until_due < 0,
        },
        "cash_accounts": [
            {
                "name": a["name"],
                "balance": _money(a["balance"]),
                "as_of": a["date"],
                "covers_rent": a["balance"] >= rent,
                "balance_after_rent": _money(a["balance"] - rent),
            }
            for a in accounts
        ],
        "any_account_covers_rent": any(a["balance"] >= rent for a in accounts),
    }


@mcp.tool
def check_stock_and_pricing(sku: str, size: str, requested_quantity: int | None = None) -> dict:
    """Check stock on hand, location and pricing for one product size.

    Reads inventory and pricing. If requested_quantity is given, also reports the
    shortage and the order total at list price (no discount is applied or assumed).
    """
    sku = sku.strip().upper()
    size = size.strip().upper()
    if not sku or not size:
        raise ToolError("Both sku and size are required")
    if requested_quantity is not None and requested_quantity < 1:
        raise ToolError("requested_quantity must be a whole number of at least 1")

    with _read_only_connection() as conn:
        item = conn.execute(
            """
            SELECT i.sku, i.name, i.size, i.qty, i.location, p.unit_cost, p.list_price
            FROM inventory i
            LEFT JOIN pricing p ON p.sku = i.sku
            WHERE i.sku = ? AND i.size = ?
            """,
            (sku, size),
        ).fetchone()
        if item is None:
            sizes = [r["size"] for r in conn.execute("SELECT size FROM inventory WHERE sku = ? ORDER BY size", (sku,))]
            message = (
                f"{sku} has no size {size}. Sizes on record: {', '.join(sizes)}"
                if sizes
                else f"No product with sku {sku}"
            )
            return {"found": False, "sku": sku, "size": size, "sizes_on_record": sizes, "message": message}

    has_pricing = item["list_price"] is not None
    result = {
        "found": True,
        "sku": item["sku"],
        "name": item["name"],
        "size": item["size"],
        "qty_on_hand": item["qty"],
        "in_stock": item["qty"] > 0,
        "location": item["location"],
        "pricing_found": has_pricing,
        "unit_cost": _money(item["unit_cost"]) if has_pricing else None,
        "list_price": _money(item["list_price"]) if has_pricing else None,
    }
    if requested_quantity is not None:
        result["order"] = {
            "requested_quantity": requested_quantity,
            "can_fill_from_stock": item["qty"] >= requested_quantity,
            "shortage": max(requested_quantity - item["qty"], 0),
            "total_at_list_price": _money(requested_quantity * item["list_price"]) if has_pricing else None,
            "total_at_unit_cost": _money(requested_quantity * item["unit_cost"]) if has_pricing else None,
        }
    return result


# ---------------------------------------------------------------------------
# Problem 5: tickets, vendors, cash and the human-approval queue
# ---------------------------------------------------------------------------

AGENT_NAMES = {"boss", "inventory", "accounting", "facilities", "customer_service"}
TICKET_STATUSES = ("open", "in_progress", "awaiting_approval", "resolved")
REQUEST_KINDS = ("invoice_payment", "rent_payment", "purchase", "discount")

# Repeatable: every write transaction runs this, and IF NOT EXISTS makes it a no-op
# once the table exists. The nine original tables are never altered.
APPROVAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    request_uid   TEXT NOT NULL UNIQUE,
    ticket_id     INTEGER NOT NULL REFERENCES tickets(id),
    kind          TEXT NOT NULL CHECK (kind IN ('invoice_payment', 'rent_payment', 'purchase', 'discount')),
    ref_id        INTEGER,
    sku           TEXT,
    size          TEXT,
    quantity      INTEGER,
    unit_price    REAL,
    amount        REAL NOT NULL CHECK (amount >= 0),
    cash_effect   REAL NOT NULL CHECK (cash_effect <= 0),
    account       TEXT,
    details       TEXT,
    reason        TEXT NOT NULL,
    requested_by  TEXT NOT NULL,
    requested_at  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'executed', 'rejected')),
    dedupe_key    TEXT NOT NULL,
    decided_by    TEXT,
    decided_at    TEXT,
    decision_note TEXT,
    payment_id    INTEGER REFERENCES payments(id),
    result        TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS approval_requests_one_pending
    ON approval_requests (dedupe_key) WHERE status = 'pending';
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Transaction:
    """One atomic write: BEGIN IMMEDIATE ... COMMIT, or ROLLBACK on any error."""

    def __enter__(self) -> sqlite3.Connection:
        path = _db_path()
        if not path.exists():
            raise ToolError(f"Working database not found at {_display(path)}")
        self.conn = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("BEGIN IMMEDIATE")
        for statement in APPROVAL_SCHEMA.split(";"):
            if statement.strip():
                self.conn.execute(statement)
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.conn.close()


def _has_approval_table(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'approval_requests'"
    ).fetchone() is not None


def _request_row(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["details"] = json.loads(out["details"]) if out.get("details") else None
    out["result"] = json.loads(out["result"]) if out.get("result") else None
    out.pop("dedupe_key", None)
    return out


def _pending_outflow(conn: sqlite3.Connection, account: str = CASH_ACCOUNT) -> float:
    if not _has_approval_table(conn):
        return 0.0
    row = conn.execute(
        "SELECT COALESCE(SUM(-cash_effect), 0) FROM approval_requests WHERE status = 'pending' AND account = ?",
        (account,),
    ).fetchone()
    return _money(row[0])


def _cash_snapshot(conn: sqlite3.Connection, amount: float) -> dict:
    acct = conn.execute("SELECT * FROM cash_accounts WHERE name = ?", (CASH_ACCOUNT,)).fetchone()
    if acct is None:
        return {"account": CASH_ACCOUNT, "found": False}
    pending = _pending_outflow(conn)
    return {
        "account": CASH_ACCOUNT,
        "balance": _money(acct["balance"]),
        "pending_outflow_before_this_request": pending,
        "covers_this_amount": acct["balance"] >= amount,
        "covers_all_pending_plus_this": acct["balance"] - pending - amount >= 0,
    }


def _check_requester(requested_by: str) -> str:
    who = (requested_by or "").strip().lower()
    if who not in AGENT_NAMES:
        raise ToolError(f"requested_by must be one of the agents: {sorted(AGENT_NAMES)}")
    return who


def _check_ticket(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise ToolError(f"Ticket {ticket_id} not found")
    return row


def _create_request(
    conn: sqlite3.Connection,
    *,
    ticket_id: int,
    kind: str,
    amount: float,
    cash_effect: float,
    reason: str,
    requested_by: str,
    dedupe_key: str,
    ref_id: int | None = None,
    sku: str | None = None,
    size: str | None = None,
    quantity: int | None = None,
    unit_price: float | None = None,
    details: dict | None = None,
) -> dict:
    """Insert a pending request, or return the existing one if it duplicates a live request."""
    if not (reason or "").strip():
        raise ToolError("reason is required so a human can judge the request")
    existing = conn.execute(
        "SELECT * FROM approval_requests WHERE dedupe_key = ? AND status IN ('pending', 'executed') "
        "ORDER BY id DESC LIMIT 1",
        (dedupe_key,),
    ).fetchone()
    if existing is not None:
        return {
            "created": False,
            "duplicate": True,
            "message": f"An identical request is already {existing['status']}; nothing new was queued.",
            "request": _request_row(existing),
        }
    snapshot = _cash_snapshot(conn, -cash_effect)
    cur = conn.execute(
        "INSERT INTO approval_requests (request_uid, ticket_id, kind, ref_id, sku, size, quantity, unit_price, "
        "amount, cash_effect, account, details, reason, requested_by, requested_at, dedupe_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()), ticket_id, kind, ref_id, sku, size, quantity, unit_price,
            _money(amount), _money(cash_effect), CASH_ACCOUNT, json.dumps(details) if details else None,
            reason.strip(), requested_by, _now(), dedupe_key,
        ),
    )
    row = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {
        "created": True,
        "duplicate": False,
        "message": "Queued for human approval. No money has moved; a person must approve it in the dashboard.",
        "request": _request_row(row),
        "cash_check": snapshot,
    }


@mcp.tool
def list_tickets(status: str | None = None) -> dict:
    """List desk tickets (id, type, requester, subject, status), optionally filtered by status.

    Reads tickets. Use it to see the work queue; use get_ticket for one ticket's full record.
    """
    with _read_only_connection() as conn:
        sql, params = "SELECT id, type, requester, subject, status, created_at FROM tickets", ()
        if status:
            sql, params = sql + " WHERE status = ?", (status.strip(),)
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY id", params)]
    return {"count": len(rows), "tickets": rows}


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """Return one ticket's full record and any approval requests already filed for it.

    Reads tickets and approval_requests. Check the existing requests before asking for a
    new payment, purchase or discount, so nothing is requested twice.
    """
    with _read_only_connection() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            return {"found": False, "ticket_id": ticket_id}
        requests = []
        if _has_approval_table(conn):
            requests = [
                _request_row(r)
                for r in conn.execute("SELECT * FROM approval_requests WHERE ticket_id = ? ORDER BY id", (ticket_id,))
            ]
        return {"found": True, "today": _today(conn).isoformat(), "ticket": dict(row), "approval_requests": requests}


@mcp.tool
def list_vendors() -> dict:
    """List vendors with specialty, lead time, open invoices and whether each is blocked from shipping.

    Reads vendors and invoices. A vendor with any open invoice will not ship new product.
    """
    with _read_only_connection() as conn:
        vendors = []
        for v in conn.execute("SELECT * FROM vendors ORDER BY id"):
            open_rows = conn.execute(
                "SELECT id, amount, due_date FROM invoices WHERE vendor_id = ? AND status = 'open' ORDER BY id",
                (v["id"],),
            ).fetchall()
            vendors.append(
                {
                    **dict(v),
                    "open_invoices": [dict(r) for r in open_rows],
                    "open_invoice_total": _money(sum(r["amount"] for r in open_rows)),
                    "blocked_from_shipping": bool(open_rows),
                }
            )
    return {"count": len(vendors), "vendors": vendors}


@mcp.tool
def get_cash_balance() -> dict:
    """Return each cash account's balance and the money already promised to pending approval requests.

    Reads cash_accounts, approval_requests and desk. available_after_pending is what would be
    left if every pending request were approved. There is no incoming revenue.
    """
    with _read_only_connection() as conn:
        accounts = []
        for a in conn.execute("SELECT * FROM cash_accounts ORDER BY name"):
            pending = _pending_outflow(conn, a["name"])
            accounts.append(
                {
                    "name": a["name"],
                    "balance": _money(a["balance"]),
                    "as_of": a["date"],
                    "pending_outflow": pending,
                    "available_after_pending": _money(a["balance"] - pending),
                }
            )
        return {"today": _today(conn).isoformat(), "cash_accounts": accounts}


@mcp.tool
def list_approval_requests(ticket_id: int | None = None, status: str | None = None) -> dict:
    """List approval requests (payments, purchases, discounts), optionally by ticket and/or status.

    Reads approval_requests. Statuses: pending (waiting for a human), executed, rejected.
    """
    with _read_only_connection() as conn:
        if not _has_approval_table(conn):
            return {"count": 0, "requests": [], "note": "No approval requests have been filed yet."}
        clauses, params = [], []
        if ticket_id is not None:
            clauses.append("ticket_id = ?")
            params.append(ticket_id)
        if status:
            clauses.append("status = ?")
            params.append(status.strip())
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = [_request_row(r) for r in conn.execute(f"SELECT * FROM approval_requests{where} ORDER BY id", params)]
    return {"count": len(rows), "requests": rows}


@mcp.tool
def request_invoice_payment(ticket_id: int, invoice_id: int, reason: str, requested_by: str) -> dict:
    """Ask a human to approve paying an open vendor invoice. Does NOT pay anything.

    Reads invoices, cash_accounts and tickets; writes one pending row to approval_requests.
    The amount is taken from the invoice, never from the caller. Duplicate requests are refused.
    """
    who = _check_requester(requested_by)
    with _Transaction() as conn:
        _check_ticket(conn, ticket_id)
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if inv is None:
            return {"created": False, "found": False, "message": f"Invoice {invoice_id} not found."}
        if inv["status"] != "open":
            return {"created": False, "message": f"Invoice {invoice_id} is '{inv['status']}', not open."}
        return _create_request(
            conn, ticket_id=ticket_id, kind="invoice_payment", ref_id=invoice_id,
            amount=inv["amount"], cash_effect=-inv["amount"], reason=reason, requested_by=who,
            dedupe_key=f"invoice:{invoice_id}",
            details={"vendor_id": inv["vendor_id"], "due_date": inv["due_date"], "description": inv["description"]},
        )


@mcp.tool
def request_rent_payment(ticket_id: int, lease_id: int, reason: str, requested_by: str) -> dict:
    """Ask a human to approve paying the next rent on a lease. Does NOT pay anything.

    Reads leases, cash_accounts and tickets; writes one pending row to approval_requests.
    The amount and due date come from the lease. One request per lease per due date.
    """
    who = _check_requester(requested_by)
    with _Transaction() as conn:
        _check_ticket(conn, ticket_id)
        lease = conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
        if lease is None:
            return {"created": False, "found": False, "message": f"Lease {lease_id} not found."}
        return _create_request(
            conn, ticket_id=ticket_id, kind="rent_payment", ref_id=lease_id,
            amount=lease["monthly_rent"], cash_effect=-lease["monthly_rent"], reason=reason, requested_by=who,
            dedupe_key=f"rent:{lease_id}:{lease['next_due']}",
            details={"landlord": lease["landlord"], "space_name": lease["space_name"], "due_date": lease["next_due"]},
        )


@mcp.tool
def request_purchase(
    ticket_id: int, vendor_id: int, sku: str, size: str, quantity: int, reason: str, requested_by: str
) -> dict:
    """Ask a human to approve buying stock from a vendor at unit cost. Does NOT buy anything.

    Reads vendors, invoices, inventory, pricing and cash_accounts; writes one pending row to
    approval_requests. Cost = quantity x pricing.unit_cost. If the vendor has an open invoice it
    is flagged as blocked, and the purchase cannot be executed until that invoice is paid.
    """
    who = _check_requester(requested_by)
    sku, size = sku.strip().upper(), size.strip().upper()
    if quantity <= 0:
        raise ToolError("quantity must be positive")
    with _Transaction() as conn:
        _check_ticket(conn, ticket_id)
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            return {"created": False, "found": False, "message": f"Vendor {vendor_id} not found."}
        item = conn.execute(
            "SELECT i.name, p.unit_cost FROM inventory i JOIN pricing p ON p.sku = i.sku WHERE i.sku = ? AND i.size = ?",
            (sku, size),
        ).fetchone()
        if item is None:
            return {"created": False, "found": False, "message": f"No priced inventory row for {sku} size {size}."}
        open_invoices = [r["id"] for r in conn.execute(
            "SELECT id FROM invoices WHERE vendor_id = ? AND status = 'open'", (vendor_id,))]
        cost = quantity * item["unit_cost"]
        out = _create_request(
            conn, ticket_id=ticket_id, kind="purchase", ref_id=vendor_id, sku=sku, size=size, quantity=quantity,
            unit_price=item["unit_cost"], amount=cost, cash_effect=-cost, reason=reason, requested_by=who,
            dedupe_key=f"purchase:{ticket_id}:{vendor_id}:{sku}:{size}:{quantity}",
            details={"vendor": vendor["name"], "lead_days": vendor["lead_days"], "item": item["name"],
                     "vendor_open_invoices": open_invoices},
        )
        out["vendor_blocked_from_shipping"] = bool(open_invoices)
        return out


# Simulation discount policy (Problem 9). An assumption set for this educational simulation, not a rule
# stored in the shop's database: group orders of DISCOUNT_MIN_ORDER_QTY+ units may get up to
# DISCOUNT_MAX_PCT off list price, above unit cost, and only on units that can actually be supplied.
DISCOUNT_MIN_ORDER_QTY = 10
DISCOUNT_MAX_PCT = 10.0
DISCOUNT_POLICY = (f"Simulation discount policy (an assumption for this exercise, not a database rule): orders of "
                   f"{DISCOUNT_MIN_ORDER_QTY}+ units may get up to {DISCOUNT_MAX_PCT:g}% off list price, above unit "
                   f"cost, only on units in stock.")


@mcp.tool
def request_discount(
    ticket_id: int, sku: str, size: str, quantity: int, unit_price: float, reason: str, requested_by: str
) -> dict:
    """Ask a human to approve a discounted unit price for a customer order. Changes no price or cash.

    Reads pricing, inventory and tickets; writes one pending row to approval_requests. Enforces the
    simulation discount policy (an assumption for this exercise, not a database rule): the ticket's
    order must be 10+ units, the price at most 10% off list and above unit cost, and `quantity` (the
    units discounted) no more than the stock on hand. The order's shortfall is reported, not hidden.
    """
    who = _check_requester(requested_by)
    sku, size = sku.strip().upper(), size.strip().upper()
    if quantity <= 0:
        raise ToolError("quantity must be positive")
    with _Transaction() as conn:
        ticket = _check_ticket(conn, ticket_id)
        item = conn.execute(
            "SELECT i.qty, p.unit_cost, p.list_price FROM inventory i JOIN pricing p ON p.sku = i.sku "
            "WHERE i.sku = ? AND i.size = ?",
            (sku, size),
        ).fetchone()
        if item is None:
            return {"created": False, "found": False, "message": f"No priced inventory row for {sku} size {size}."}
        price = _money(unit_price)
        floor = _money(item["list_price"] * (1 - DISCOUNT_MAX_PCT / 100))
        same_item = ticket["sku"] == sku and ticket["size"] == size and ticket["qty"]
        order_qty = ticket["qty"] if same_item else quantity
        refuse = lambda msg: {"created": False, "message": msg, "policy": DISCOUNT_POLICY}  # noqa: E731
        if price <= item["unit_cost"]:
            return refuse(f"{price} is at or below unit cost {item['unit_cost']}; the price must stay above cost.")
        if price >= item["list_price"]:
            return refuse(f"{price} is not a discount; list price is {item['list_price']}.")
        if price < floor:
            return refuse(f"{price} is more than {DISCOUNT_MAX_PCT:g}% off list price {item['list_price']}; "
                          f"the lowest allowed price is {floor}.")
        if order_qty < DISCOUNT_MIN_ORDER_QTY:
            return refuse(f"The order is {order_qty} unit(s); a discount needs an order of "
                          f"{DISCOUNT_MIN_ORDER_QTY} or more.")
        if quantity > item["qty"]:
            return refuse(f"Only {item['qty']} on hand, so at most {item['qty']} can be discounted; "
                          f"the order of {order_qty} is {max(order_qty - item['qty'], 0)} short.")
        return _create_request(
            conn, ticket_id=ticket_id, kind="discount", sku=sku, size=size, quantity=quantity, unit_price=price,
            amount=quantity * price, cash_effect=0, reason=reason, requested_by=who,
            dedupe_key=f"discount:{ticket_id}:{sku}:{size}",
            details={
                "list_price": _money(item["list_price"]), "unit_cost": _money(item["unit_cost"]),
                "discount_pct": round(100 * (1 - price / item["list_price"]), 1),
                "total_at_list_price": _money(quantity * item["list_price"]),
                "margin_per_unit": _money(price - item["unit_cost"]), "qty_on_hand": item["qty"],
                "order_quantity": order_qty, "shortfall": max(order_qty - quantity, 0),
                "policy": DISCOUNT_POLICY,
            },
        )


@mcp.tool
def update_ticket(ticket_id: int, status: str, note: str, updated_by: str) -> dict:
    """Set a ticket's status and append a dated note. Only the Boss should call this.

    Writes tickets (and reads approval_requests). Statuses: open, in_progress, awaiting_approval,
    resolved. A ticket cannot be marked resolved while it still has pending approval requests.
    """
    status = status.strip().lower()
    if status not in TICKET_STATUSES:
        raise ToolError(f"status must be one of {TICKET_STATUSES}")
    if not (note or "").strip() or not (updated_by or "").strip():
        raise ToolError("note and updated_by are required")
    with _Transaction() as conn:
        ticket = _check_ticket(conn, ticket_id)
        pending = conn.execute(
            "SELECT COUNT(*) FROM approval_requests WHERE ticket_id = ? AND status = 'pending'", (ticket_id,)
        ).fetchone()[0]
        if status == "resolved" and pending:
            return {"updated": False, "message": f"{pending} approval request(s) still pending; use awaiting_approval."}
        stamp = f"[{_today(conn).isoformat()} {updated_by.strip()}] {note.strip()}"
        notes = f"{ticket['notes']} | {stamp}" if ticket["notes"] else stamp
        conn.execute("UPDATE tickets SET status = ?, notes = ? WHERE id = ?", (status, notes, ticket_id))
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return {"updated": True, "previous_status": ticket["status"], "ticket": dict(row)}


# ---------------------------------------------------------------------------
# Backend-only: a human's decision on an approval request. These are tagged
# "backend-only"; no agent toolset includes them (see backend/agents.py). The
# Problem 7 approve route is the only intended caller.
# ---------------------------------------------------------------------------


def _check_human(decided_by: str, request: sqlite3.Row) -> str:
    who = (decided_by or "").strip()
    if not who:
        raise ToolError("A human approver name is required")
    if who.lower().replace(" ", "_") in AGENT_NAMES or who.lower() == request["requested_by"]:
        raise ToolError("An agent cannot approve or reject a request, including its own")
    return who


def _add_month(day: date) -> date:
    month = day.month % 12 + 1
    year = day.year + (day.month == 12)
    for d in (day.day, 30, 29, 28):
        try:
            return day.replace(year=year, month=month, day=d)
        except ValueError:
            continue
    raise ValueError(day)


@mcp.tool(tags={"backend-only"})
def execute_approved_request(request_id: int, approved_by: str, note: str = "") -> dict:
    """BACKEND ONLY. Record a human's approval and carry out a pending request in one transaction.

    Writes approval_requests, payments, cash_accounts, and invoices (invoice) or leases (rent).
    Refuses if the request is not pending, the approver is an agent, the amount no longer
    matches the database, the vendor is blocked (purchase), or cash would go negative.
    Discounts move no cash. Nothing outside this database is paid, bought or sent.
    """
    with _Transaction() as conn:
        req = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        if req is None:
            return {"executed": False, "found": False, "message": f"Request {request_id} not found."}
        who = _check_human(approved_by, req)
        if req["status"] != "pending":
            return {"executed": False, "message": f"Request {request_id} is already {req['status']}."}
        today = _today(conn).isoformat()
        kind, amount = req["kind"], _money(req["amount"])
        result: dict = {"kind": kind, "amount": amount}
        payment_id = None

        if kind == "invoice_payment":
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (req["ref_id"],)).fetchone()
            if inv is None or inv["status"] != "open" or _money(inv["amount"]) != amount:
                return {"executed": False, "message": "Invoice is no longer open at the requested amount."}
        elif kind == "rent_payment":
            lease = conn.execute("SELECT * FROM leases WHERE id = ?", (req["ref_id"],)).fetchone()
            due = json.loads(req["details"])["due_date"]
            if lease is None or lease["next_due"] != due or _money(lease["monthly_rent"]) != amount:
                return {"executed": False, "message": "Lease rent or due date changed since the request."}
        elif kind == "purchase":
            blocked = conn.execute(
                "SELECT COUNT(*) FROM invoices WHERE vendor_id = ? AND status = 'open'", (req["ref_id"],)
            ).fetchone()[0]
            if blocked:
                return {"executed": False, "message": "Vendor still has an open invoice and will not ship."}

        if kind != "discount":
            moved = conn.execute(
                "UPDATE cash_accounts SET balance = ROUND(balance - ?, 2), date = ? WHERE name = ? AND balance >= ?",
                (amount, today, req["account"], amount),
            ).rowcount
            if moved != 1:
                return {"executed": False, "message": f"Not enough cash in {req['account']}; balance cannot go negative."}
            payment_kind = {"invoice_payment": "invoice", "rent_payment": "rent", "purchase": "purchase"}[kind]
            ref = req["ref_id"] if kind != "purchase" else req["id"]
            payment_id = conn.execute(
                "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
                (payment_kind, ref, amount, req["account"], today, who),
            ).lastrowid
            result["payment_id"] = payment_id
            if kind == "invoice_payment":
                conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (req["ref_id"],))
            elif kind == "rent_payment":
                nxt = _add_month(date.fromisoformat(due)).isoformat()
                conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (nxt, req["ref_id"]))
                result["lease_next_due"] = nxt
        else:
            result["approved_unit_price"] = req["unit_price"]

        bal = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (req["account"],)).fetchone()
        result["balance_after"] = _money(bal["balance"]) if bal else None
        conn.execute(
            "UPDATE approval_requests SET status = 'executed', decided_by = ?, decided_at = ?, decision_note = ?, "
            "payment_id = ?, result = ? WHERE id = ? AND status = 'pending'",
            (who, _now(), note.strip() or None, payment_id, json.dumps(result), request_id),
        )
        row = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
    return {"executed": True, "request": _request_row(row), "result": result}


@mcp.tool(tags={"backend-only"})
def reject_request(request_id: int, decided_by: str, note: str = "") -> dict:
    """BACKEND ONLY. Record a human's rejection of a pending request. Moves no money.

    Writes approval_requests.
    """
    with _Transaction() as conn:
        req = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        if req is None:
            return {"rejected": False, "found": False, "message": f"Request {request_id} not found."}
        who = _check_human(decided_by, req)
        if req["status"] != "pending":
            return {"rejected": False, "message": f"Request {request_id} is already {req['status']}."}
        conn.execute(
            "UPDATE approval_requests SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? "
            "WHERE id = ?",
            (who, _now(), note.strip() or None, request_id),
        )
        row = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
    return {"rejected": True, "request": _request_row(row)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Campus Customs MCP server")
    parser.add_argument("--http", action="store_true", help="Serve Streamable HTTP (default 127.0.0.1:8001)")
    args = parser.parse_args()
    if args.http:
        port = int(os.getenv("MCP_PORT", "8001"))
        mcp.run(transport="http", host="127.0.0.1", port=port)
    else:
        mcp.run()
