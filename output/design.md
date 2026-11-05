# Campus Customs: Agent Arcade — dashboard design (Problem 8)

The live desk is in `frontend/` (React + Vite + TypeScript). Start the backend from `backend/` with
`uvicorn main:app --reload --port 8000`, then start the desk from `frontend/` with `npm run dev` and open
`http://localhost:5173`.

## The idea: a retro arcade where the agents are the players

A multi-agent system is hard to picture. Five pieces of software pass work to each other, call tools, and
stop to ask a person for money. A plain table of log lines hides all of that. So the desk treats the shop as an
arcade cabinet:

- **The tickets are levels:** "Operation Missing Tee", "Operation Keep the Lights On" and "Operation Hoodie
  Negotiation".
- **The agents are a team of classic game characters:** each has its own colour and sprite, so you can tell
  at a glance who is working.
- **The checking account is the treasure vault,** and every payment is a locked gate that only a person can
  open.

The look is the same as the Problem 6 page (`output/desk_tickets.html`). It has a near-black background with
neon-pink accents and pixel-art headings drawn in code. Everything uses the same hand-made sprites and
synthesized sounds, with no images, fonts or audio downloaded. The arcade styling is there to make the system
easier to understand, so it never hides a number or a decision.

## Layout

The desk has three columns on a laptop, and one column on a phone.

| Area | What it shows | Why it is there |
|---|---|---|
| **Header** | Pixel title, backend light (online/offline, model `gpt-6-luna`), vault balance, sound toggle, reset | The essentials are visible from anywhere on the page |
| **Left: Mission select** | The three tickets as level cards, with database status and stage | "What needs doing?" |
| **Left: Run panel** | START MISSION, the *Agent run* stamp, the *Ticket* stamp, what is still outstanding, expected vs. actual routes | "What happened, and is it really finished?" |
| **Centre: Command network** | Mario on top, the four specialists below, delegation lines | "Who is working, and who asked whom?" |
| **Centre: Live agent feed** | One line per real event, newest first, with the character's sprite | "What are they saying and doing right now?" |
| **Right: Treasure vault** | Balance, money committed to pending requests, what is left, approved and rejected transactions | "Can we afford this?" |
| **Right: Approval gates** | One locked gate per pending request | "What is waiting for me?" |
| **Bottom: What each agent did** | One card per agent: its summary, the MCP tools it used, any draft customer reply and open issues | The short summary of each agent's work that the assignment asks for |

On a phone the columns stack in working order: missions, run panel, network, approval gates, vault, feed,
summaries. The network map scrolls sideways inside its own box and starts centred on Mario.

## Why each agent is a different character

Each agent has one colour, one sprite and one sound wherever it appears: on the network, in the feed, on
the summary cards and on the approval gates ("Asked by Spyro (Accounting)"). Because the character is the
same everywhere, you learn the cast once and can then read a run like a story.

| Character | Agent | Colour | What the character suggests |
|---|---|---|---|
| Mario | Boss | Red | The team leader who sends others on missions |
| Crash Bandicoot | Inventory | Orange | Crates and warehouse shelves: stock and suppliers |
| Spyro | Accounting | Purple | The dragon guarding the treasure: cash, invoices, discounts |
| Ryu | Facilities | White (silver lines) | The disciplined fighter who checks the lease before anyone pays |
| Sonic | Customer Service | Blue | Speed and communication: the reply to the customer |

The sprites and sounds are original pixel art and synthesized placeholders, not material copied from the
games.

## How agent activity and delegation are shown

Every animation comes from a real event in the backend's audit trail, which the desk polls once a second
during a run. With no events, nothing moves.

- **An agent starts working:** its tile glows and gets a "WORKING" tag. A "▶" marks the agent working most
  recently.
- **A delegation starts:** the line from the delegating agent to the receiving one turns bright white and a
  pulse travels along it in the direction of the hand-off. Specialist-to-specialist hand-offs (Ryu → Spyro)
  animate directly, not through Mario.
- **A delegation finishes:** the line turns solid in the receiver's colour. A refused or failed delegation
  flashes red.
- **A tool is used:** a cyan chip shows the MCP tool name above the agent, such as `check_rent_due`.
- **A request is filed:** a gold lock appears on the agent until a person decides.
- **The run ends:** agents who never took part dim and read "SITTING OUT".

**Expected vs. actual.** The Problem 6 plan stays on the map as dashed pink lines, with gold dotted lines for
"only if needed". When the run ends, the run panel lists every route as one of:
- ✓ as planned
- ✕ planned but not used
- ! not in the plan

The map labels unexpected and unused routes too. A run that strays from the plan is easy to spot, which is the
point of comparing the two.

## "Agent run complete" is not the same as "Ticket resolved"

The assignment's wording says a ticket should be marked resolved when the run finishes. We deliberately show
two separate stamps instead:

