# Homework 5 — AI Foundations (MGT 409, Yale SOM)

Course project for Homework 5 of AI Foundations, taught by Professor Zaman. The work is completed one problem
at a time, following the assignment instructions.

This project is independent of Homework 4. It may reuse architectural patterns from earlier work (FastAPI,
FastMCP, PydanticAI, AI calls routed through Portkey), but it shares no code, data, or configuration files with it.

## Status

- Problem 1 (Vibe coder prompts): `AI_prompts.md` is in place. It continues through the whole assignment.
- **Problem 2 (Study the Campus Customs database): complete.** Checked against the official Panel A and B
  instructions on 2026-11-03. The deliverable is [output/harness.md](output/harness.md), and the supporting query
  evidence is in [docs/problem2_database_exploration.md](docs/problem2_database_exploration.md).

- **Problem 3 (Build the MCP server): complete.** [mcp_server/server.py](mcp_server/server.py) is a FastMCP server
  with three read-only tools, one for each ticket. It is described in [mcp_server/README.md](mcp_server/README.md)
  and in the "MCP tools" section of [output/harness.md](output/harness.md). It is verified by
  `tests/check_mcp_tools.py` (26/26 checks pass). Checked against the official Panel A and B instructions on
  2026-11-03.

- **Problem 4 (Add the MCP server to vibe coder and test each tool): complete.** [.mcp.json](.mcp.json) at the
  project root registers the server with Claude Code. A Claude Code session opened in `Homework 5` connected to
  `campus-customs` and called each of the three tools for real. [output/mcp_smoke.json](output/mcp_smoke.json)
  records the student's prompt, the tool name, the arguments and the exact output for each call.
  At the time, `tests/verify_mcp_smoke.py --record` confirmed that every output matched `data/campus_customs_new.db`
  (37 fields) and that both databases were identical. The working copy has since changed (Problem 9), so check this
  evidence now with `tests/verify_mcp_smoke.py --original`. Checked against the official Panel A and B instructions on
  2026-11-03.
  - Known limitations: test prompt 1 was typed in the parent session and forwarded word for word to the connected
    session, which made the call. Prompts 2 and 3 didn't name a lease ID or SKU, so read-only SQL was used to pick
    the arguments (`lease_id 1`, `CC-HOOD-NAVY` size `M`). The JSON stores the tool names without Claude Code's
    `mcp__campus-customs__` prefix.

- **Problem 5 (Build the agent team and grow the MCP tools): complete.** Checked against the official Panel A
  and B instructions on 2026-11-03.
  - [backend/agents.py](backend/agents.py) defines five PydanticAI agents (Boss, Inventory, Accounting,
    Facilities, Customer Service), all on `gpt-6-luna` through Portkey. Prompts are in `backend/prompts/`, one
    file per agent, and data types are in [backend/models.py](backend/models.py).
  - Agents reach the MCP server over HTTP (`127.0.0.1:8001`). Each agent has a filtered tool list and a guarded
    `delegate` tool, and every step is appended to `output/audit_trail.json`.
  - The MCP server now has 15 tools, including a database-backed approval queue. Agents can only *request*
    money moves; the two execution tools are backend-only.
  - Deterministic tests pass, on temporary database copies:
    - `tests/check_mcp_tools.py` (26/26)
    - `tests/check_problem5_tools.py` (45/45)
    - `tests/check_agent_team.py` (33/33)
  - The live check passed on 2026-11-03: `tests/live_agent_test.py 102` ran on an isolated copy of the original
    database.
    - Boss → Facilities → Accounting, with 8 real MCP calls.
    - One pending $2,400 rent approval request was filed, and no money moved.
    - 20,937 tokens.
    - The record is in [docs/problem5_live_test.json](docs/problem5_live_test.json), and the 40 steps are in
      `output/audit_trail.json`.
  - Known limitations:
    - The responses report their model as `gpt-6-luna-global`, the provider's name for the deployment behind
      the requested `gpt-6-luna`.
    - The five prompts were drafted by the assistant and should be reviewed in the student's own words.

