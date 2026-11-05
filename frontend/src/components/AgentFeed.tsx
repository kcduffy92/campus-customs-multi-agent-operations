// What each agent is saying and doing, line by line, from real /events entries only.
import { CHARACTERS, charOf } from "../characters";
import { KIND_LABEL, money, timeOf } from "../format";
import { Sprite } from "../art/sprites";
import type { ArcadeEvent, CharacterId } from "../types";

export interface FeedLine {
  index: number;
  who: CharacterId | null;
  text: string;
  tone: "talk" | "act" | "tool" | "gate" | "fail" | "system" | "human";
  time: string | null;
}

export function feedLine(ev: ArcadeEvent): FeedLine | null {
  const who = ev.character ?? charOf(ev.agent);
  const name = who ? CHARACTERS[who].short : "";
  const to = ev.to_character ?? charOf(ev.to_agent);
  const toName = to ? CHARACTERS[to].short : ev.to_agent ?? "?";
  const base = { index: ev.index, who, time: ev.time };
  switch (ev.kind) {
    case "run_started":
      return { ...base, who: null, tone: "system", text: `Run started on ${ev.model ?? "the model"}${ev.run_label ? ` · ${ev.run_label}` : ""}` };
    case "agent_active":
      return { ...base, tone: "act", text: `${name} is on the case` };
    case "delegation_started":
      return { ...base, tone: "act", text: `${name} → ${toName}: hands over a task` };
    case "delegation_finished":
      return { ...base, tone: "act", text: `${toName} reported back to ${name}` };
    case "delegation_failed":
      return { ...base, tone: "fail", text: `${name} → ${toName} did not go through${ev.reason ? `: ${String(ev.reason)}` : ""}` };
    case "tool_used":
      return { ...base, tone: "tool", text: `${name} used ${ev.tool}` };
    case "approval_requested": {
      const id = ev.approval?.request_id;
      return { ...base, tone: "gate", text: ev.approval?.duplicate
        ? `${name} found request #${id} already queued (${ev.tool})`
        : `${name} filed approval request #${id ?? "?"} with ${ev.tool}. Waiting for a person.` };
    }
    case "tool_failed":
      return { ...base, tone: "fail", text: `${name}'s call to ${ev.tool} was refused` };
    case "said":
    case "agent_finished":
      return ev.said ? { ...base, tone: "talk", text: `${name}: “${ev.said}”` } : { ...base, tone: "act", text: `${name} finished` };
    case "run_finished":
      return { ...base, who: null, tone: ev.status === "completed" ? "system" : "fail",
        text: ev.status === "completed" ? "Agent run complete" : `Run ended: ${ev.status}${ev.error ? ` (${ev.error})` : ""}` };
    case "approval_decided": {
      const k = ev.request_kind ? KIND_LABEL[ev.request_kind] : "Request";
      const verb = ev.decision === "approved" ? "approved" : ev.decision === "rejected" ? "rejected" : "tried to approve";
      return { ...base, who: null, tone: ev.decision === "approve_refused" ? "fail" : "human",
        text: `${ev.decided_by} ${verb} ${k.toLowerCase()} #${ev.request_id} (${money(ev.amount)})${ev.message ? `: ${ev.message}` : ""}` };
    }
    case "ticket_updated":
      return { ...base, who: null, tone: "human",
        text: `Ticket set to ${ev.status}${ev.resolution_type ? ` (${ev.resolution_type})` : ""}: ${ev.note ?? ""}` };
    case "database_reset":
      return { ...base, who: null, tone: "system", text: "Database reset to the original. A fresh round starts here." };
    default:
      return null;
  }
}

export function AgentFeed({ events, title = "Live agent feed" }: { events: ArcadeEvent[]; title?: string }) {
  const lines = events.map(feedLine).filter((l): l is FeedLine => l !== null).slice(-80).reverse();
  return (
    <section className="panel feed pixel-box" aria-labelledby="feed-title">
      <header className="panel-head"><h2 id="feed-title">{title}</h2><span className="muted small">newest first</span></header>
      {lines.length === 0 ? (
        <p className="empty">No agent activity for this ticket yet. Press START MISSION to run the team.</p>
      ) : (
        <ol className="feed-list" role="log" aria-live="polite" aria-relevant="additions">
          {lines.map((l) => (
            <li key={l.index} className={`feed-line t-${l.tone}`}>
              <span className="feed-who">{l.who ? <Sprite id={l.who} size={22} /> : <span className="feed-dot" aria-hidden="true" />}</span>
              <span className="feed-text">{l.text}</span>
              <time className="feed-time">{timeOf(l.time)}</time>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
