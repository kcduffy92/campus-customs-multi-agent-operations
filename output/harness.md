# Campus Customs agent harness

This harness describes the shop's data and rules for the agents. Later problems will keep adding to it.

## Databases

| File | Role |
|---|---|
| `data/campus_customs.db` | Original shop database. Keep it untouched and use it to reset. |
| `data/campus_customs_new.db` | Working copy. The MCP server and backend point here, and tools update it as tickets are resolved. |

To reset before a full run, copy `data/campus_customs.db` over `data/campus_customs_new.db`.

The shop's "today" is `desk.date_today` (2026-08-31), not the system clock.

---

## Tables (Problem 2)

There are 9 tables. Each one lists its fields, types and key constraints, and why it matters for the agents.

### `desk` (1 row)
- **Fields:** `date_today` TEXT NOT NULL, `notes` TEXT
- **Why it matters:** it sets "today" for the shop, which every agent uses to decide what is due or overdue.

### `tickets` (3 rows)
- **Fields:** `id` INTEGER PK, `type` TEXT NOT NULL, `requester` TEXT NOT NULL, `subject` TEXT NOT NULL,
  `sku` TEXT, `size` TEXT, `qty` INTEGER, `lease_id` INTEGER FK→`leases.id`,
  `invoice_id` INTEGER FK→`invoices.id`, `status` TEXT NOT NULL, `notes` TEXT, `created_at` TEXT NOT NULL
- **Why it matters:** it is the work queue. Agents read each open ticket, follow its links, and record the outcome
  in `status` and `notes`.

### `inventory` (10 rows)
- **Fields:** `sku` TEXT NOT NULL, `name` TEXT NOT NULL, `size` TEXT NOT NULL, `qty` INTEGER NOT NULL,
  `location` TEXT NOT NULL. PK (`sku`, `size`).
- **Why it matters:** it shows whether an order can be filled from stock, and where to find the item.

### `pricing` (4 rows)
- **Fields:** `sku` TEXT PK, `unit_cost` REAL NOT NULL, `list_price` REAL NOT NULL
- **Why it matters:** list price and unit cost set the limits for quotes and discount decisions (no selling below
  cost).

### `vendors` (3 rows)
- **Fields:** `id` INTEGER PK, `name` TEXT NOT NULL, `specialty` TEXT NOT NULL, `lead_days` INTEGER NOT NULL
- **Why it matters:** it shows who can restock what, and `lead_days` sets how long a restock takes.

### `invoices` (1 row)
- **Fields:** `id` INTEGER PK, `vendor_id` INTEGER NOT NULL FK→`vendors.id`, `amount` REAL NOT NULL,
  `due_date` TEXT NOT NULL, `status` TEXT NOT NULL, `description` TEXT
- **Why it matters:** it lists what the shop owes vendors. A vendor will not ship new product while it has an open
  unpaid invoice.

### `leases` (1 row)
- **Fields:** `id` INTEGER PK, `space_name` TEXT NOT NULL, `landlord` TEXT NOT NULL, `monthly_rent` REAL NOT NULL,
  `next_due` TEXT NOT NULL, `notes` TEXT
- **Why it matters:** it holds the rent obligation. Agents check the amount and due date when a rent notice
  arrives.

### `cash_accounts` (1 row)
- **Fields:** `name` TEXT PK, `balance` REAL NOT NULL, `date` TEXT NOT NULL
- **Why it matters:** it is the only source of cash. The pay tool must refuse if the balance would go negative,
  and no revenue comes in.

### `payments` (0 rows)
- **Fields:** `id` INTEGER PK, `kind` TEXT NOT NULL, `ref_id` INTEGER, `amount` REAL NOT NULL,
  `account` TEXT NOT NULL, `paid_at` TEXT NOT NULL, `approved_by` TEXT NOT NULL
- **Why it matters:** it is the ledger where every approved payment is recorded, including who approved it.
  Human approval is required for every payment.

---

## How the three open tickets link to other tables

