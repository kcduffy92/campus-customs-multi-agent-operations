// Typed calls to the Problem 7 FastAPI backend. The frontend never changes cash or records itself:
// every change goes through these routes, and only /approvals/{id}/approve can move money.
import type { ApprovalRequest, Cash, EventsResponse, Health, ResolutionType, RunInfo, Ticket } from "./types";

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailText(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d))).join("; ");
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_URL + path, { ...init, headers: { "Content-Type": "application/json" } });
  } catch {
    throw new ApiError(
      0,
      `Can't reach the backend at ${API_URL}. Start it from backend/ with: uvicorn main:app --reload --port 8000`,
    );
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailText(body) ?? `${res.status} ${res.statusText}`);
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export interface DecisionResult {
  approved?: boolean;
  rejected?: boolean;
  request: ApprovalRequest;
  result?: Record<string, unknown>;
  ticket?: Ticket;
}

export const api = {
  health: () => request<Health>("/health"),
  tickets: () => request<{ tickets: Ticket[] }>("/tickets").then((r) => r.tickets),
  startRun: (ticketId: number) =>
    post<{ run_id: string; ticket_id: number; status: string }>(`/tickets/${ticketId}/run`),
  run: (runId: string) => request<RunInfo>(`/runs/${runId}`),
  events: (params: { since?: number; limit?: number }) => {
    const q = new URLSearchParams();
    if (params.since !== undefined) q.set("since", String(params.since));
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    return request<EventsResponse>(`/events?${q.toString()}`);
  },
  approvals: (status: "pending" | "executed" | "rejected" | "all" = "all") =>
    request<{ requests: ApprovalRequest[] }>(`/approvals?status=${status}`).then((r) => r.requests),
  approve: (id: number, approvedBy: string, expectedAmount: number, note = "") =>
    post<DecisionResult>(`/approvals/${id}/approve`, {
      approved_by: approvedBy,
      expected_amount: expectedAmount,
      confirm: true,
      note,
    }),
  reject: (id: number, decidedBy: string, note = "") =>
    post<DecisionResult>(`/approvals/${id}/reject`, { decided_by: decidedBy, confirm: true, note }),
  resolve: (ticketId: number, resolvedBy: string, confirmation: string, resolutionType: ResolutionType) =>
    post<{ resolved: boolean; resolution_type: ResolutionType | null; ticket: Ticket }>(`/tickets/${ticketId}/resolve`, {
      resolved_by: resolvedBy,
      confirmation,
      confirm: true,
      resolution_type: resolutionType,
    }),
  cash: () => request<Cash>("/cash"),
  reset: (resetBy?: string) =>
    post<{ reset: boolean; epoch: number; next_cursor: number }>("/reset", {
      confirm: "RESET",
      reset_by: resetBy || null,
    }),
};
