import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MISSIONS } from "../expected";
import { soundForBatch, soundForEvent } from "../liveSounds";
import { buildRunView, compareRoutes, summarize } from "../networkState";
import { cash, rentRequest, rentRun, ticket } from "../test/fixtures";
import { AgentFeed, feedLine } from "./AgentFeed";
import { AgentSummaries } from "./AgentSummaries";
import { CashMeter } from "./CashMeter";
import { CommandNetwork } from "./CommandNetwork";
import { ResetDialog } from "./ResetDialog";
import { RunPanel } from "./RunPanel";

const view = () => buildRunView(rentRun(), 102, "run-102");

describe("CashMeter", () => {
  it("shows balance, commitments and what is left", () => {
    render(<CashMeter cash={cash()} previousBalance={null} pending={[rentRequest()]} decided={[]} />);
    expect(screen.getByText("$3,400.00")).toBeInTheDocument();
    expect(screen.getByText("$2,400.00", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("$1,000.00")).toBeInTheDocument();
  });

  it("after a payment shows old and new balances from the backend, with the difference", () => {
    const paid = rentRequest({ status: "executed", decided_by: "Kate Duffy", payment_id: 1 });
    render(<CashMeter cash={cash({ balance: 1000, pending_outflow: 0, available_after_pending: 1000 })} previousBalance={3400}
      pending={[]} decided={[paid, rentRequest({ id: 2, status: "rejected", decided_by: "Kate Duffy", amount: 264 })]} />);
    expect(screen.getByLabelText("was $3,400.00")).toBeInTheDocument();
    expect(screen.getByText("−$2,400.00", { selector: ".delta" })).toBeInTheDocument();
    expect(screen.getByText(/approved by Kate Duffy · payment 1/)).toBeInTheDocument();
    expect(screen.getByText("$264.00 not paid")).toBeInTheDocument();
  });

  it("marks overcommitted cash", () => {
    render(<CashMeter cash={cash({ balance: 500, pending_outflow: 840, available_after_pending: -340 })} previousBalance={null} pending={[]} decided={[]} />);
    expect(screen.getByText(/OVERCOMMITTED/)).toBeInTheDocument();
  });
});

describe("RunPanel", () => {
  const base = {
    mission: MISSIONS[102], startBlocked: null, starting: false, onStart: vi.fn(), approverName: "Kate Duffy",
    onResolve: vi.fn(),
  };
  it("shows AGENT RUN COMPLETE without claiming the ticket is resolved", () => {
    const v = view();
    render(<RunPanel {...base} ticket={ticket()} view={v} compare={summarize(compareRoutes(MISSIONS[102].routes, v))} />);
    expect(screen.getByText("AGENT RUN COMPLETE")).toBeInTheDocument();
    expect(screen.queryByText("TICKET RESOLVED")).not.toBeInTheDocument();
    expect(screen.getByText("AWAITING APPROVAL")).toBeInTheDocument();
    expect(screen.getByText(/Mario → Ryu · as planned/)).toBeInTheDocument();
  });
  it("shows TICKET RESOLVED only when the database says so", () => {
    const v = view();
    render(<RunPanel {...base} ticket={ticket({ status: "resolved", is_resolved: true, pending_requests: 0, stage: "resolved", stage_label: "Resolved (operational)", resolution_type: "operational" })}
      view={v} compare={summarize(compareRoutes(MISSIONS[102].routes, v))} />);
    expect(screen.getByText("TICKET RESOLVED")).toBeInTheDocument();
  });
  it("offers a person-confirmed resolve only after the run, with nothing pending", () => {
    const v = buildRunView(rentRun().map((e) => ({ ...e, ticket_id: 101 })), 101, "run-102");
    render(<RunPanel {...base} mission={MISSIONS[101]} ticket={ticket({ id: 101, status: "in_progress", pending_requests: 0,
      waiting_on: ["The supplier invoice is paid; the reprint still has to arrive and reach the customer."] })}
      view={v} compare={summarize(compareRoutes(MISSIONS[101].routes, v))} />);
    expect(screen.getByText(/Record the resolution/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /mark resolved/i })).toBeDisabled();
    expect(screen.getByText(/reach the customer/)).toBeInTheDocument();
  });
  it("needs a resolution type, a note and the accuracy checkbox before it unlocks", () => {
    const onResolve = vi.fn().mockResolvedValue({ ok: true, message: "ok" });
    const v = buildRunView(rentRun().map((e) => ({ ...e, ticket_id: 101 })), 101, "run-102");
    render(<RunPanel {...base} onResolve={onResolve} mission={MISSIONS[101]}
      ticket={ticket({ id: 101, status: "in_progress", pending_requests: 0 })}
      view={v} compare={summarize(compareRoutes(MISSIONS[101].routes, v))} />);
    const btn = screen.getByRole("button", { name: /mark resolved/i });
    const box = screen.getByRole("checkbox", { name: /accurately describes what has and has not happened/i });
    fireEvent.change(screen.getByRole("textbox", { name: /resolution note/i }), { target: { value: "Invoice paid; delivery outstanding" } });
    fireEvent.click(box);
    expect(btn).toBeDisabled(); // no resolution type chosen yet
    fireEvent.click(screen.getByRole("radio", { name: /administrative/i }));
    expect(btn).toBeEnabled();
    fireEvent.keyDown(btn, { key: "Enter" });
    fireEvent.keyDown(btn, { key: "Enter" });
    expect(onResolve).toHaveBeenCalledWith("Invoice paid; delivery outstanding", "administrative");
  });
  it("disables START with the reason when a run is active", () => {
    render(<RunPanel {...base} startBlocked="A run is active on ticket 101." ticket={ticket()} view={buildRunView([], 102, null)}
      compare={summarize({})} />);
    expect(screen.getByRole("button", { name: /start mission/i })).toBeDisabled();
    expect(screen.getByText("A run is active on ticket 101.")).toBeInTheDocument();
  });
});

