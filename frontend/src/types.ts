// Shapes returned by the Problem 7 backend (backend/main.py).

export type ApiAgent = "boss" | "inventory" | "accounting" | "facilities" | "customer_service";
export type CharacterId = "mario" | "crash" | "spyro" | "ryu" | "sonic";

export type TicketStatus = "open" | "in_progress" | "awaiting_approval" | "resolved";
export type Stage =
  | "not_started"
  | "agents_working"
  | "investigated"
  | "awaiting_approval"
  | "approved_awaiting_external"
  | "needs_follow_up"
  | "resolved";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  status: TicketStatus;
  created_at: string;
  notes?: string | null;
  open_or_resolved: "open" | "resolved";
  is_resolved: boolean;
  stage: Stage;
  stage_label: string;
  waiting_on: string[];
  pending_requests: number;
  executed_requests: number;
  rejected_requests: number;
  resolution_type?: ResolutionType | null;
}

export type ResolutionType = "operational" | "administrative";

export type RequestKind = "invoice_payment" | "rent_payment" | "purchase" | "discount";

export interface ApprovalRequest {
  id: number;
  ticket_id: number;
  kind: RequestKind;
  ref_id: number | null;
  sku: string | null;
  size: string | null;
  quantity: number | null;
  unit_price: number | null;
  amount: number;
  cash_effect: number;
  account: string | null;
  details: Record<string, unknown> | null;
  reason: string;
  requested_by: string;
  requested_at: string;
  status: "pending" | "executed" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  payment_id: number | null;
  result: Record<string, unknown> | null;
}

export interface Cash {
  account: string;
  balance: number;
  as_of: string;
  today: string;
  pending_outflow: number;
  available_after_pending: number;
}

export interface Health {
  status: string;
  model: string;
  mcp_server: string;
  mcp_tools: number;
  database: string;
  portkey_key_configured: boolean;
  active_run: string | null;
  transaction_active: boolean;
  epoch: number;
  authentication: string;
}

export interface ArcadeEvent {
  index: number;
  epoch: number;
  time: string | null;
  run_id: string | null;
  ticket_id: number | null;
  action: string;
  kind: string;
  agent: ApiAgent | null;
  character: CharacterId | null;
  parent_agent?: ApiAgent | null;
  parent_character?: CharacterId | null;
  depth?: number | null;
  to_agent?: ApiAgent | null;
  to_character?: CharacterId | null;
  tool?: string | null;
  args?: Record<string, unknown> | null;
  said?: string | null;
  customer_reply?: string | null;
  open_issues?: string[] | null;
  recommended_ticket_status?: string | null;
  approval_request_ids?: number[] | null;
  approval?: { created: boolean | null; duplicate: boolean; request_id: number | null };
  status?: string | null;
  error?: string | null;
  reason?: unknown;
  run_label?: string | null;
  this_database?: boolean;
  model?: string | null;
  usage?: Record<string, number> | null;
  // Human decisions and ticket updates written by the backend
  decision?: string;
  request_id?: number;
  request_kind?: RequestKind;
  amount?: number;
  decided_by?: string;
  message?: string;
  note?: string;
  updated_by?: string;
  previous_status?: string;
  reset_by?: string | null;
  resolution_type?: ResolutionType | null;
}

export interface EventsResponse {
  events: ArcadeEvent[];
  next_cursor: number;
  epoch: number;
  active_run: string | null;
}

export interface RunInfo {
  run_id: string;
  ticket_id: number;
  status: string;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  result: { final_report?: { summary?: string } | null; usage?: Record<string, number> } | null;
}