| Ticket | Request | Links | Key facts (2026-08-31) |
|---|---|---|---|
| **101** `customer_order` (Tauhid Zaman) | 1 × CC-TEE-WHITE, size S | `inventory` and `pricing` by (sku, size). `invoice_id` 501 → `invoices`, then `vendor_id` 1 → `vendors` | Size S stock is **0**. Invoice 501 is the Bulldog Print Co rush reprint of this tee: **$840, open, 3 days overdue**. Lead time is 5 days. |
| **102** `rent_notice` (Elm City Properties) | Rent due | `lease_id` 1 → `leases`, then `cash_accounts` and `payments` | Rent is **$2,400**, due 2026-09-02, in 2 days. Checking has **$3,400**. |
| **103** `price_override` (Yale AI Club) | 20 × CC-HOOD-NAVY, size M, bulk discount | `inventory` and `pricing` by (sku, size). Possibly `vendors` for a reprint | Only **8** in stock (12 short). List price $58.00, unit cost $22.00. |

Together, the tickets compete for the same $3,400. Paying invoice 501 and the rent leaves $160.

## Constraints to keep in mind

- Foreign keys are off by default (`PRAGMA foreign_keys = 0`). Turn them on in any connection that writes.
- There are no CHECK constraints. Guard against negative stock and negative cash in the tools.
- Money is stored as REAL. Round to cents.
- `payments.ref_id` is linked to an invoice or a lease depending on `payments.kind`, and has no foreign key.

The full query evidence is in [`docs/problem2_database_exploration.md`](../docs/problem2_database_exploration.md).

---

## MCP tools (Problem 3)

The server is `mcp_server/server.py` (FastMCP, `campus-customs`), and it uses `data/campus_customs_new.db`. All
three tools are **read-only**: the database is opened with `mode=ro`. They return only database values. A missing
record comes back as `"found": false` instead of a guess.

### `get_vendor_invoice_status(invoice_id)`
- **Reads:** `invoices`, `vendors`, `desk`
- **Helps unlock:** **Ticket 101** (Bulldog tee, size S, for Tauhid Zaman)
- **Why it's the right tool:** size S is at 0 and only Bulldog Print Co can reprint it. That vendor won't ship while
  invoice 501 ($840, due 2026-08-28) is still open, so this tool shows the restock is blocked by an invoice that is
  3 days overdue as of `desk.date_today`. It also returns the vendor's 5-day lead time.

### `check_rent_due(lease_id)`
- **Reads:** `leases`, `cash_accounts`, `desk`
- **Helps unlock:** **Ticket 102** (rent notice from Elm City Properties)
- **Why it's the right tool:** it checks the emailed rent notice against lease 1 ($2,400, due 2026-09-02, 2 days
  away) and confirms checking's $3,400 covers it without going negative. That is what a human approver needs to
  see before authorizing payment, and this tool pays nothing.

### `check_stock_and_pricing(sku, size, requested_quantity=None)`
- **Reads:** `inventory`, `pricing`
- **Helps unlock:** **Ticket 103** (Yale AI Club wants 20 navy hoodies in M at a bulk discount). It also confirms
  ticket 101's size S tee is at 0.
- **Why it's the right tool:** with `requested_quantity=20` it shows only 8 size-M hoodies exist (12 short), and it
  gives the $58.00 list price and $22.00 unit cost. That is the stock and cost floor any discount decision has to
  respect. No discount is assumed.

Tested with `tests/check_mcp_tools.py` (26/26 checks pass, and neither database changed).

---

## Approval queue table (Problem 5)

