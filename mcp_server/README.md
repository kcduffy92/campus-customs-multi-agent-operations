# Campus Customs MCP server

## What it is for

This FastMCP server gives every Homework 5 agent controlled access to the Campus Customs shop database. The agents
call its tools instead of writing SQL, so they can only see real database values. Nothing is made up: a missing
record comes back as `"found": false`. The agents in `backend/` have no other way into the database.

## Database

It uses **`data/campus_customs_new.db`**, the working copy. It never touches the original
`data/campus_customs.db`, which is kept for resets. Setting `CAMPUS_CUSTOMS_DB` points the server at an isolated
copy instead; the tests and the live agent check do this. The server refuses to run against the original file.

The shop's "today" comes from `desk.date_today`, not the system clock.

Read tools open the database with `mode=ro`. Write tools each run as one `BEGIN IMMEDIATE` transaction with
foreign keys on, and roll back on any error. The first write creates the `approval_requests` table
(`CREATE TABLE IF NOT EXISTS`). The nine original tables are never altered.

## Tools (15)

### Problem 3 (read-only)

| Tool | Tables | Ticket | What it returns |
|---|---|---|---|
| `get_vendor_invoice_status(invoice_id)` | `invoices`, `vendors`, `desk` | 101 | The invoice's amount, status and days past due; the vendor and its lead time; the vendor's open invoices; and whether the vendor is blocked from shipping. |
| `check_rent_due(lease_id)` | `leases`, `cash_accounts`, `desk` | 102 | The rent amount, due date and days until due; each cash account's balance; and whether it covers the rent. Pays nothing. |
| `check_stock_and_pricing(sku, size, requested_quantity=None)` | `inventory`, `pricing` | 103 (also 101) | Quantity on hand, location, unit cost and list price. With a quantity, it also returns the shortage and the totals at list price and at unit cost. |

### Problem 5: agent tools

| Tool | Tables | Ticket | What it does |
|---|---|---|---|
| `list_tickets(status=None)` | `tickets` | all | Lists the work queue. |
| `get_ticket(ticket_id)` | `tickets`, `approval_requests`, `desk` | all | Returns one ticket and the approval requests already filed for it. |
| `list_vendors()` | `vendors`, `invoices` | 101, 103 | Each vendor's specialty and lead time, its open invoices, and whether it is blocked from shipping. |
| `get_cash_balance()` | `cash_accounts`, `approval_requests`, `desk` | 101, 102, 103 | The balance, the total of pending requests, and the balance left if all of them were approved. |
| `list_approval_requests(ticket_id=None, status=None)` | `approval_requests` | all | The requests filed so far, with their status. |
| `request_invoice_payment(ticket_id, invoice_id, reason, requested_by)` | reads `invoices`, `cash_accounts`; writes `approval_requests` | 101 | Queues payment of an open invoice. The amount comes from the invoice. |
| `request_rent_payment(ticket_id, lease_id, reason, requested_by)` | reads `leases`, `cash_accounts`; writes `approval_requests` | 102 | Queues the lease's `monthly_rent` for its `next_due` date. |
| `request_purchase(ticket_id, vendor_id, sku, size, quantity, reason, requested_by)` | reads `vendors`, `invoices`, `inventory`, `pricing`, `cash_accounts`; writes `approval_requests` | 101, 103 | Queues a stock purchase at quantity × unit cost, and flags it when the vendor is blocked. |
| `request_discount(ticket_id, sku, size, quantity, unit_price, reason, requested_by)` | reads `pricing`, `inventory`; writes `approval_requests` | 103 | Queues a discounted price. It must be at least the unit cost and below the list price. It moves no cash and leaves `pricing` unchanged. |
| `update_ticket(ticket_id, status, note, updated_by)` | writes `tickets`; reads `approval_requests` | all | Sets the status (`open`, `in_progress`, `awaiting_approval` or `resolved`) and appends a dated note. It refuses `resolved` while any request is still pending. |

The request tools never move money. They refuse a duplicate of a pending or executed request (same invoice; same
lease and due date; same purchase or discount line), and return the existing request instead.

### Problem 5: backend-only tools (tagged `backend-only`; no agent can call them)

| Tool | Tables | What it does |
|---|---|---|
| `execute_approved_request(request_id, approved_by, note="")` | writes `approval_requests`, `payments`, `cash_accounts`, and `invoices` (invoices) or `leases` (rent) | Carries out a human's approval in one transaction. It refuses if the request isn't pending, the approver is an agent, the amount no longer matches the database, the vendor is blocked (purchases), or cash would go negative. Invoices are marked `paid`. Rent moves `next_due` forward one month. Purchases record a payment; the stock arrives after the vendor's lead time, so `inventory` is unchanged. Discounts move no cash. |
| `reject_request(request_id, decided_by, note="")` | writes `approval_requests` | Records a human's rejection of a pending request. |

The Problem 7 approve route is the only intended caller of these two tools. Nothing outside the database is paid,
bought or sent.

## Run

From the `Homework 5` folder, with the virtual environment set up (`pip install -r requirements.txt`):

```bash
.venv/Scripts/python.exe mcp_server/server.py          # stdio (Claude Code, .mcp.json)
.venv/Scripts/python.exe mcp_server/server.py --http   # http://127.0.0.1:8001/mcp (the agents)
```

`MCP_PORT` changes the HTTP port. The server only listens on localhost.

## Tests

```bash
.venv/Scripts/python.exe tests/check_mcp_tools.py       # Problem 3 tools, working database (read-only)
.venv/Scripts/python.exe tests/check_problem5_tools.py  # Problem 5 tools and approval queue, temporary copy
```
