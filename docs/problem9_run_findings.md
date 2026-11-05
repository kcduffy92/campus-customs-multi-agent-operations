# Problem 9 — live run findings

Observations from the real three-ticket simulation, recorded while it ran. Every item quotes the audit trail
(`output/audit_trail.json`) or a read-only database query. These notes feed the final evidence
(`desk_tickets.html` Actual sections, `resolved_tickets.json`, `harness.md`).

## Reset
- Kate Duffy reset the working database from the dashboard at 2026-11-04 23:58:09 UTC (audit entry 40,
  `database_reset`, epoch 1). Afterwards the working database matched the original byte for byte, with checking at $3,400.00.

## Ticket 102 — rent notice
- **Run** (audit entries 41–80): Mario → Ryu → Spyro, as planned. 10 requests, 10 tool calls, 22,772 tokens. No
  refusals or errors.
- **Request #1:** rent payment of $2,400.00 for lease 1 (Elm City Properties, due 2026-09-02), filed by Accounting.
  It matched the lease.
- **Approval:** Kate Duffy approved it in the dashboard at 2026-11-05 00:02:39 UTC. Payment 1 was $2,400.00 from
  checking, which went from $3,400.00 to $1,000.00. The lease's next due date moved to 2026-10-02.
- **Resolution:** the backend's rent rule set the ticket to resolved, with `resolution_type: operational`.
- No issues found.

## Ticket 101 — customer tee order
- **Run** (audit entries 83–137): Mario → Crash → Spyro, then Mario → Sonic, as planned. 14 requests, 14 tool
  calls, 36,167 tokens. No refusals or errors.
- **Request #2:** invoice payment of $840.00 for invoice 501 ("Rush reprint CC-TEE-WHITE S", open, 3 days
  overdue), filed by Accounting. No duplicate tee purchase was requested; Inventory and Accounting both said
  the invoice already covers the reprint.
- Every agent said that paying the invoice doesn't confirm shipment and that the 5-day lead time is an estimate.
- **Issue: Sonic's draft reply reveals internal details.** The draft, which was never sent, says "invoice 501 is open
  and overdue, and a payment request is awaiting human approval. The printer is blocked from shipping until
  the invoice is addressed." Sonic's prompt forbids revealing vendor invoices, unpaid vendors or internal
  approvals to a customer. Otherwise the draft is accurate: no size S tee is in stock, the price is $28, and nothing is
  confirmed.
- **Decision (Kate Duffy):** approve the $840 invoice anyway, record the issue, and don't re-run the ticket. The
  draft must be edited before it is sent, and this is listed as outstanding in the ticket's resolution note.
- **Approval:** Kate Duffy approved request #2 in the dashboard at 2026-11-05 00:08:05 UTC (audit entry 138). Payment 2
  was $840.00 to invoice 501, from checking, which went from $1,000.00 to $160.00. Invoice 501 is now `paid`.
- **Ticket status:** the backend set ticket 101 to `in_progress`, not resolved (audit entry 139), with the stage
  "Approved; awaiting supplier or customer". Its note says: "The supplier invoice is paid; the reprint still has
  to arrive and reach the customer."
- **Resolution:** Kate Duffy resolved ticket 101 in the dashboard with `resolution_type: administrative` (audit
  entry 140). Her note: "Inventory confirmed that the size S tee is out of stock. The $840 rush reprint invoice
  was paid with human approval, and no duplicate purchase was made. Customer Service drafted a response, but
  it was not sent because it included confidential internal payment information and needs revision. The
  reprint has not been confirmed as shipped or delivered. Outstanding steps include confirming shipment with
  the supplier, getting the tee to the customer, and sending an approved, corrected response."
- **Dashboard wording issue:** after this resolution, the 101 card showed the stage label "Fully resolved". The
  backend uses that label for every resolved ticket, so it overstates an administrative resolution.
  Raised with Kate Duffy before ticket 103.
- **Fix (approved by Kate Duffy, made while no run was active):** the backend now takes the label from the
  recorded `resolution_type`. It reads "Resolved (administrative): outside steps outstanding" (101, which keeps
  its outstanding step visible) or "Resolved (operational)" (102). The dashboard's "RESOLVED" stamp was moved so
  it no longer overlaps the label. No data changed: checking stayed at $160.00, with 2 payments. API tests pass
  99/99 and frontend tests 31/31. The 101 and 102 screenshots were re-captured after the fix.

