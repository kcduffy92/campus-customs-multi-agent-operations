// Human approval gates: every pending payment, purchase and discount the agents asked for.
// The person names themselves, ticks "reviewed", then holds (or double-presses) to approve or reject.
// The frontend only calls the backend; the backend decides and reports what really happened.
import { useRef, useState } from "react";
import { charOf, CHARACTERS } from "../characters";
import { missionFor } from "../expected";
import { isHumanName, KIND_LABEL, money, movesCash, requestTitle } from "../format";
import { Gate, Sprite } from "../art/sprites";
import type { ApprovalRequest } from "../types";
import { HoldButton } from "./HoldButton";

export type Decision = "approve" | "reject";
export interface DecisionOutcome { ok: boolean; message: string }

interface Props {
  requests: ApprovalRequest[]; // pending only
  balance: number | null;
  approverName: string;
  onApproverName: (name: string) => void;
  onDecide: (request: ApprovalRequest, decision: Decision) => Promise<DecisionOutcome>;
  disabledReason?: string | null; // e.g. "An agent run is active"
  selectedTicket?: number;
}

export function ApprovalGate({ requests, balance, approverName, onApproverName, onDecide, disabledReason, selectedTicket }: Props) {
  const [reviewed, setReviewed] = useState<Record<number, boolean>>({});
  const [busy, setBusy] = useState<Record<number, Decision | undefined>>({});
  const [outcomes, setOutcomes] = useState<Record<number, DecisionOutcome & { decision: Decision }>>({});
  const inFlight = useRef(new Set<number>());
  const nameOk = isHumanName(approverName);

  const decide = async (r: ApprovalRequest, decision: Decision) => {
    if (inFlight.current.has(r.id)) return; // duplicate-click protection
    inFlight.current.add(r.id);
    setBusy((b) => ({ ...b, [r.id]: decision }));
    try {
      const out = await onDecide(r, decision);
      setOutcomes((o) => ({ ...o, [r.id]: { ...out, decision } }));
    } finally {
      inFlight.current.delete(r.id);
      setBusy((b) => ({ ...b, [r.id]: undefined }));
    }
  };

  const sorted = [...requests].sort((a, b) =>
    Number(b.ticket_id === selectedTicket) - Number(a.ticket_id === selectedTicket) || a.id - b.id);

  return (
    <section className="panel approvals pixel-box" aria-labelledby="approvals-title">
      <header className="panel-head">
        <h2 id="approvals-title">Human approval gates</h2>
        <span className={`count-pill${requests.length ? " hot" : ""}`}>{requests.length} waiting</span>
      </header>
      <label className="approver">
        <span>Your name (recorded with every decision)</span>
        <input value={approverName} onChange={(e) => onApproverName(e.target.value)} placeholder="e.g. Kate Duffy"
          autoComplete="name" aria-invalid={approverName.length > 0 && !nameOk} />
      </label>
      {disabledReason && <p className="notice warn" role="status">{disabledReason}</p>}
      {sorted.length === 0 && (
        <p className="empty">No requests are waiting. Agents file them here; nothing is paid until a person approves.</p>
      )}
      <ul className="gate-list">
        {sorted.map((r) => {
          const who = charOf(r.requested_by);
          const m = missionFor(r.ticket_id);
          const short = movesCash(r) && balance != null && r.amount > balance;
          const blockedVendor = r.kind === "purchase" && Array.isArray(r.details?.vendor_open_invoices)
            && (r.details?.vendor_open_invoices as unknown[]).length > 0;
          const can = nameOk && !!reviewed[r.id] && !disabledReason;
          const b = busy[r.id];
          const out = outcomes[r.id];
          return (
            <li key={r.id} className={`gate-card${short ? " short" : ""}${r.ticket_id === selectedTicket ? " current" : ""}`}>
              <div className="gate-top">
                <Gate size={44} />
                <div>
                  <p className="gate-kind">{KIND_LABEL[r.kind]} · request #{r.id}</p>
                  <p className="gate-amount">{money(r.amount)}</p>
                  <p className="gate-effect">{movesCash(r) ? `Moves ${money(r.amount)} out of checking` : "Moves no cash (price offer only)"}</p>
                </div>
              </div>
              <p className="gate-title">{requestTitle(r)}</p>
              <dl className="gate-facts">
                <dt>Ticket</dt><dd>{r.ticket_id}{m ? ` · ${m.name}` : ""}</dd>
                <dt>Purpose</dt><dd>{r.reason}</dd>
                <dt>Asked by</dt>
                <dd className="asked-by">{who && <Sprite id={who} size={20} />}{who ? `${CHARACTERS[who].short} (${CHARACTERS[who].role})` : r.requested_by}</dd>
              </dl>
              {short && <p className="notice danger">Insufficient funds: checking has {money(balance)}. The backend will refuse this payment.</p>}
              {blockedVendor && <p className="notice warn">This vendor has an open invoice and won't ship until it is paid. The backend will refuse the purchase.</p>}
              <label className="reviewed">
                <input type="checkbox" checked={!!reviewed[r.id]} onChange={(e) => setReviewed((v) => ({ ...v, [r.id]: e.target.checked }))} />
                I reviewed the amount, purpose and ticket for request #{r.id}.
              </label>
              <div className="gate-actions">
                <HoldButton label={`APPROVE ${money(r.amount)}`} tone="approve" disabled={!can || (!!b && b !== "approve")}
                  busy={b === "approve"} onConfirm={() => decide(r, "approve")} />
                <HoldButton label="REJECT" tone="reject" disabled={!can || (!!b && b !== "reject")}
                  busy={b === "reject"} onConfirm={() => decide(r, "reject")} />
              </div>
              {!nameOk && <p className="hint">Enter your name above to unlock this gate.</p>}
              {out && <p className={`notice ${out.ok ? "ok" : "danger"}`} role="alert">{out.message}</p>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
