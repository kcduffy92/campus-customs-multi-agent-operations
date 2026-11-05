// Which real event plays which character sound. Only events that arrived while the page was open
// trigger sounds (never the backlog), and only one sound plays per refresh.
import type { SoundId } from "./sound/sfx";
import type { ArcadeEvent } from "./types";

const SHORTAGE = /short|out of stock|0 on hand|not enough|only \d+ (?:in stock|on hand)/i;

export function soundForEvent(ev: ArcadeEvent): SoundId | null {
  switch (ev.kind) {
    case "delegation_started":
      return ev.character === "mario" ? "mario.coin" : null; // Boss hands out a task
    case "agent_active":
      return ev.character === "ryu" ? "ryu.hadouken" : null; // Facilities springs into action
    case "tool_used":
      return ev.character === "crash" ? "crash.crate" : null; // Inventory opens the crates
    case "approval_requested":
      return "spyro.approval"; // a request now waits for a person
    case "agent_finished":
      if (ev.character === "crash" && ev.said && SHORTAGE.test(ev.said)) return "crash.woah";
      if (ev.character === "sonic" && ev.customer_reply) return "sonic.ring"; // reply drafted
      return null;
    case "delegation_failed":
    case "tool_failed":
      return "ryu.impact";
    case "run_finished":
      return ev.status === "completed" ? null : "ryu.impact"; // no victory sound: a run is not a resolution
    case "approval_decided":
      return ev.decision === "approved" ? "spyro.treasure" : ev.decision === "approve_refused" ? "sonic.warn" : null;
    case "ticket_updated":
      return ev.status === "resolved" ? "mario.fanfare" : null;
    default:
      return null;
  }
}

/** The sound for a batch of new events: the latest event that has one. */
export function soundForBatch(events: ArcadeEvent[]): SoundId | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const s = soundForEvent(events[i]);
    if (s) return s;
  }
  return null;
}
