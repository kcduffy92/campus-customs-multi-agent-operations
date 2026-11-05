// One card per agent on the selected ticket's latest run: what it concluded and which tools it used.
import { CHARACTERS, ORDER } from "../characters";
import type { Mission } from "../expected";
import type { RunView } from "../networkState";
import { Sprite } from "../art/sprites";

export function AgentSummaries({ view, mission }: { view: RunView; mission: Mission }) {
  const ran = ORDER.filter((c) => view.nodes[c].state !== "idle" && view.nodes[c].state !== "out");
  return (
    <section className="panel summaries pixel-box" aria-labelledby="summaries-title">
      <header className="panel-head"><h2 id="summaries-title">What each agent did</h2></header>
      {view.status === "none" ? (
        <p className="empty">No run on this ticket yet. Summaries appear here as each agent finishes.</p>
      ) : (
        <ul className="summary-grid">
          {ran.map((c) => {
            const n = view.nodes[c], ch = CHARACTERS[c];
            return (
              <li key={c} className={`summary-card s-${n.state}`} style={{ ["--accent" as string]: ch.color }}>
                <div className="summary-head">
                  <Sprite id={c} size={36} />
                  <div><p className="summary-name">{ch.short}</p><p className="summary-role">{ch.role}</p></div>
                  <span className="summary-state">{n.state === "working" ? "WORKING" : n.state === "stopped" ? "STOPPED" : "DONE"}</span>
                </div>
                <p className="summary-said">{n.said ?? (n.state === "working" ? "Working on it…" : "No summary was recorded.")}</p>
                {n.tools.length > 0 && (
                  <p className="summary-tools"><span className="muted small">MCP tools:</span>{" "}
                    {[...new Set(n.tools)].map((t) => <code key={t}>{t}</code>)}</p>
                )}
                {n.approvalsFiled.length > 0 && <p className="summary-gate">Filed approval request{n.approvalsFiled.length > 1 ? "s" : ""} #{n.approvalsFiled.join(", #")}</p>}
                {n.customerReply && (
                  <details className="summary-reply"><summary>Draft reply to the customer (not sent)</summary><p>{n.customerReply}</p></details>
                )}
                {n.openIssues.length > 0 && (
                  <ul className="summary-issues">{n.openIssues.map((i) => <li key={i}>{i}</li>)}</ul>
                )}
              </li>
            );
          })}
          {view.status !== "running" && ORDER.filter((c) => view.nodes[c].state === "out").map((c) => (
            <li key={c} className="summary-card s-out" style={{ ["--accent" as string]: CHARACTERS[c].color }}>
              <div className="summary-head">
                <Sprite id={c} size={36} />
                <div><p className="summary-name">{CHARACTERS[c].short}</p><p className="summary-role">{CHARACTERS[c].role}</p></div>
                <span className="summary-state">SAT OUT</span>
              </div>
              <p className="summary-said muted">{mission.out.includes(c) ? "Not needed on this ticket, as planned." : "Not called this run, although the plan expected it."}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