- **Problem 6 (Plan the three tickets): complete.** Checked against the official Panel A and B instructions on
  2026-11-03.
  - [output/desk_tickets.html](output/desk_tickets.html) ("Campus Customs: Agent Arcade") is one standalone page
    that opens with a double-click. It has five tabs: Ticket 101, Ticket 102, Ticket 103, Cash and Reflection.
  - Each ticket tab has an **Expected** section in the student's own words. It names who the Boss calls first and
    why, every expected delegation, the expected MCP tools, and the human approval gate. The **Actual** sections
    are left empty for a later problem, and Cash and Reflection only say "Coming in a later level."
  - The agents appear as game characters: Mario (Boss), Crash Bandicoot (Inventory), Spyro (Accounting), Ryu
    (Facilities) and Sonic (Customer Service). The art is original pixel art, and every sound is an original Web
    Audio synth placeholder. Sound is muted by default. Licensed clips can be pasted into `AUDIO_CLIPS` in the page.
  - Each ticket tab also has a **command network**: Mario at the top and the four specialists below, joined by
    SVG delegation arrows. It shows only the expected plan:
    - 101: Mario → Crash, Crash → Spyro (conditional), Mario → Sonic. Ryu is dimmed.
    - 102: Mario → Ryu, Ryu → Spyro. Crash and Sonic are dimmed.
    - 103: Mario → Crash, Mario → Spyro, Mario → Sonic. Ryu is dimmed.
  - Clicking a character or a connection shows who delegates, who receives the task, and why. A labelled, silent
    "Preview animation" demo shows the line states. `window.AgentArcade.network(id)` can later show real
    audit-trail events (`applyAuditEvents`) and compare them with the plan (`compare`); the page never calls it.
  - Screenshots of the network are in [docs/problem6_screenshots/](docs/problem6_screenshots/).
  - `tests/check_desk_tickets.py` (104/104) checks that the page is standalone and has the five tabs, that the
    approved wording appears word for word, that each network's routes and dimmed agents match the plan, that
    the Actual sections are empty, that the ticket facts match the working database, and that both databases
    are unchanged.
  - No agents were run, and nothing was written to either database.

- **Problem 7 (Backend routes): complete.** Checked against the official Panel A and B instructions on
  2026-11-03.
  - [backend/main.py](backend/main.py) is a FastAPI app with the routes listed in the "Backend API routes"
    section of [output/harness.md](output/harness.md): tickets (open or resolved), start a run, run status,
    recent agent events, approvals, approve or reject, checking balance, reset, and health.
  - Start it from `backend/` with the required command, `uvicorn main:app --reload --port 8000`. It starts the
    MCP server on port 8001 ([backend/mcp_supervised.py](backend/mcp_supervised.py)) and stops it on shutdown.
    It refuses to start a second one if the port is taken, and a reload leaves exactly one running.
  - Runs happen in the background, one at a time, and the dashboard polls `/events`. Only
    `POST /approvals/{id}/approve` moves money: it needs a person's name, `confirm: true` and the exact amount.
  - Approver names are recorded, not authenticated. This is a classroom simulation, not production security.
  - Approving a payment or discount doesn't fake an outcome. 102 becomes resolved once the rent is recorded.
    101 and 103 stay `in_progress`, with a note on what is still outstanding, until a person confirms the
    outside step with `POST /tickets/{id}/resolve`.
  - `tests/check_api.py` passes 92/92. It uses a temporary database copy and a scripted fake agent run, so it
    makes no model calls. The earlier suites still pass, and both databases are unchanged.
  - In `backend/agents.py`, `agent_finished` audit events now include the agent's summary, and `run_team`
    accepts a `run_id`.