- **AGENT RUN:** NOT STARTED → AGENTS WORKING → **AGENT RUN COMPLETE** (or RUN FAILED). This comes from the run's
  events and means the agents finished their investigation and actions. The stamp says plainly that this alone
  does not mean money moved or anyone received anything.
- **TICKET (database):** the real status in the database: OPEN, AWAITING APPROVAL, IN PROGRESS, or
  **TICKET RESOLVED** in gold. The desk never shows "resolved" because a run ended; it shows it only when
  the database says so.

The reason is that at the end of a run the real work is often still pending:
- **Ticket 102 (rent):** the job is done once a person approves the rent and the payment is recorded. The
  backend then marks it resolved, and the gold stamp appears.
- **Ticket 101 (tee):** paying invoice 501 does not put a shirt in the customer's hands. The ticket stays
  IN PROGRESS, with "the reprint still has to arrive and reach the customer" listed under *Still outstanding*.
- **Ticket 103 (hoodies):** an approved discount is only an offer. The ticket stays IN PROGRESS until the club
  accepts and stock is available.

For 101 and 103, a person closes the ticket in **Record the resolution**:
- They choose a **type of resolution**:
  - **Operational:** the real-world outcome has happened, and they know it has.
  - **Administrative:** the desk's work is done and the ticket is closed, but outside steps are still
    outstanding.
- They write a resolution note covering what the desk completed, what they approved, and what is still
  outstanding.
- They tick "I confirm this resolution note accurately describes what has and has not happened", then hold the
  button.

That calls the backend's resolve route with their name and the resolution type, and both are recorded in the
ticket note and the audit trail. Agents cannot resolve tickets: the system refuses it even if one tries.

## How human approvals work

Agents can only *ask* for a payment, purchase or discount. Each request appears as a locked arcade gate
showing:
- the exact amount, and whether it moves cash ("Moves no cash" for a discount)
- what it is for and which ticket it belongs to
- which agent asked

To open a gate, the person:
1. types their name (it is recorded with the decision);
2. ticks "I reviewed the amount, purpose and ticket";
3. **holds** APPROVE or REJECT for about a second, while a bar fills. Keyboard and screen-reader users press
   Enter twice instead ("Press again to confirm").

While the backend works, the buttons show PROCESSING… and can't be pressed again, so a double-click cannot pay
twice. The backend also refuses a second approval. The result shown is the backend's own answer: success, or
the exact refusal, such as "Not enough cash in checking" or "Vendor still has an open invoice". Warnings for
insufficient funds and blocked vendors appear on the gate before anyone approves. Gates are locked while an
agent run is active.

The desk never changes cash or records itself. Every change goes through the backend's approve, reject,
resolve and reset routes. Approver names are recorded, not authenticated: this is a classroom simulation, not
production security.

## How cash and payments appear

The vault shows four things:
- the checking balance
- money committed to pending requests
- what would be left if all of them were approved (red "OVERCOMMITTED" if negative)
- the list of approved transactions, each with the approver's name and payment number

Rejected requests are listed separately in red with a strike-through, and pending ones are pink, so the
three states never blur together.

When a payment goes through, the old balance stays visible, struck through, above the new one, with the
difference in a red chip (for example, $3,400.00 → **$1,000.00**, −$2,400.00). We deliberately don't "count
down" through in-between amounts, because those would be numbers that never existed. Both figures come from
the backend.

## Sound

Sound is off until you press SOUND, and it never needs a download. When it is on, short synthesized cues play
for real events only:
- Mario's coin when he delegates
- Ryu's "hadouken" when Facilities starts work
- Crash's crate when Inventory checks stock, and his "woah" when he reports a shortage
- Spyro's warning chime when a request reaches the gate, and his treasure chime when a payment is approved
- Sonic's ring when a customer reply is drafted
- a fanfare only when a ticket is actually resolved

A finished run gets no victory sound, because a finished run is not a resolution.

## Why this helps

Someone watching the desk for a minute can answer the questions a manager cares about:
- Who did the work?
- Did they follow the plan?
- What did each of them conclude?
- What is waiting for me?
- What will it cost?
- Is the ticket really done?

The game styling is a memory aid. Familiar characters stand for each agent's job, lines show the hand-offs,
gates mark where a person has to decide, and the vault tracks the money. The rules about what counts as done
stay strict.

## Testing

None of the testing spent Portkey tokens:
- **`tests/dev_fake_backend.py`** runs the real API and MCP server on a temporary copy of the database, with
  scripted agent runs that make real tool calls and write real-format events, all labelled "SCRIPTED TEST
  RUN".
- **Vitest (`npm test`):** 30 tests covering event handling, the expected-vs-actual comparison, approval gates
  (locks, hold, the keyboard alternative, duplicate-click protection), cash display, the two stamps, reset
  confirmation and sound triggers.
- **Browser screenshots** are in `docs/problem8_screenshots/`.
