// Start a mission, then show two separate things:
//   AGENT RUN COMPLETE: the agents finished their investigation and actions (from the run's events).
//   TICKET RESOLVED:    the database says the ticket is resolved. Never shown just because a run ended.
import { useState } from "react";
import { CHARACTERS } from "../characters";
import type { Mission } from "../expected";
import { isHumanName } from "../format";
import type { CompareSummary, RunView } from "../networkState";
import type { ResolutionType, Ticket } from "../types";
import type { DecisionOutcome } from "./ApprovalGate";
import { HoldButton } from "./HoldButton";

interface Props {
  ticket: Ticket | undefined;
  mission: Mission;
  view: RunView;
  compare: CompareSummary;
  startBlocked: string | null; // why START is disabled, if it is
  starting: boolean;
  onStart: () => void;
  approverName: string;
  onResolve: (note: string, resolutionType: ResolutionType) => Promise<DecisionOutcome>;
}

const RUN_TEXT: Record<string, string> = {
  running: "AGENTS WORKING",
  completed: "AGENT RUN COMPLETE",
  error: "RUN FAILED",
  stopped_usage_limit: "RUN STOPPED: USAGE LIMIT",
  refused: "RUN REFUSED",
  cancelled: "RUN CANCELLED",
};

const routeName = (k: string) => {
  const [a, b] = k.split(">") as (keyof typeof CHARACTERS)[];
  return `${CHARACTERS[a]?.short ?? a} → ${CHARACTERS[b]?.short ?? b}`;
};

export function RunPanel({ ticket, mission, view, compare, startBlocked, starting, onStart, approverName, onResolve }: Props) {
  const [confirmation, setConfirmation] = useState("");
  const [checked, setChecked] = useState(false);
  const [resolutionType, setResolutionType] = useState<ResolutionType | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<DecisionOutcome | null>(null);
  const finished = view.status !== "none" && view.status !== "running";
  const resolved = !!ticket?.is_resolved;
  const canOfferResolve = !!ticket && !resolved && finished && ticket.pending_requests === 0;
  const nameOk = isHumanName(approverName);

  const resolve = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (resolutionType) setOutcome(await onResolve(confirmation.trim(), resolutionType));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel run pixel-box" aria-labelledby="run-title">
      <header className="panel-head">
        <div>
          <p className="eyebrow">{mission.level} · Ticket {mission.ticketId}</p>
          <h2 id="run-title">{mission.name}</h2>
        </div>
        <button type="button" className="btn start" onClick={onStart} disabled={!!startBlocked || starting}
          aria-describedby="start-why">
          {starting ? "STARTING…" : view.status === "running" ? "RUNNING…" : finished ? "RUN AGAIN" : "▶ START MISSION"}
        </button>
      </header>
      <p id="start-why" className="muted small">{startBlocked ?? "Starts the real agent team on this ticket. Each run makes live model calls."}</p>

      <div className="stamps" aria-live="polite">
        <div className={`stamp run-stamp ${view.status === "none" ? "off" : `rs-${view.status}`}`}>
          <span className="stamp-k">Agent run</span>
          <span className="stamp-v">{view.status === "none" ? "NOT STARTED" : RUN_TEXT[view.status] ?? view.status.toUpperCase()}</span>
          {view.status === "running" && view.current && <span className="stamp-n">{CHARACTERS[view.current].short} is working</span>}
          {finished && view.status === "completed" && <span className="stamp-n">The agents finished. This alone does not mean money moved or anyone received anything.</span>}
          {view.error && <span className="stamp-n danger-text">{view.error}</span>}
        </div>
        <div className={`stamp ticket-stamp ${resolved ? "on" : "off"}`}>
          <span className="stamp-k">Ticket (database)</span>
          <span className="stamp-v">{resolved ? "TICKET RESOLVED" : (ticket?.status ?? "—").replace("_", " ").toUpperCase()}</span>
          <span className="stamp-n">{ticket?.stage_label}</span>
        </div>
      </div>

      {ticket && ticket.waiting_on.length > 0 && (
        <div className="outstanding">
          <p className="sub">Still outstanding</p>
          <ul>{ticket.waiting_on.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}
      {ticket && ticket.pending_requests > 0 && (
        <p className="notice gate-notice">{ticket.pending_requests} request{ticket.pending_requests > 1 ? "s" : ""} for this ticket wait at the approval gate. {mission.gate}</p>
      )}

      {view.status !== "none" && (
        <div className="compare">
          <p className="sub">Expected vs. actual routes</p>
          <ul className="compare-list">
            {compare.matched.map((k) => <li key={k} className="c-matched">✓ {routeName(k)} · as planned</li>)}
            {compare.pending.map((k) => <li key={k} className="c-pending">… {routeName(k)} · not yet</li>)}
            {compare.missed.map((k) => <li key={k} className="c-missed">✕ {routeName(k)} · planned but not used</li>)}
            {compare.unexpected.map((k) => <li key={k} className="c-unexpected">! {routeName(k)} · not in the plan</li>)}
          </ul>
          {view.usage && <p className="muted small">Model use: {view.usage.requests ?? 0} requests · {view.usage.tool_calls ?? 0} tool calls · {(view.usage.total_tokens ?? 0).toLocaleString()} tokens</p>}
        </div>
      )}

      {canOfferResolve && (
        <form className="resolve" onSubmit={(e) => e.preventDefault()} aria-labelledby="resolve-title">
          <p id="resolve-title" className="sub">Record the resolution</p>
          <p className="muted small">{mission.resolveHint} Only a person can do this; the agents cannot.</p>
          <fieldset className="res-type">
            <legend>Type of resolution</legend>
            <label>
              <input type="radio" name="resolution-type" value="operational" checked={resolutionType === "operational"}
                onChange={() => setResolutionType("operational")} />
              <span><strong>Operational</strong>: the real-world outcome has happened, and you know it has.</span>
            </label>
            <label>
              <input type="radio" name="resolution-type" value="administrative" checked={resolutionType === "administrative"}
                onChange={() => setResolutionType("administrative")} />
              <span><strong>Administrative</strong>: the desk's work is done and the ticket is closed, but outside
                steps (delivery, stock, a customer's decision) are still outstanding.</span>
            </label>
          </fieldset>
          <label>
            <span>Resolution note</span>
            <textarea value={confirmation} onChange={(e) => setConfirmation(e.target.value)} rows={3}
              placeholder={resolutionType === "operational" ? "What was fulfilled, and how you know"
                : "What the desk completed, what you approved, and what is still outstanding"} />
          </label>
          <label className="reviewed">
            <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
            I confirm this resolution note accurately describes what has and has not happened.
          </label>
          <HoldButton label="MARK RESOLVED" tone="danger" busy={busy}
            disabled={!nameOk || !checked || !resolutionType || confirmation.trim().length < 5} onConfirm={resolve} />
          {!nameOk && <p className="hint">Enter your name in the approval panel first.</p>}
          {outcome && <p className={`notice ${outcome.ok ? "ok" : "danger"}`} role="alert">{outcome.message}</p>}
        </form>
      )}
    </section>
  );
}