## Ticket 103 — bulk hoodie discount
- **Run** (audit entries 141–187): Mario → Crash, Mario → Spyro, Mario → Sonic, the planned routes. 12 requests,
  10 tool calls, 31,388 tokens. No refusals or errors.
- **Inventory (correct):** 8 of 20 CC-HOOD-NAVY size M on hand (Aisle A), 12 short. List price $58.00, unit cost
  $22.00. No vendor is blocked now. Crash said Bulldog Print Co's supply of this hoodie is *unconfirmed* and
  that the database records no vendor-to-SKU mapping.
- **Accounting (no request filed, which differs from the plan):** Spyro applied the simulation policy: the
  20-unit order qualifies, only 8 can be discounted, the lowest price is $52.20 (10% off), and the margin is
  $30.20 a unit. But it filed **no discount request**, because "no proposed discounted price was given, so I
  did not invent one". Mario's delegation told it to "state the lowest acceptable price and whether any approval
  request can/should be filed without a proposed price; do not invent a price". The Expected plan for 103
  listed `request_discount`, which was not used.
- **Accounting lookup error:** Spyro called `check_stock_and_pricing` with `sku: "hoodie"` instead of
  `CC-HOOD-NAVY`. The tool returned not-found, and Spyro said so in its report. Its figures (8 on hand, $22,
  $58) came from Mario's task and match the database, but Spyro didn't confirm them itself.
- **Customer Service (no problems):** the draft, which was not sent, says 8 are in stock, 12 are short, supply
  and the group price aren't confirmed, and nothing is approved. It offers to discuss a partial order. It
  reveals no internal finances; it does mention the internal SKU code.
- **Ticket status:** Mario set ticket 103 to `in_progress` (not resolved), noting that a proposed price and
  supply for the 12-unit shortfall are still outstanding.
- **Money:** no request was filed for 103, so nothing waits at the approval gate. Checking is still $160.00 with
  2 payments. No restock purchase was requested: 12 × $22.00 = $264.00 would be more than the $160.00 left.
- Screenshot: `docs/problem9_screenshots/05_ticket103_run_complete_no_request.jpg`.

### Diagnosis: two problems in the first 103 run
1. **Coordination problem, so the discount request was missing.** Mario's delegation framed pricing as
   something that needs a customer-proposed price, and Spyro followed that framing and filed nothing. Neither
   prompt said who sets the price, so the agents treated "no customer price" as a blocker. In a real shop,
   Accounting proposes the price within policy and a person approves it.
2. **Wrong SKU in a tool call.** Spyro called `check_stock_and_pricing` with `sku: "hoodie"` instead of the exact
   `CC-HOOD-NAVY` from the ticket and from Inventory's results. It got not-found, and its figures went
   unconfirmed by its own lookup.

### Fix (approved by Kate Duffy)
These targeted prompt changes were made with no run active. Facilities, Inventory and Customer Service are
unchanged, and so is the code.
- **`backend/prompts/boss.md`** (`price_override` routing): "The customer does not need to propose a price.
  Accounting proposes one within the simulation discount policy and prepares the approval request." Mario asks
  Accounting for a pricing recommendation and an approval request, not whether a request can be filed without
  a customer price, and passes on the exact SKU and size.
- **`backend/prompts/accounting.md`**, two new sections:
  - *Proposing a discount:* Accounting chooses a price within the policy from verified list price, unit cost
    and quantity on hand, explains the choice, and files `request_discount`. A missing customer price is never
    a reason to skip the request. For ticket 103 the limit is 10% off, which is $52.20 a unit, on the 8 units on
    hand only. It may choose that price or a smaller discount, but must say why.
  - *Exact identifiers:* use the exact SKU and size from the ticket or Inventory's results, never a description
    such as "hoodie". If a tool says a SKU wasn't found, recheck the exact identifier. If it is genuinely
    unknown, ask for clarification instead of inventing one.

### Why we re-run ticket 103
To test whether a targeted change to the coordination instructions fixes the behaviour: does Accounting now
propose an in-policy price, file a human approval request, and use the exact SKU? The first run stays in the
record unchanged (audit entries 141–187, plus the screenshot above). Tickets 101 and 102 are not re-run and
the database is not reset.

