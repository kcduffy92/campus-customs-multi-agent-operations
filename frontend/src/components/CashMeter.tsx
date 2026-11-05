// The checking account, straight from GET /cash. When the balance changes it shows the old value
// struck through and the new one with the difference: no counting animation, no made-up figures.
import { KIND_LABEL, money } from "../format";
import type { ApprovalRequest, Cash } from "../types";

interface Props {
  cash: Cash | null;
  previousBalance: number | null; // the balance before the latest change, if it changed this session
  pending: ApprovalRequest[];
  decided: ApprovalRequest[]; // executed and rejected
}

export function CashMeter({ cash, previousBalance, pending, decided }: Props) {
  const changed = cash && previousBalance != null && previousBalance !== cash.balance;
  const delta = changed ? cash.balance - previousBalance : 0;
  const executed = decided.filter((r) => r.status === "executed");
  const rejected = decided.filter((r) => r.status === "rejected");
  const pendingCash = pending.filter((r) => r.cash_effect < 0);
  const over = cash ? cash.available_after_pending < 0 : false;

  return (
    <section className="panel cash pixel-box" aria-labelledby="cash-title">
      <header className="panel-head">
        <h2 id="cash-title">Treasure vault · checking</h2>
        {cash && <span className="muted small">as of {cash.as_of}</span>}
      </header>
      {!cash ? <p className="empty">Waiting for the backend…</p> : (
        <>
          <div className={`balance${changed ? " changed" : ""}`} aria-live="polite">
            {changed && <span className="old-balance" aria-label={`was ${money(previousBalance)}`}>{money(previousBalance)}</span>}
            <span className="big-balance" key={cash.balance}>{money(cash.balance)}</span>
            {changed && <span className={`delta ${delta < 0 ? "down" : "up"}`}>{delta < 0 ? "−" : "+"}{money(Math.abs(delta))}</span>}
          </div>
          <dl className="cash-lines">
            <dt>Pending commitments</dt>
            <dd className={pendingCash.length ? "pending" : ""}>{money(cash.pending_outflow)}
              {pendingCash.length > 0 && <span className="muted small"> ({pendingCash.length} request{pendingCash.length > 1 ? "s" : ""} awaiting approval)</span>}</dd>
            <dt>Available after commitments</dt>
            <dd className={over ? "danger-text" : ""}>{money(cash.available_after_pending)}{over && " · OVERCOMMITTED"}</dd>
          </dl>
          <h3 className="sub">Approved transactions</h3>
          {executed.length === 0 ? <p className="empty small">None yet. Cash only moves when a person approves a request.</p> : (
            <ul className="tx-list">
              {executed.map((r) => (
                <li key={r.id} className="tx executed">
                  <span>{KIND_LABEL[r.kind]} #{r.id} · ticket {r.ticket_id}</span>
                  <span className="tx-amt">{r.cash_effect < 0 ? `−${money(r.amount)}` : "no cash moved"}</span>
                  <span className="muted small">approved by {r.decided_by}{r.payment_id ? ` · payment ${r.payment_id}` : ""}</span>
                </li>
              ))}
            </ul>
          )}
          {rejected.length > 0 && (
            <>
              <h3 className="sub">Rejected</h3>
              <ul className="tx-list">
                {rejected.map((r) => (
                  <li key={r.id} className="tx rejected">
                    <span>{KIND_LABEL[r.kind]} #{r.id} · ticket {r.ticket_id}</span>
                    <span className="tx-amt">{money(r.amount)} not paid</span>
                    <span className="muted small">rejected by {r.decided_by}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