- **Problem 8 (Agent dashboard): complete.** Checked against the official Panel A and B instructions on
  2026-11-03.
  - [frontend/](frontend/) is the live "Campus Customs: Agent Arcade" desk, built with React + Vite +
    TypeScript. It talks to the backend at `http://localhost:8000`, which allows the Vite address
    `http://localhost:5173`. Start it from `frontend/` with `npm run dev`.
  - What it does:
    - lists the three tickets and lets you pick one and start the agent team on it
    - shows each agent live in the Problem 6 command network: who is working, delegations as pulsing lines,
      and the MCP tool in use
    - shows a live feed of what the agents say and do, and a summary card per agent
    - compares the expected routes with the actual ones
    - has human approval gates (a name, a "reviewed" checkbox, and hold-to-confirm, or press Enter twice)
    - shows the checking balance, which drops after an approved payment, plus reset with a typed `RESET`
  - **On "mark a ticket resolved when the run finishes":** the desk shows two separate stamps.
    *Agent run complete* comes from the run's events. *Ticket resolved* appears only when the database says
    so. 102 resolves once its rent payment is recorded. 101 (invoice paid, tee not yet with the customer)
    and 103 (discount offered, not yet accepted) stay in progress until a named person confirms the outside
    step. The reasons are in [output/design.md](output/design.md).
  - [output/design.md](output/design.md) explains the design choices, as Panel B asks. Screenshots are in
    [docs/problem8_screenshots/](docs/problem8_screenshots/).
  - Tests, all with no model calls:
    - `npm test` in `frontend/`: 30/30
    - `npm run build`: TypeScript check and production build both pass
    - `tests/check_api.py`: 94/94
  - Browser testing used `tests/dev_fake_backend.py`: the real API and MCP server on a temporary copy of the
    database, with scripted agent runs labelled "SCRIPTED TEST RUN".
  - Backend changes for the desk (in `backend/main.py`):
    - `/events` now marks runs that used another database copy (`this_database`), so the Problem 5 isolated
      live test isn't shown as activity on the real database.
    - A human decision's request type is now reported as `request_kind`. Previously it overwrote the event's
      `kind`.
  - `output/desk_tickets.html` (Problem 6) is unchanged.

- **Problem 9 (Resolve the tickets): complete.** The live three-ticket run on `gpt-6-luna` took place on 2026-11-04/05 (UTC).
  Kate Duffy did every reset, run start, approval and resolution in the dashboard; the assistant only watched
  read-only and captured screenshots.
  - **Order:** reset, then 102 → 101 → 103. All three tickets ended `resolved`:
    - 102 is *operational*: the recorded rent payment completes it.
    - 101 and 103 are *administrative*: the desk's work is done, but delivery, stock and customer steps are still
      outstanding and are listed.
    - On "resolved", the assignment says "run … until each is resolved"; how operational and administrative
      resolution meet that is explained in [output/design.md](output/design.md) and
      [output/resolved_tickets.json](output/resolved_tickets.json).
  - **Cash:** $3,400.00 − $2,400.00 rent (payment 1) − $840.00 invoice 501 (payment 2) = **$160.00**, which matches
    `cash_accounts`. The 103 discount (8 × $52.20) moved no cash, and no purchase was requested.
  - **Evidence:**
    - [output/desk_tickets.html](output/desk_tickets.html): Actual sections with each run's real network, plus the
      Cash tab. Expected sections unchanged.
    - [output/resolved_tickets.json](output/resolved_tickets.json)
    - [output/resolved_board.html](output/resolved_board.html): genuine board screenshots, embedded
    - the updated `output/audit_trail.json`, and the "Verified full run (Problem 9)" section of
      [output/harness.md](output/harness.md)
    - All of it is built from the audit trail and database by `tests/build_problem9_outputs.py`, and checked
      independently by `tests/check_problem9_outputs.py` (50/50).
  - **What went wrong and was fixed**, all recorded in [docs/problem9_run_findings.md](docs/problem9_run_findings.md):
    - 101's draft reply disclosed internal invoice details. It was recorded, not re-run.
    - 103's first run filed no discount request, and Accounting used the SKU "hoodie". After a targeted prompt fix, the
      second run filed an in-policy request. Both runs are kept.
    - A dashboard label said "Fully resolved" for administrative resolutions. It now shows the resolution type.
  - Added before the run:
  - Agents can no longer mark a ticket resolved (`backend/agents.py`).
  - The four prompts flagged in review were revised; Facilities is unchanged.
  - A **simulation discount policy**, which is an assumption and not a database rule: 10+ unit orders, up to 10%
    off list, above cost, only on stock on hand. The prompts state it and `request_discount` enforces it.
  - An optional `resolution_type` (operational or administrative) on the person-confirmed resolve route.
  - Details are in the "Simulation policy and resolution rules" section of
    [output/harness.md](output/harness.md).

