// Turns real backend events into what the command network shows. Pure functions, no side effects:
// with no events there is no activity, and nothing here ever invents a step.
import { ORDER, charOf } from "./characters";
import type { ExpectedRoute } from "./expected";
import type { ArcadeEvent, CharacterId } from "./types";

export type NodeState = "idle" | "working" | "done" | "stopped" | "out";
export type EdgeLive = "active" | "completed" | "failed";
export type RunStatus = "none" | "running" | "completed" | "error" | "stopped_usage_limit" | "refused" | "cancelled";
export type RouteCompare = "matched" | "missed" | "unexpected" | "pending";

export interface NodeView {
  state: NodeState;
  tool: string | null; // the tool in use right now (cleared when the agent finishes)
  tools: string[]; // every MCP tool this agent used in the run, in order
  said: string | null;
  customerReply: string | null;
  openIssues: string[];
  approvalsFiled: number[]; // approval request ids this agent filed (or found) in the run
}

export interface RunView {
  runId: string | null;
  ticketId: number;
  status: RunStatus;
  label: string | null;
  error: string | null;
  usage: Record<string, number> | null;
  startedAt: string | null;
  finishedAt: string | null;
  nodes: Record<CharacterId, NodeView>;
  edges: Record<string, EdgeLive>; // "from>to" by character
  edgeOrder: string[]; // delegations in the order they started
  current: CharacterId | null; // the agent working most recently, if the run is active
}

export const edgeKey = (from: CharacterId, to: CharacterId) => `${from}>${to}`;

const emptyNode = (): NodeView => ({
  state: "idle", tool: null, tools: [], said: null, customerReply: null, openIssues: [], approvalsFiled: [],
});

export function emptyRun(ticketId: number): RunView {
  return {
    runId: null, ticketId, status: "none", label: null, error: null, usage: null, startedAt: null, finishedAt: null,
    nodes: Object.fromEntries(ORDER.map((c) => [c, emptyNode()])) as Record<CharacterId, NodeView>,
    edges: {}, edgeOrder: [], current: null,
  };
}

/** The current epoch's latest run of this ticket on this database, or null. */
export function latestRunId(events: ArcadeEvent[], ticketId: number, epoch: number): string | null {
  let id: string | null = null;
  for (const ev of events) {
    if (ev.kind === "run_started" && ev.ticket_id === ticketId && ev.epoch === epoch && ev.this_database !== false) {
      id = ev.run_id;
    }
  }
  return id;
}

/** Fold one run's events into node and connection states. */
export function buildRunView(events: ArcadeEvent[], ticketId: number, runId: string | null): RunView {
  const view = emptyRun(ticketId);
  if (!runId) return view;
  view.runId = runId;
  const stack: CharacterId[] = [];
  for (const ev of events) {
    if (ev.run_id !== runId) continue;
    const who = ev.character ?? charOf(ev.agent);
    const node = who ? view.nodes[who] : null;
    switch (ev.kind) {
      case "run_started":
        view.status = "running";
        view.label = ev.run_label ?? null;
        view.startedAt = ev.time;
        break;
      case "agent_active":
        if (who && node) {
          node.state = "working";
          stack.push(who);
        }
        break;
      case "tool_used":
      case "approval_requested":
        if (node && ev.tool) {
          node.tool = ev.tool;
          node.tools.push(ev.tool);
        }
        if (node && ev.kind === "approval_requested" && ev.approval?.request_id != null) {
          node.approvalsFiled.push(ev.approval.request_id);
        }
        break;
      case "tool_failed":
        if (node && ev.tool) node.tools.push(`${ev.tool} (refused)`);
        break;
      case "delegation_started": {
        const to = ev.to_character ?? charOf(ev.to_agent);
        if (who && to) {
          const k = edgeKey(who, to);
          view.edges[k] = "active";
          if (!view.edgeOrder.includes(k)) view.edgeOrder.push(k);
          if (node) node.tool = null; // it is waiting on a colleague now, not using a tool
        }
        break;
      }
      case "delegation_finished":
      case "delegation_failed": {
        const to = ev.to_character ?? charOf(ev.to_agent);
        if (who && to) {
          const k = edgeKey(who, to);
          view.edges[k] = ev.kind === "delegation_failed" ? "failed" : "completed";
          if (!view.edgeOrder.includes(k)) view.edgeOrder.push(k);
        }
        break;
      }
      case "agent_finished":
        if (who && node) {
          node.state = "done";
          node.tool = null;
          node.said = ev.said ?? node.said;
          node.customerReply = ev.customer_reply ?? null;
          node.openIssues = ev.open_issues ?? [];
          const i = stack.lastIndexOf(who);
          if (i >= 0) stack.splice(i, 1);
        }
        break;
      case "run_finished":
        view.status = (ev.status as RunStatus) ?? "completed";
        view.error = ev.error ?? null;
        view.usage = ev.usage ?? null;
        view.finishedAt = ev.time;
        for (const c of ORDER) {
          const n = view.nodes[c];
          if (n.state === "idle") n.state = "out";
          if (n.state === "working") n.state = "stopped"; // the run ended before this agent finished
          n.tool = null;
        }
        // A delegation still marked active when the run ended did not finish.
        for (const k of Object.keys(view.edges)) if (view.edges[k] === "active") view.edges[k] = "failed";
        break;
    }
  }
  view.current = view.status === "running" ? stack[stack.length - 1] ?? null : null;
  return view;
}

/** Compare the Expected plan with what actually happened. Missed routes count only after the run ends. */
export function compareRoutes(expected: ExpectedRoute[], view: RunView): Record<string, RouteCompare> {
  const out: Record<string, RouteCompare> = {};
  const finished = view.status !== "none" && view.status !== "running";
  for (const r of expected) {
    const k = edgeKey(r.from, r.to);
    out[k] = view.edges[k] ? "matched" : finished ? "missed" : "pending";
  }
  for (const k of view.edgeOrder) if (!(k in out)) out[k] = "unexpected";
  return out;
}

export interface CompareSummary {
  matched: string[];
  missed: string[];
  unexpected: string[];
  pending: string[];
}

export function summarize(compare: Record<string, RouteCompare>): CompareSummary {
  const s: CompareSummary = { matched: [], missed: [], unexpected: [], pending: [] };
  for (const [k, v] of Object.entries(compare)) s[v].push(k);
  return s;
}