describe("CommandNetwork", () => {
  it("draws the expected plan with no activity when there is no run", () => {
    const { container } = render(<CommandNetwork mission={MISSIONS[102]} view={buildRunView([], 102, null)}
      compare={{}} reducedMotion />);
    expect(container.querySelectorAll(".edge.s-expected")).toHaveLength(2);
    expect(container.querySelectorAll(".edge.s-active, .edge.s-completed, .pulse")).toHaveLength(0);
    expect(container.querySelector('[data-agent="crash"]')).toHaveClass("n-planned-out");
  });
  it("animates a real active delegation and shows the tool in use", () => {
    const v = buildRunView(rentRun({ finished: false }).slice(0, 9), 102, "run-102");
    const { container } = render(<CommandNetwork mission={MISSIONS[102]} view={v} compare={compareRoutes(MISSIONS[102].routes, v)} reducedMotion={false} />);
    expect(container.querySelector('[data-agent="spyro"]')).toHaveClass("n-working", "n-current");
    expect(screen.getByText("get_cash_balance")).toBeInTheDocument();
    expect(container.querySelectorAll(".edge.s-active .pulse")).toHaveLength(2);
  });
  it("lets keyboard users read a connection", () => {
    render(<CommandNetwork mission={MISSIONS[102]} view={view()} compare={compareRoutes(MISSIONS[102].routes, view())} reducedMotion />);
    const line = screen.getByRole("button", { name: /Mario → Ryu · Expected step 1 · Actual: completed/ });
    fireEvent.keyDown(line, { key: "Enter" });
    expect(screen.getByText(/Why: Check the rent notice/)).toBeInTheDocument();
  });
});

describe("AgentFeed and summaries", () => {
  it("turns events into readable lines", () => {
    const lines = rentRun().map(feedLine).filter(Boolean).map((l) => l!.text);
    expect(lines).toContain("Mario → Ryu: hands over a task");
    expect(lines).toContain("Spyro used get_cash_balance");
    expect(lines).toContain("Spyro filed approval request #1 with request_rent_payment. Waiting for a person.");
    expect(lines).toContain("Ryu: “Notice matches lease 1.”");
    expect(lines).toContain("Agent run complete");
  });
  it("shows an empty state rather than invented activity", () => {
    render(<AgentFeed events={[]} />);
    expect(screen.getByText(/No agent activity for this ticket yet/)).toBeInTheDocument();
  });
  it("summarises each agent with its tools, and who sat out", () => {
    render(<AgentSummaries view={view()} mission={MISSIONS[102]} />);
    expect(screen.getByText("Queued $2,400 rent for approval.")).toBeInTheDocument();
    expect(screen.getByText("request_rent_payment")).toBeInTheDocument();
    expect(screen.getAllByText("Not needed on this ticket, as planned.")).toHaveLength(2);
  });
});

describe("ResetDialog", () => {
  it("only resets after RESET is typed", () => {
    const onReset = vi.fn().mockResolvedValue({ ok: true, message: "done" });
    render(<ResetDialog open blocked={null} onClose={vi.fn()} onReset={onReset} />);
    const btn = screen.getByRole("button", { name: /reset database/i, hidden: true });
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { hidden: true }), { target: { value: "reset" } });
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { hidden: true }), { target: { value: "RESET" } });
    expect(btn).toBeEnabled();
    fireEvent.click(btn);
    expect(onReset).toHaveBeenCalledTimes(1);
  });
  it("is blocked while a run is active", () => {
    render(<ResetDialog open blocked="An agent run is active." onClose={vi.fn()} onReset={vi.fn()} />);
    fireEvent.change(screen.getByRole("textbox", { hidden: true }), { target: { value: "RESET" } });
    expect(screen.getByRole("button", { name: /reset database/i, hidden: true })).toBeDisabled();
  });
});

describe("live sounds", () => {
  it("plays only for real events, never a victory sound for a finished run", () => {
    const run = rentRun();
    expect(soundForEvent(run[3])).toBe("mario.coin"); // Boss delegates
    expect(soundForEvent(run[4])).toBe("ryu.hadouken"); // Facilities active
    expect(soundForEvent(run[9])).toBe("spyro.approval"); // approval requested
    expect(soundForEvent(run[run.length - 1])).toBeNull(); // run complete is not a resolution
    expect(soundForBatch([])).toBeNull();
  });
});
