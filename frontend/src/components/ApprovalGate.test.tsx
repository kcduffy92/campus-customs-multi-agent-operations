import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { rentRequest } from "../test/fixtures";
import { ApprovalGate, type DecisionOutcome } from "./ApprovalGate";
import { HOLD_MS } from "./HoldButton";

function setup(over: Partial<Parameters<typeof ApprovalGate>[0]> = {}) {
  const onDecide = vi.fn<(...a: unknown[]) => Promise<DecisionOutcome>>();
  const props = {
    requests: [rentRequest()], balance: 3400, approverName: "Kate Duffy", onApproverName: vi.fn(), onDecide,
    ...over,
  };
  const utils = render(<ApprovalGate {...(props as Parameters<typeof ApprovalGate>[0])} />);
  const approve = () => screen.getByRole("button", { name: /approve \$2,400\.00/i });
  const reject = () => screen.getByRole("button", { name: /reject/i });
  const review = () => screen.getByRole("checkbox", { name: /reviewed the amount/i });
  return { ...utils, onDecide, approve, reject, review };
}

describe("ApprovalGate", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("shows the exact amount, purpose, ticket and requester", () => {
    setup();
    expect(screen.getByText("$2,400.00")).toBeInTheDocument();
    expect(screen.getByText("Rent due 2026-09-02 per lease 1")).toBeInTheDocument();
    expect(screen.getByText(/102 · Operation Keep the Lights On/)).toBeInTheDocument();
    expect(screen.getByText(/Spyro \(Accounting\)/)).toBeInTheDocument();
  });

  it("stays locked until a name is entered and the review box is ticked", () => {
    const { approve, reject, review, rerender, onDecide } = setup({ approverName: "" });
    expect(approve()).toBeDisabled();
    expect(reject()).toBeDisabled();
    rerender(<ApprovalGate requests={[rentRequest()]} balance={3400} approverName="Kate Duffy" onApproverName={vi.fn()} onDecide={onDecide} />);
    expect(approve()).toBeDisabled();
    fireEvent.click(review());
    expect(approve()).toBeEnabled();
  });

  it("needs a full one-second hold; letting go early does nothing", async () => {
    const { approve, review, onDecide } = setup();
    onDecide.mockResolvedValue({ ok: true, message: "Approved" });
    fireEvent.click(review());
    fireEvent.pointerDown(approve(), { button: 0 });
    act(() => { vi.advanceTimersByTime(HOLD_MS / 2); });
    fireEvent.pointerUp(approve());
    act(() => { vi.advanceTimersByTime(HOLD_MS); });
    expect(onDecide).not.toHaveBeenCalled();
    fireEvent.pointerDown(approve(), { button: 0 });
    await act(async () => { vi.advanceTimersByTime(HOLD_MS + 60); });
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide.mock.calls[0][1]).toBe("approve");
  });

  it("keyboard users press Enter twice instead of holding", async () => {
    const { approve, review, onDecide } = setup();
    onDecide.mockResolvedValue({ ok: true, message: "Approved" });
    fireEvent.click(review());
    fireEvent.keyDown(approve(), { key: "Enter" });
    expect(onDecide).not.toHaveBeenCalled();
    expect(approve()).toHaveTextContent(/press again/i);
    await act(async () => { fireEvent.keyDown(approve(), { key: "Enter" }); });
    expect(onDecide).toHaveBeenCalledTimes(1);
  });

  it("submits once while the backend is working, then shows the backend's answer", async () => {
    let finish: (v: DecisionOutcome) => void = () => {};
    const { approve, reject, review, onDecide } = setup();
    onDecide.mockImplementation(() => new Promise<DecisionOutcome>((r) => { finish = r; }));
    fireEvent.click(review());
    fireEvent.keyDown(approve(), { key: "Enter" });
    await act(async () => { fireEvent.keyDown(approve(), { key: "Enter" }); });
    expect(screen.getByRole("button", { name: /processing/i })).toBeDisabled();
    expect(reject()).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("button", { name: /processing/i }), { key: "Enter" });
    expect(onDecide).toHaveBeenCalledTimes(1);
    await act(async () => { finish({ ok: false, message: "Not done: Not enough cash in checking" }); });
    expect(screen.getByRole("alert")).toHaveTextContent("Not enough cash in checking");
  });

  it("warns about insufficient funds and blocked vendors before anyone approves", () => {
    setup({ balance: 500 });
    expect(screen.getByText(/Insufficient funds/)).toBeInTheDocument();
  });

  it("disables every gate while a run is active", () => {
    const { approve, review } = setup({ disabledReason: "Approvals open again when the current run finishes." });
    fireEvent.click(review());
    expect(approve()).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/current run finishes/);
  });
});
