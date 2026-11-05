// Event shapes as GET /events returns them (see backend/main.py simplify() and tests/check_api.py).
import type { ApprovalRequest, ArcadeEvent, Cash, Ticket } from "../types";

let i = 0;
const ev = (e: Partial<ArcadeEvent> & { kind: string }): ArcadeEvent => ({
  index: i++, epoch: 0, time: "2026-11-03T19:46:22+00:00", run_id: "run-102", ticket_id: 102, action: e.kind,
  agent: null, character: null, ...e,
});

/** A ticket 102 run shaped like the Problem 5 live test: Boss -> Facilities -> Accounting. */
export function rentRun(opts: { finished?: boolean; runId?: string; epoch?: number } = {}): ArcadeEvent[] {
  i = 0;
  const run_id = opts.runId ?? "run-102", epoch = opts.epoch ?? 0;
  const list: ArcadeEvent[] = [
    ev({ kind: "run_started", agent: "boss", character: "mario", model: "gpt-6-luna", this_database: true, run_label: null }),
    ev({ kind: "agent_active", agent: "boss", character: "mario" }),
    ev({ kind: "tool_used", agent: "boss", character: "mario", tool: "get_ticket" }),
    ev({ kind: "delegation_started", agent: "boss", character: "mario", to_agent: "facilities", to_character: "ryu" }),
    ev({ kind: "agent_active", agent: "facilities", character: "ryu" }),
    ev({ kind: "tool_used", agent: "facilities", character: "ryu", tool: "check_rent_due" }),
    ev({ kind: "delegation_started", agent: "facilities", character: "ryu", to_agent: "accounting", to_character: "spyro" }),
    ev({ kind: "agent_active", agent: "accounting", character: "spyro" }),
    ev({ kind: "tool_used", agent: "accounting", character: "spyro", tool: "get_cash_balance" }),
    ev({ kind: "approval_requested", agent: "accounting", character: "spyro", tool: "request_rent_payment",
      approval: { created: true, duplicate: false, request_id: 1 } }),
    ev({ kind: "agent_finished", agent: "accounting", character: "spyro", said: "Queued $2,400 rent for approval." }),
    ev({ kind: "delegation_finished", agent: "facilities", character: "ryu", to_agent: "accounting", to_character: "spyro" }),
    ev({ kind: "agent_finished", agent: "facilities", character: "ryu", said: "Notice matches lease 1." }),
    ev({ kind: "delegation_finished", agent: "boss", character: "mario", to_agent: "facilities", to_character: "ryu" }),
  ];
  if (opts.finished !== false) {
    list.push(
      ev({ kind: "agent_finished", agent: "boss", character: "mario", said: "Rent request filed; waiting for a person." }),
      ev({ kind: "run_finished", agent: "boss", character: "mario", status: "completed", usage: { requests: 10, tool_calls: 10, total_tokens: 20937 } }),
    );
  }
  return list.map((e) => ({ ...e, run_id, epoch }));
}

export const ticket = (over: Partial<Ticket> = {}): Ticket => ({
  id: 102, type: "rent_notice", requester: "Elm City Properties", subject: "Rent due", status: "awaiting_approval",
  created_at: "2026-08-31T11:05:00-04:00", open_or_resolved: "open", is_resolved: false, stage: "awaiting_approval",
  stage_label: "Awaiting human approval", waiting_on: [], pending_requests: 1, executed_requests: 0, rejected_requests: 0,
  ...over,
});

export const rentRequest = (over: Partial<ApprovalRequest> = {}): ApprovalRequest => ({
  id: 1, ticket_id: 102, kind: "rent_payment", ref_id: 1, sku: null, size: null, quantity: null, unit_price: null,
  amount: 2400, cash_effect: -2400, account: "checking",
  details: { landlord: "Elm City Properties", due_date: "2026-09-02", space_name: "Chapel Street shop" },
  reason: "Rent due 2026-09-02 per lease 1", requested_by: "accounting", requested_at: "2026-11-03T19:46:50+00:00",
  status: "pending", decided_by: null, decided_at: null, decision_note: null, payment_id: null, result: null, ...over,
});

export const cash = (over: Partial<Cash> = {}): Cash => ({
  account: "checking", balance: 3400, as_of: "2026-08-31", today: "2026-08-31", pending_outflow: 2400,
  available_after_pending: 1000, ...over,
});
