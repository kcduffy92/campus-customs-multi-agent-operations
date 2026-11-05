// The Expected plan from Problem 6 (output/desk_tickets.html), used to compare against real runs.
import type { CharacterId } from "./types";

export interface ExpectedRoute {
  from: CharacterId;
  to: CharacterId;
  kind: "definite" | "conditional";
  step: number;
  why: string;
  condition?: string;
}

export interface Mission {
  ticketId: number;
  level: string;
  name: string;
  routes: ExpectedRoute[];
  out: CharacterId[];
  gate: string;
  resolveHint: string;
}

export const MISSIONS: Record<number, Mission> = {
  101: {
    ticketId: 101,
    level: "LEVEL 101",
    name: "Operation Missing Tee",
    routes: [
      { from: "mario", to: "crash", kind: "definite", step: 1,
        why: "Find out whether the shirt is available before promising anything; check the stock and the supplier invoice." },
      { from: "crash", to: "spyro", kind: "conditional", step: 2, condition: "if the supplier invoice requires Accounting",
        why: "If the unpaid invoice is preventing a reprint, assess the payment and submit an approval request." },
      { from: "mario", to: "sonic", kind: "definite", step: 3,
        why: "Prepare an accurate response explaining the situation and any confirmed next steps." },
    ],
    out: ["ryu"],
    gate: "The $840 supplier invoice requires approval before any payment.",
    resolveHint: "Paying the invoice does not put a tee in the customer's hands. Note what the desk did, what you approved, and what is still outstanding (reprint, delivery, the reply being sent).",
  },
  102: {
    ticketId: 102,
    level: "LEVEL 102",
    name: "Operation Keep the Lights On",
    routes: [
      { from: "mario", to: "ryu", kind: "definite", step: 1, why: "Check the rent notice against the actual lease." },
      { from: "ryu", to: "spyro", kind: "definite", step: 2,
        why: "Once the amount and due date are confirmed, verify cash and prepare a payment request for human approval." },
    ],
    out: ["crash", "sonic"],
    gate: "The $2,400 rent payment requires approval.",
    resolveHint: "Rent tickets resolve on their own (operational) once the approved payment is recorded.",
  },
  103: {
    ticketId: 103,
    level: "LEVEL 103",
    name: "Operation Hoodie Negotiation",
    routes: [
      { from: "mario", to: "crash", kind: "definite", step: 1,
        why: "Confirm whether we have enough hoodies to fulfill the request." },
      { from: "mario", to: "spyro", kind: "definite", step: 2,
        why: "Evaluate the pricing and whether a discount makes sense, never below unit cost." },
      { from: "mario", to: "sonic", kind: "definite", step: 3,
        why: "Explain what we can actually offer, including any inventory limitations." },
    ],
    out: ["ryu"],
    gate: "Any proposed discount requires authorization before it becomes a confirmed offer.",
    resolveHint: "An approved discount is only an offer. Note the units and price offered, the shortfall, and that the club has not accepted yet unless you know it has.",
  },
};

export const missionFor = (ticketId: number): Mission | undefined => MISSIONS[ticketId];