- **Problem 10 (Reflection): complete.** The Reflection tab of [output/desk_tickets.html](output/desk_tickets.html)
  holds Kate Duffy's reflection, word for word. The source is
  [docs/problem10_reflection.md](docs/problem10_reflection.md), and it is also logged in `AI_prompts.md`.
  - It answers all five Panel A questions:
    1. how the agents performed on each ticket
    2. Actual vs. Expected for each ticket
    3. what one agent with all the tools would have done more simply
    4. three new problems the team could solve
    5. three it couldn't, with the tools and agents needed
  - It ties each answer to tickets 101–103 and the Cash tab, as Panel B asks.
  - `tests/build_reflection.py` renders the Markdown without changing any words, and `tests/check_desk_tickets.py`
    checks it word for word.

- **Problem 11 (Submit to GitHub): ready to publish.** The repository includes both databases, every evidence file and
  the frontend. It leaves out `.env`, local environments, `node_modules`, build output, the course ZIP and local
  AI-assistant settings. `output/github_url.txt` is added once the public repository exists.

## Where the completed evidence is

| Problem | Evidence |
|---|---|
| 1 | `AI_prompts.md` (every prompt, verbatim; only identifying local paths redacted for public release) |
| 2 | `output/harness.md` (tables), `docs/problem2_database_exploration.md` |
| 3 | `mcp_server/server.py`, `mcp_server/README.md`, `output/harness.md` (MCP tools) |
| 4 | `.mcp.json`, `output/mcp_smoke.json` |
| 5 | `backend/` (agents, models, config, audit), `backend/prompts/*.md`, `docs/problem5_live_test.json` |
| 6 | `output/desk_tickets.html`: Expected sections and command network |
| 7 | `backend/main.py`, `output/harness.md` (Backend API routes) |
| 8 | `frontend/`, `output/design.md`, `docs/problem8_screenshots/` |
| 9 | `output/desk_tickets.html` (Actual sections and Cash tab), `output/resolved_tickets.json`, `output/resolved_board.html`, `output/audit_trail.json`, `output/harness.md` (Verified full run), `docs/problem9_run_findings.md`, `docs/problem9_screenshots/` |
| 10 | `output/desk_tickets.html` (Reflection tab), source text in `docs/problem10_reflection.md` |
| 11 | this repository, plus `output/github_url.txt` |

## Model

Every agent uses **only `gpt-6-luna`** through Portkey (an assignment requirement), set by `OPENAI_MODEL` in this
folder's `.env`. The backend refuses to start with any other model. Every recorded agent run requested `gpt-6-luna`.
The responses report `gpt-6-luna-global`, the provider's name for the deployment behind it.

## Prerequisites

- **Python 3.14** (the version used here).
- **Node.js 20.19 or newer** with npm (built with Node 24 and npm 11), for the React dashboard.
- A **Portkey API key**, needed only for live agent runs. The automated tests need no key and make no model calls.
- Windows, macOS or Linux. Commands are given for Windows PowerShell and for macOS/Linux shells.

