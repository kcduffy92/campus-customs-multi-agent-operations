// The five agents and the characters who play them (same assignments as Problem 6).
import type { ApiAgent, CharacterId } from "./types";
import type { SoundId } from "./sound/sfx";

export interface Character {
  id: CharacterId;
  api: ApiAgent;
  name: string;
  short: string;
  role: string;
  color: string;
  lineColor?: string; // completed-line colour, when the main colour would look like another state
  sound: SoundId;
  resp: string;
}

export const CHARACTERS: Record<CharacterId, Character> = {
  mario: {
    id: "mario", api: "boss", name: "Mario", short: "Mario", role: "Boss", color: "#ff5468", sound: "mario.intro",
    resp: "Reads the ticket, decides which specialist to call first, delegates, and sets the final ticket status.",
  },
  crash: {
    id: "crash", api: "inventory", name: "Crash Bandicoot", short: "Crash", role: "Inventory", color: "#ff8a3d",
    sound: "crash.crate", resp: "Checks stock, spots shortages, and investigates restocking and supplier problems.",
  },
  spyro: {
    id: "spyro", api: "accounting", name: "Spyro", short: "Spyro", role: "Accounting", color: "#b07cff",
    sound: "spyro.gem", resp: "Checks cash and invoices, weighs discounts, and files approval requests for a person.",
  },
  ryu: {
    id: "ryu", api: "facilities", name: "Ryu", short: "Ryu", role: "Facilities", color: "#f2f2f2", lineColor: "#9fb0c8",
    sound: "ryu.hadouken", resp: "Checks rent notices against the lease and hands confirmed payments to Accounting.",
  },
  sonic: {
    id: "sonic", api: "customer_service", name: "Sonic", short: "Sonic", role: "Customer Service", color: "#4d94ff",
    sound: "sonic.ring", resp: "Drafts accurate customer replies from facts the other agents confirmed. Never sends them.",
  },
};

export const ORDER: CharacterId[] = ["mario", "crash", "spyro", "ryu", "sonic"];

export const API_TO_CHAR: Record<ApiAgent, CharacterId> = {
  boss: "mario", inventory: "crash", accounting: "spyro", facilities: "ryu", customer_service: "sonic",
};

export function charOf(agent: string | null | undefined): CharacterId | null {
  if (!agent) return null;
  return (API_TO_CHAR as Record<string, CharacterId>)[agent] ?? null;
}

export const label = (id: CharacterId) => `${CHARACTERS[id].short} (${CHARACTERS[id].role})`;
