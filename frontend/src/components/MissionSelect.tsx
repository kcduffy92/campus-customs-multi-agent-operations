// The three tickets as arcade levels. Status comes from the database; the stage label from the backend.
import { missionFor } from "../expected";
import { Lock } from "../art/sprites";
import type { Ticket } from "../types";

interface Props {
  tickets: Ticket[];
  selected: number;
  onSelect: (id: number) => void;
  runningTicket: number | null;
}

export function MissionSelect({ tickets, selected, onSelect, runningTicket }: Props) {
  return (
    <nav className="missions" aria-label="Tickets">
      <h2 className="sr-only">Mission select</h2>
      {tickets.length === 0 && <p className="empty">Loading tickets…</p>}
      <ul className="mission-list">
        {tickets.map((t) => {
          const m = missionFor(t.id);
          const on = t.id === selected;
          return (
            <li key={t.id}><button type="button" aria-current={on ? "true" : undefined}
              className={`mission pixel-box${on ? " selected" : ""}${t.is_resolved ? " resolved" : ""}`}
              onClick={() => onSelect(t.id)}>
              <span className="mission-level">{m?.level ?? `TICKET ${t.id}`}</span>
              <span className="mission-name">{m?.name ?? t.subject}</span>
              <span className="mission-meta">Ticket {t.id} · {t.requester}</span>
              <span className="mission-subject">{t.subject}</span>
              <span className="mission-status">
                <span className={`db-status st-${t.status}`}>{t.status.replace("_", " ")}</span>
                {runningTicket === t.id ? <span className="stage running">Agents working</span>
                  : <span className={`stage stage-${t.stage}`}>{t.stage_label}</span>}
              </span>
              {t.pending_requests > 0 && (
                <span className="mission-pending"><Lock size={12} /> {t.pending_requests} awaiting approval</span>
              )}
              {t.is_resolved && <span className="resolved-stamp" aria-hidden="true">RESOLVED</span>}
            </button></li>
          );
        })}
      </ul>
    </nav>
  );
}