## Installation

From the repository root:

**Windows (PowerShell)**

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend; npm.cmd install; cd ..
```

**macOS / Linux**

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
(cd frontend && npm install)
```

If PowerShell refuses to run `npm` ("running scripts is disabled"), use `npm.cmd` instead, as shown above.
In the rest of this README, `PY` means `.venv\Scripts\python.exe` on Windows and `.venv/bin/python` on macOS/Linux.

## Configuration

Copy `.env.example` to `.env` in the repository root and fill in your own values. Never commit `.env`; it is
ignored by git.

```bash
cp .env.example .env            # Windows: Copy-Item .env.example .env
```

| Variable | Value |
|---|---|
| `PORTKEY_API_KEY` | your Portkey key (required for live agent runs only) |
| `OPENAI_MODEL` | `gpt-6-luna` (the only model allowed) |
| `PORTKEY_PROVIDER` | `openai` |
| `MCP_SERVER_URL` | `http://127.0.0.1:8001/mcp` (default) |

`frontend/.env.example` shows the one frontend setting, `VITE_API_URL=http://localhost:8000` (the default).

## The two databases

- `data/campus_customs.db`: the **original** course database. It is never modified, and every reset copies from it.
- `data/campus_customs_new.db`: the **working copy** the application reads and writes. As committed, it holds the
  **final state of the Problem 9 run**: tickets 101, 102 and 103 resolved, **$160.00** in checking, and two
  recorded payments (rent $2,400.00 and invoice 501 $840.00).

### Starting a fresh run (this erases the completed simulation in your local copy)

To run the three tickets yourself, start from a clean working copy:

- **With the backend running:** use the dashboard's **RESET** button and type `RESET` (or `POST /reset`).
- **With everything stopped:** copy the original over the working copy:

```bash
cp data/campus_customs.db data/campus_customs_new.db      # Windows: Copy-Item data\campus_customs.db data\campus_customs_new.db -Force
```

**Resetting replaces the submitted Problem 9 state in your local working copy**: the resolved tickets, the $160
balance and the payments. The committed evidence in `output/` is not changed, and the evidence generator refuses
to overwrite it from a different run. To restore the submitted state, run
`git checkout -- data/campus_customs_new.db output/audit_trail.json`.

## Running the application

The **FastAPI backend starts and stops its own MCP server** (on `127.0.0.1:8001`). For the full application, do
**not** start the MCP server separately. If something else holds port 8001, the backend refuses to start and says
so.