`approval_requests` is the only table added to the working copy. The MCP server creates it on the first write
(`CREATE TABLE IF NOT EXISTS`, so it's safe to run again). The original `data/campus_customs.db` keeps exactly
the nine tables above, and a reset brings the working copy back to those nine.

- **Fields:**
  - `id` INTEGER PK and `request_uid` TEXT UNIQUE (a UUID)
  - `ticket_id` FK→`tickets.id`
  - `kind` (`invoice_payment`, `rent_payment`, `purchase`, `discount`) and `ref_id` (the invoice, lease or
    vendor)
  - `sku`, `size`, `quantity`, `unit_price`
  - `amount` (≥ 0) and `cash_effect` (≤ 0), plus `account`, `details` (JSON) and `reason`
  - `requested_by` (an agent) and `requested_at`
  - `status` (`pending`, `executed`, `rejected`)
  - `decided_by`, `decided_at`, `decision_note`, `payment_id` FK→`payments.id`, and `result` (JSON)
- **Rules:**
  - A unique index allows only one *pending* request per item.
  - The request tools also refuse an item that has already been executed.
  - Only a pending request can be decided, so a request can't be executed twice.
- **Why it matters:** agents can only *prepare* money moves. A person decides each one, and the row records who
  decided, when, and what happened.

## MCP tools (Problem 5 additions)

The server now has 15 tools. Full details are in [`mcp_server/README.md`](../mcp_server/README.md).

| Tool | Tables it uses | Ticket |
|---|---|---|
| `get_vendor_invoice_status` (Problem 3) | `invoices`, `vendors`, `desk` | 101 |
| `check_rent_due` (Problem 3) | `leases`, `cash_accounts`, `desk` | 102 |
| `check_stock_and_pricing` (Problem 3) | `inventory`, `pricing` | 103, 101 |
| `list_tickets` | `tickets` | all |
| `get_ticket` | `tickets`, `approval_requests`, `desk` | all |
| `list_vendors` | `vendors`, `invoices` | 101, 103 |
| `get_cash_balance` | `cash_accounts`, `approval_requests`, `desk` | 101, 102, 103 |
| `list_approval_requests` | `approval_requests` | all |
| `request_invoice_payment` | `invoices`, `cash_accounts` → writes `approval_requests` | 101 |
| `request_rent_payment` | `leases`, `cash_accounts` → writes `approval_requests` | 102 |
| `request_purchase` | `vendors`, `invoices`, `inventory`, `pricing`, `cash_accounts` → writes `approval_requests` | 101, 103 |
| `request_discount` | `pricing`, `inventory` → writes `approval_requests` | 103 |
| `update_ticket` | writes `tickets`, reads `approval_requests` | all |
| `execute_approved_request` (**backend only**) | writes `approval_requests`, `payments`, `cash_accounts`, `invoices` / `leases` | 101, 102, 103 |
| `reject_request` (**backend only**) | writes `approval_requests` | all |

## The five agents (Problem 5)

The agents are built with PydanticAI in [`backend/agents.py`](../backend/agents.py), with data types in
[`backend/models.py`](../backend/models.py) and one prompt per agent in `backend/prompts/`.

- **Model:** every agent uses `gpt-6-luna` through Portkey (`PORTKEY_API_KEY`). Any other `OPENAI_MODEL` stops
  startup.
- **MCP connection:** agents reach the campus-customs MCP server over HTTP (`http://127.0.0.1:8001/mcp`). Each
  agent sees a filtered list of tools.
- **Output:** each agent returns a structured `AgentReport`: a summary, facts with their source tool,
  approval request IDs, a draft customer reply, a recommended status, and open issues.

| Agent | Prompt | Responsibilities | MCP tools | Usually delegates to | Safety boundary |
|---|---|---|---|---|---|
| **Boss** | `boss.md` | Reads the ticket, routes it to only the agents it needs, combines their reports, and sets the final status and note. | `get_ticket`, `list_tickets`, `list_approval_requests`, `update_ticket` | The first specialist for the ticket type, then Customer Service if a reply is needed | Never touches money. Can't mark a ticket resolved while requests are pending. |
| **Inventory** | `inventory.md` | Stock, shortages, location, prices, vendors, and restock blockers. | `check_stock_and_pricing`, `list_vendors`, `get_vendor_invoice_status` | Accounting, when a restock needs money | Read-only. Never promises stock that isn't on hand. |
| **Accounting** | `accounting.md` | Cash, invoices, rent amounts, discount limits, and every approval request. | `get_vendor_invoice_status`, `check_rent_due`, `check_stock_and_pricing`, `get_cash_balance`, `list_approval_requests`, `request_invoice_payment`, `request_rent_payment`, `request_purchase`, `request_discount` | Inventory or Facilities, for missing facts | Files requests only. Checks the balance left after pending requests. Never below unit cost. |
| **Facilities** | `facilities.md` | Checks rent notices against the lease, and flags mismatches and urgency. | `get_ticket`, `check_rent_due` | Accounting, to queue confirmed rent | Never pays. Never invents lease terms. |
| **Customer Service** | `customer_service.md` | Drafts an honest reply to the requester. | `get_ticket`, `check_stock_and_pricing`, `list_approval_requests` | Inventory, for missing facts | Drafts only; nothing is sent. Doesn't promise pending discounts or unconfirmed dates. Doesn't reveal costs or cash. |

### Delegation

- **Full connectivity:** every agent has one `delegate(to_agent, task)` tool and can reach any of the other four.
- **Guards** (in `check_delegation`), checked before any work starts:
  - no self-delegation and no unknown agents
  - no circular delegation: an agent can't call anyone already in the chain, including the Boss
  - at most 3 levels below the Boss
  - at most 8 delegations per ticket
- **Repeated tasks:** an identical task, after normalizing the words, gets the earlier report back without
  running the agent again.
- **Refusals:** a refused delegation is returned to the agent as a structured result, and the agent finishes
  with what it has.
- **Identity:** `requested_by`, `updated_by` and `ticket_id` are filled in by code before each MCP call. The
  model can't claim to be another agent or act on another ticket.

### Audit trail

Every run appends to `output/audit_trail.json`; the file is never wiped.

- **Per entry:** `run_id`, `ticket_id`, `agent`, `parent_agent`, `depth`, `chain`, `action`, plus the step's
  details (the MCP `tool`, its `args` and `result`, the delegation's target and task, and token `usage`).
- **Actions recorded:**
  - `run_started` / `run_finished`
  - `agent_started` / `agent_finished`
  - `model_request` / `model_response` (each agent-loop step, with the tool calls it requested and its tokens)
  - `mcp_tool_call`, `mcp_tool_refused`, `mcp_tool_error`
  - `delegation_started`, `delegation_finished`, `delegation_cached`, `delegation_refused`, `delegation_failed`
- **Safe writes:** a thread lock plus a cross-process lock file guard each append, and the file is replaced
  atomically. An unreadable file is kept as a backup instead of being overwritten.
- **No secrets:** known secret values are redacted.

## Safety

**Real customers**
- Agents only state facts that an MCP tool returned in the same run. A missing record is reported as not found.
- Customer replies are drafts for a person to review. Nothing is emailed or sent.
- Customer Service never promises a discount that is still pending or a date that isn't confirmed, and never
  reveals costs, margins, cash or unpaid vendor bills.

**Real money**
- **Who can do what:** agents can only *request* payments, purchases and discounts. Only the Boss can change a
  ticket, and only Accounting can file money requests.
- **Who approves:** the tools that execute or reject a request are tagged `backend-only`. They aren't in any
  agent's allowlist, and the tool-call hook refuses them as well.
- **Human sign-off:**
  - Execution needs a named person, who can't be an agent and can't be the requester.
  - Each request can be decided only once.
  - Every decision is recorded with who, when, and the result.
- **Money checks:**
  - Amounts come from the database, not from the model.
  - Discounts can't go below unit cost.
  - A blocked vendor's purchase can't be executed.
  - The cash update fails if the balance would go negative, and the whole transaction rolls back.
- **Competing tickets:** the three tickets compete for the same $3,400. `get_cash_balance` shows what is left
  after pending requests, so Accounting can see overcommitment before a person approves anything.
- **Nothing leaves the shop:** no real bank, vendor, landlord or customer system is connected.

**Data**
- The MCP server refuses to open the original database. Tests and live checks run on temporary copies.
- Ticket notes are appended to, never replaced. The original nine-table schema is never altered.

**Token limits**
- All agents in one ticket run share a single budget: 30 model requests, 40 tool calls and 200,000 total tokens
  (`backend/config.py`).
- Hitting the budget stops the whole run with status `stopped_usage_limit`.
- The delegation depth (3) and per-ticket count (8) limit how far a ticket can spread, and repeated tasks are
  answered from cache.
- Only one run per ticket can be active at a time, and audit previews are capped at 600 characters.

Tests: `tests/check_problem5_tools.py` (45 checks) and `tests/check_agent_team.py` (33 checks). Neither calls a
model, and both use temporary databases.

## Verified live run (Problem 5)

This was one real run of `tests/live_agent_test.py 102` on 2026-11-03. It ran on a **temporary copy of the
original database** behind its own HTTP MCP server, and the copy was deleted afterwards. The full record is in
[`docs/problem5_live_test.json`](../docs/problem5_live_test.json). Its 40 steps are the first run in
`output/audit_trail.json`, which is labelled `problem5-live-test`.

- **Model:** requested as `gpt-6-luna` through Portkey (`x-portkey-provider: openai`). Each response reported
  its model as `gpt-6-luna-global`, which is the name the provider returns for the deployment that served it.
- **Agents that ran:** Boss, Facilities and Accounting. Inventory and Customer Service weren't needed for a rent
  notice.
- **Delegations:** Boss → Facilities ("check rent notice against lease ID 1"), then Facilities → Accounting
  ("Queue the rent payment for lease 1 ... $2,400.00, due 2026-09-02"). No delegations were refused or repeated.
- **MCP tool calls (8):**
  - Boss: `get_ticket`
  - Facilities: `get_ticket`, `check_rent_due`
  - Accounting: `check_rent_due`, `get_cash_balance`, `list_approval_requests`, `request_rent_payment`
  - Boss: `update_ticket`
- **Facts vs. the database:** rent was $2,400.00, due 2026-09-02, landlord Elm City Properties, checking
  $3,400.00, and $1,000.00 left after rent. All of these match `leases` and `cash_accounts`.
- **Outcome on the copy:**
  - Approval request 1 (`rent_payment`, $2,400.00, `pending`, requested by `accounting`) was filed.
  - Ticket 102 was set to `awaiting_approval`, with a note appended.
  - Checking stayed at $3,400.00, and there were 0 payment rows: no money moved.
- **Usage:** 10 model requests, 10 tool calls and 20,937 tokens (19,289 input, 1,648 output). That's well
  under the shared limits of 30, 40 and 200,000.
- **Audit events:**
  - `run_started` / `run_finished`
  - 3 `agent_started` / `agent_finished`
  - 10 `model_request` / `model_response`
  - 8 `mcp_tool_call`
  - 2 `delegation_started` / `delegation_finished`
  - The API key does not appear in the trail.
- **Databases:** the original and working databases were unchanged (same SHA-256 before and after).

## Backend API routes (Problem 7)

Start from the `backend/` folder with `uvicorn main:app --reload --port 8000` (serves `http://localhost:8000`;
interactive docs at `/docs`). The backend starts the campus-customs MCP server on `127.0.0.1:8001` and stops
it on shutdown; if 8001 is already taken it refuses to start and says so.

- `GET /` — list of every route with its purpose.
- `GET /health` — backend status: model (`gpt-6-luna`), MCP server reachable and its 15 tools, active run, reset epoch.
- `GET /tickets` — the three tickets, each `open` or `resolved`, plus its stage and pending/approved/rejected request counts.
- `GET /tickets/{ticket_id}` — one ticket with its notes, stage and approval requests.
- `POST /tickets/{ticket_id}/run` — start the agent team on a ticket in the background; returns a `run_id` (202). One run at a time; 409 if busy, 404 if no such ticket.
- `POST /tickets/{ticket_id}/resolve` — a named person marks a ticket resolved after confirming the outside step (e.g. the customer received the tee).
- `GET /runs` — runs started by this backend since it started.
- `GET /runs/{run_id}` — one run's status (`running`, `completed`, `error`, `stopped_usage_limit`), final report, delegations and token use.
- `GET /events?since=&run_id=&ticket_id=&limit=` — recent agent events for the board: who is active, who delegated to whom, which MCP tool was used, what each agent concluded, approvals filed, run finished; `next_cursor` for polling.
- `GET /approvals?status=pending|executed|rejected|all&ticket_id=` — the approval queue (pending by default).
- `POST /approvals/{request_id}/approve` — a person approves a request (`approved_by`, `expected_amount`, `confirm: true`); the **only** route that moves cash.
- `POST /approvals/{request_id}/reject` — a person rejects a request (`decided_by`, `confirm: true`); moves no cash.
- `GET /cash` — the checking balance from `cash_accounts`, money committed to pending requests, and what is left after them.
- `POST /reset` — copy the original database over the working copy (`confirm: "RESET"`); refused during a run or approval.

### How the routes keep money safe

- Agents only file requests. `execute_approved_request` is called from one place, the approve route; no
  agent's tool list includes it.
- Approve needs a person's name (agent and character names get 403), `confirm: true`, and the exact amount the
  person saw (a different amount gets 409). The tool then re-checks, in one locked transaction, that the request
  is still pending, the invoice/lease amount is unchanged, the vendor is not blocked, and the balance covers it.
- A request executes at most once: a second approve gets 409. Runs, approvals and resets share one lock, and
  only one agent run can be active, because all three tickets draw on the same $3,400.
- **Not production authentication.** Approver names are recorded in `payments.approved_by`,
  `approval_requests.decided_by` and an `approval_decided` audit event, but they are not verified. This is a
  classroom simulation on localhost.

### Ticket stages

The database keeps its four statuses (`open`, `in_progress`, `awaiting_approval`, `resolved`). The API adds a
derived `stage`, and after each human decision it sets the status and appends a note saying what is still
outstanding. It never claims a delivery, a supplier confirmation or a customer acceptance.

| Stage | When | Database status set after a decision |
|---|---|---|
| `not_started` | No run on this database since the last reset | `open` |
| `agents_working` | A run is active on the ticket | (unchanged) |
| `investigated` | A run completed and filed nothing | (unchanged) |
| `awaiting_approval` | A request is pending | `awaiting_approval` |
| `approved_awaiting_external` | Approved, but something outside still has to happen | `in_progress` |
| `needs_follow_up` | Every request was rejected | `open` |
| `resolved` | The database says `resolved` | `resolved` |

- **102:** a recorded rent payment is the whole job, so the ticket becomes `resolved` once nothing is pending or rejected.
- **101:** paying invoice 501 leaves it `in_progress`: the reprint still has to arrive and reach the customer.
- **103:** an approved discount leaves it `in_progress`: the customer has not accepted and the shortage remains.
- 101 and 103 become `resolved` only when a person uses `POST /tickets/{id}/resolve` and states what they confirmed.

### Events and resets

- `agent_finished` audit entries now also carry `summary`, `customer_reply`, `approval_request_ids`,
  `recommended_ticket_status` and `open_issues`, so `/events` can show what each agent concluded.
- Each event has `character` (mario, crash, spyro, ryu, sonic) for the Problem 6 command network.
- `run_started` events carry `this_database` (false for runs made on another copy, such as the Problem 5
  isolated live test), and human decisions report the request type as `request_kind`. Both were added
  for the Problem 8 desk.
- A reset appends a `database_reset` entry and never deletes earlier ones. Every event carries an `epoch` (the
  number of resets before it), so the dashboard can tell runs before and after a reset apart.

## The dashboard (Problem 8)

`frontend/` is the live desk, built with React + Vite + TypeScript. Start it from `frontend/` with `npm run dev`
(on Windows PowerShell, `npm.cmd run dev` if script execution is blocked) and open `http://localhost:5173`. The
backend at `http://localhost:8000` allows that origin. Design choices are explained in `output/design.md`.

- **Layout:**
  - left: mission select (three ticket cards) and the run panel
  - centre: the command network and the live agent feed
  - right: the treasure vault (cash) and the human approval gates
  - bottom: a card per agent saying what it did
- **Live data only:** it polls `/events` every second during a run (every 3 seconds otherwise) and refreshes
  `/tickets`, `/cash` and `/approvals`. Every animation comes from a real event; with no events, nothing moves.
- **Command network:** Mario at the top and the four specialists below. Dashed lines show the Expected plan; solid
  or pulsing lines show real delegations. It shows the MCP tool in use, a lock while a request waits for a
  person, and dims agents that never ran. After a run it marks routes as planned, planned but not used, or
  not in the plan.
- **Two separate stamps:** *Agent run* (from events: working, complete, failed) and *Ticket* (from the database).
  "TICKET RESOLVED" appears only when the database says resolved. The label names the resolution type
  (operational, or administrative with outside steps outstanding).
- **Approval gates:** each shows the exact amount, purpose, ticket and requesting agent. Approving needs the
  person's name, a "reviewed" checkbox, and a one-second hold (or Enter twice). It can't be submitted twice while
  the API call runs, and the result shown is the backend's own answer. Gates are locked during a run.
- **Record the resolution:** a person chooses *operational* or *administrative*, writes a resolution note, and ticks
  "I confirm this resolution note accurately describes what has and has not happened".
- **Vault:** shows the balance, pending commitments, what's left after them, and approved and rejected decisions.
  After a payment it shows the old balance struck through next to the new one, both from the backend.
- **Reset:** you type `RESET`. It is blocked during a run.
- **Sound:** off by default; character sounds play for real events only.
- **Tests:**
  - `npm test` runs 31 Vitest tests
  - `npm run build` covers the TypeScript check and the production build
  - `tests/dev_fake_backend.py` gives a scripted backend on a temporary database copy for browser testing

## Simulation policy and resolution rules (Problem 9 preparation)

These rules were set before the full three-ticket run. Each one is in an agent prompt, and most are also
enforced in code.

### Simulation discount policy: an assumption, not a database rule
The shop's database has no discount policy. For this educational simulation we assume:

- A group order of **10 or more units** may get **up to 10% off list price**.
- The discounted price must stay **above unit cost**.
- The discount covers **only units that can actually be supplied**: stock on hand, since the database records
  no other fulfillment arrangements. Whether the order qualifies depends on the size of the order the customer
  asked for. Any shortfall is reported, never hidden.
- Every discount needs human approval before it becomes an offer.

It is written into `backend/prompts/accounting.md`, and `request_discount` in `mcp_server/server.py` enforces
it. Discount requests outside the policy are refused with the reason, and each discount request records the
order size, the shortfall and a policy note. For ticket 103 (20 × CC-HOOD-NAVY M, 8 on hand, list $58.00,
unit cost $22.00), the most the policy allows is 8 units at $52.20 or more ($417.60 for 8). That leaves a 12-unit
shortfall.

### Agents never mark a ticket resolved
- `backend/agents.py` refuses any agent call to `update_ticket` with `status: "resolved"` and records the refusal
  in the audit trail as `mcp_tool_refused`.
- The Boss sets `awaiting_approval` while a request is pending. When the team is done but something outside the
  desk is outstanding, it sets `in_progress`. It may *recommend* `resolved` in its report.
- Only two paths set `resolved`:
  1. the backend's rent rule, once an approved rent payment is recorded (ticket 102)
  2. a named person using `POST /tickets/{id}/resolve` in the dashboard

### Resolution categories
| `resolution_type` | Meaning | Set by |
|---|---|---|
| `operational` | The real-world outcome has happened and the person knows it has. | The rent rule (automatically), or a person |
| `administrative` | The desk's work is done and the ticket is closed, but the note lists outside steps still outstanding (merchandise, delivery, stock, a customer's decision). | A person |

The resolve route takes an optional `resolution_type`. It is written into the ticket note ("(administrative
resolution)") and into the `ticket_updated` audit event. The dashboard asks the person to choose a type, write
the resolution note, and tick **"I confirm this resolution note accurately describes what has and has not
happened."**

An administrative note records:
- the internal actions completed
- the human approvals actually granted
- the payments actually recorded
- any customer replies drafted but not sent
- what is still outstanding

It never claims an outside event, such as a reprint shipped, merchandise delivered or an offer accepted,
unless there is evidence for it.

### What the agent prompts now say
- **Boss:** coordinates and recommends; never resolves. It routes only to the specialists a ticket needs. Only
  Accounting files requests, and Inventory may pass a need to Accounting. Discounts are judged on supply, cost,
  price and margin, not on cash.
- **Inventory:** keeps verified facts separate from possibilities. A vendor's specialty doesn't prove it
  supplies a SKU, so the prompt says not to assume Bulldog Print Co makes the hoodies. A "rush reprint" invoice
  suggests the reprint was already ordered, and paying it may lift the shipping block, but neither proves
  anything shipped. It checks existing invoices before suggesting a purchase.
- **Accounting:** before any purchase, checks for an invoice already covering it, never files duplicates or
  assumes a supplier from specialty, and checks cash after pending commitments. It applies the simulation
  discount policy and shows its working.
- **Facilities:** unchanged.
- **Customer Service:** lead times are estimates in days, not business days unless the source says so, and
  never a delivery date. A payment or pending approval is not a shipment. It keeps "available now",
  "still looking into" and "needs confirmation" apart, never writes as if the customer accepted, and keeps
  internal finances out of replies.

<!-- P9:run -->
## Verified full run (Problem 9)

Built from audit entries 40–240 and the working database by `tests/build_problem9_outputs.py`. Details are in `output/resolved_tickets.json` and `docs/problem9_run_findings.md`.

- **Reset:** by Kate Duffy at 2026-11-04T23:58:09.875+00:00. Checking started at $3,400.00.
- **Order:** 102 → 101 → 103. Every approval, reset and resolution was done by Kate Duffy in the dashboard.

- **Ticket 102 (operational):** Boss called first: Ryu. Delegations: Mario → Ryu, Ryu → Spyro. 22,772 tokens. The rent notice matched lease 1 (Elm City Properties, $2,400.00 due 2026-09-02). Kate Duffy approved request #1; it was paid as payment 1, and the lease is next due 2026-10-02. Resolved operationally: the recorded payment completes the ticket.
- **Ticket 101 (administrative):** Boss called first: Crash. Delegations: Mario → Crash, Crash → Spyro, Mario → Sonic. 36,167 tokens. The size S tee was out of stock (0 on hand). Invoice 501 ($840.00, "Rush reprint CC-TEE-WHITE S") was paid as payment 2 after Kate Duffy approved request #2; no duplicate purchase was made. Shipment and delivery of the reprint are not confirmed, and the customer reply was drafted but not sent. Resolved administratively.
  - Customer Service's draft reply disclosed internal invoice and approval details, which its prompt forbids (audit entry 129). It was not sent. Kate Duffy chose to record the issue, not re-run the ticket.
- **Ticket 103 (administrative):** Boss called first: Crash. Delegations: Mario → Crash, Mario → Spyro, Mario → Sonic. 38,345 tokens. 8 of 20 CC-HOOD-NAVY size M were on hand, 12 short. Under the simulation discount policy, Kate Duffy approved request #3: 8 at $52.20 (10% off $58.00, total $417.60) as an offer. No cash moved and no purchase was requested. The club has not accepted, supply for the other 12 is unconfirmed, and the reply was drafted but not sent. Resolved administratively after a re-run.
  - First run (audit entries 141–187) filed no discount request. Mario asked whether a request could be filed without a customer-proposed price, and Accounting declined to propose one.
  - In the first run, Accounting looked up the stock with sku "hoodie" instead of CC-HOOD-NAVY and got not-found (audit entry 165).
  - After a targeted prompt fix (Boss: Accounting proposes the price; Accounting: propose within policy, use exact SKUs), the second run (audit entries 188–237) filed discount request #3 within policy, using the exact SKU.
  - In the second run, Mario told Inventory to rely on the previous run's ticket note, and Inventory passed requested_quantity 12 instead of 20 (audit entry 199). Inventory explained the mismatch, and the final figures are correct.

- **Cash:** $3,400.00 − $3,240.00 = **$160.00**, which matches `cash_accounts`.
- **Dashboard fix during the run:** the resolved-ticket label now shows the resolution type, instead of "Fully resolved" for every resolved ticket.

<!-- /P9:run -->