### Pre-rerun checks
- **Deterministic tests, no model calls:** `check_agent_team` 34/34, `check_problem5_tools` 50/50,
  `check_api` 99/99.
- **`check_mcp_tools.py` (20/26):** it checks the live working database against the *original* Problem 3
  values and requires the working and original databases to be identical. The six failures are this
  simulation's intended changes (invoice 501 paid, rent paid, $160 left), not the prompt change. It passes
  again after a reset.
- **Live state (read-only):**
  - checking is $160.00, with payments 1 (rent $2,400) and 2 (invoice $840), both approved by Kate Duffy
  - tickets 101 and 102 are `resolved`, and 103 is `in_progress`
  - ticket 103 has no discount or purchase request
  - the audit trail is intact at 188 entries (SHA-256 `dd8288accf1206cc`)
  - the original database is unchanged
- **Backend restart:** agents load their prompt files once and then cache them, so the backend was restarted
  while idle. The `--reload` was triggered by updating `backend/agents.py`'s timestamp; its contents didn't
  change. It came back healthy with a new MCP server, and the next run builds its agents from the updated
  prompts.

### Second ticket 103 run (after the fix)
- **Run** (audit entries 188–237; the first run's entries 141–187 are unchanged): Mario → Crash, Mario → Spyro,
  Mario → Sonic, the planned routes. 13 requests, 11 tool calls, 38,345 tokens. No refusals or errors.
- **Did the fix work? Yes.** Spyro proposed a price within policy and filed **request #3**:
  - discount on **8 × CC-HOOD-NAVY size M at $52.20** (10% off the $58.00 list price), total $417.60
  - margin $30.20 a unit over the $22.00 cost, cash effect $0.00
  - the request records an order size of 20 and a shortfall of 12, and its reason says the remaining 12 are
    not included
  - Spyro passed the exact SKU and size to `request_discount`. It made no lookup with a made-up SKU this time,
    and the tool checked the 8 on hand against the database.
  - No purchase was requested.
- **New, smaller problems:**
  - Mario told Crash that "the ticket note already records 8 of 20 … Please do not repeat those checks". That
    leans on a note written by the *previous* run, where the rule is facts from tools in this run.
  - Crash still ran `check_stock_and_pricing`, which confirmed 8 on hand, but passed `requested_quantity: 12`
    instead of 20. The tool therefore reported a shortage of 4. Crash noticed and explained the mismatch,
    and kept the correct 12-unit shortfall for the 20-unit order.
  - The final figures are correct and match the database.
- **Customer Service:** the draft, which was not sent, says 8 are on hand, 12 are short with supply
  unconfirmed, and the discount is still awaiting approval. It doesn't quote the price as approved, and it
  reveals no internal finances (it mentions the SKU code).
- **Approval:** Kate Duffy approved request #3 in the dashboard at 2026-11-05 00:24:07 UTC (audit entry 238),
  41 seconds after it was filed. Our read-only check came afterwards and confirmed the request was within
  policy. A discount moves no cash, so checking stayed at $160.00 with 2 payments.
- **Ticket status:** the backend set ticket 103 to `in_progress`, not resolved (audit entry 239): "The discount
  is approved as an offer; the customer has not accepted it and the stock shortage is not solved."
- **Resolution:** Kate Duffy resolved ticket 103 with `resolution_type: administrative` (audit entry 240). Her
  note covers the 8 of 20 on hand and 12 short, the discount on 8 at $52.20 ($417.60) approved as an offer with
  no cash moved, and the reply drafted but not sent. It lists the outstanding steps (club acceptance,
  supply for the remaining 12, sending the reply) and records that a first run filed no request and the ticket
  was re-run after a prompt fix.

## End state (verified read-only)
- **Tickets:** 101 resolved (administrative), 102 resolved (operational), 103 resolved (administrative).
- **Checking:** $3,400.00 at the start, minus $2,400.00 rent (payment 1), minus $840.00 invoice 501
  (payment 2), leaves **$160.00**, which matches `cash_accounts`. The discount (#3) moved no cash, and no
  purchase was requested.
- **Approval requests:** #1 rent, #2 invoice and #3 discount, all `executed` and decided by Kate Duffy.
- **Audit trail:** 241 entries in all, 40 before the reset and entries 40–240 from this simulation.
- **Screenshots:** `docs/problem9_screenshots/00`–`08`.