1. **Backend**, from `backend/` (the assignment's command, with the virtual environment active):

   ```bash
   cd backend
   uvicorn main:app --reload --port 8000
   ```

   Without activating the environment: `..\.venv\Scripts\uvicorn.exe main:app --reload --port 8000` (Windows) or
   `../.venv/bin/uvicorn main:app --reload --port 8000` (macOS/Linux). The API serves `http://localhost:8000`, with
   interactive docs at `/docs`. Don't edit files in `backend/` during a run: `--reload` would restart the server and
   end the run.

2. **React dashboard**, from `frontend/` in a second terminal: `npm run dev` (`npm.cmd run dev` in PowerShell if
   needed). Then open **http://localhost:5173**.

3. **Stopping:** press Ctrl+C in each terminal. Stopping the backend also stops its MCP server.

### Running the MCP server on its own (testing only)

To use the MCP tools without the backend (for example from Claude Code, or to try the tools over HTTP), run
`PY mcp_server/server.py` (stdio, used by `.mcp.json`) or `PY mcp_server/server.py --http` (port 8001). **Stop it
before starting the backend.** In Claude Code, open this folder as the project root and approve the
`campus-customs` server from `.mcp.json`. That file uses the Windows path `.venv/Scripts/python.exe`; on
macOS/Linux, change it to `.venv/bin/python`.

## The three-ticket workflow

These steps make live `gpt-6-luna` calls (about 20,000–40,000 tokens per ticket run).

1. Reset the working database (see above), with the backend and dashboard running.
2. In the dashboard, type your name in **Human approval gates**. It is recorded with every decision.
3. Run the tickets in this order: **102** (rent) → **101** (tee) → **103** (hoodies). Select a ticket, press
   **START MISSION**, and watch the command network and the live feed. Only one run can be active at a time.
4. **Approve or reject** each request at its gate. Tick "I reviewed…", then hold the button for one second (or press
   Enter twice). Agents can only *request* payments, purchases and discounts. The approve route is the only thing
   that moves money, and it refuses agent names, wrong amounts, duplicates, blocked vendors and overdrafts.
5. **Resolution:**
   - A recorded rent payment resolves 102 automatically (*operational*).
   - For 101 and 103, a person uses **Record the resolution**: choose *operational* (the outside outcome really
     happened) or *administrative* (the desk's work is done, with outside steps still outstanding), write a note,
     and confirm it is accurate.
   - Agents can never mark a ticket resolved.
6. The **Cash** figures come from the database: $3,400.00 at the start, less each approved payment.

## Automated tests (no model calls, no Portkey key needed)

All of these use temporary database copies and never write to the evidence or the committed databases. Run them
from the repository root with `PY tests/<name>.py`:

| Test | What it checks |
|---|---|
| `check_mcp_tools.py` | The Problem 3 tools, on a copy of the original database |
| `check_problem5_tools.py` | The approval-queue tools and money safeguards |
| `check_agent_team.py` | Tool allowlists, identity stamping, delegation limits, no agent resolving, audit trail |
| `check_api.py` | Every API route, with a scripted fake agent run and a placeholder key |
| `check_desk_tickets.py` | `desk_tickets.html`: Expected wording, Actual sections, Cash, Reflection word for word |
| `check_problem9_outputs.py` | The Problem 9 evidence recomputed from the database and audit trail |
| `check_evidence_guards.py` | That the evidence scripts refuse to overwrite the verified results |
| `verify_mcp_smoke.py --original` | The Problem 4 smoke outputs against the original database |

Frontend, from `frontend/`: `npm test` (Vitest) and `npm run build` (TypeScript check and production build).
For a scripted browser demo with no model calls, run `PY tests/dev_fake_backend.py` instead of the backend. It uses a
temporary database copy.

## Scripts that write evidence or spend tokens

| Script | Effect | Safe? |
|---|---|---|
| All `check_*.py` tests and `verify_mcp_smoke.py --original` | Read-only on the project | Yes |
| `tests/build_problem9_outputs.py` | Rebuilds the Problem 9 evidence from the audit trail and database. An unchanged rebuild is byte-identical | Yes. It refuses to write if the reset, runs, payments or balance differ from the recorded simulation (`--force` overrides) |
| `tests/build_reflection.py` | Rebuilds the Reflection tab from `docs/problem10_reflection.md` | Yes |
| `tests/verify_mcp_smoke.py --record` | Rewrites `output/mcp_smoke.json` | Refuses while the databases differ (as committed) |
| `tests/live_agent_test.py 102 --live` | **Spends Portkey tokens**; rewrites `docs/problem5_live_test.json`; appends to the audit trail | Needs `--live`, and also `--overwrite-record` because the record exists |
| Dashboard START MISSION / backend `POST /tickets/{id}/run` | **Spends Portkey tokens**; appends to `output/audit_trail.json` | Live use only |
| Dashboard RESET / `POST /reset` | Replaces the local working database with the original | See "Starting a fresh run" |

## Prompt log

`AI_prompts.md` records the prompts submitted to the AI coding assistant, problem by problem, verbatim. Before
public release, only identifying local paths were replaced with placeholders, as noted at the top of the file.
