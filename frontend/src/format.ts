import type { ApprovalRequest, RequestKind } from "./types";

export const money = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD" });

export const KIND_LABEL: Record<RequestKind, string> = {
  invoice_payment: "Invoice payment",
  rent_payment: "Rent payment",
  purchase: "Stock purchase",
  discount: "Discount offer",
};

export const movesCash = (r: ApprovalRequest) => r.cash_effect < 0;

export function requestTitle(r: ApprovalRequest): string {
  const d = r.details ?? {};
  switch (r.kind) {
    case "invoice_payment":
      return `Pay invoice ${r.ref_id}${d.description ? ` — ${String(d.description)}` : ""}`;
    case "rent_payment":
      return `Pay rent to ${String(d.landlord ?? "the landlord")}${d.due_date ? `, due ${String(d.due_date)}` : ""}`;
    case "purchase":
      return `Buy ${r.quantity} × ${r.sku} size ${r.size} from ${String(d.vendor ?? `vendor ${r.ref_id}`)}`;
    case "discount":
      return `Offer ${r.quantity} × ${r.sku} size ${r.size} at ${money(r.unit_price)} each`;
  }
}

export const timeOf = (iso: string | null | undefined) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

export const isHumanName = (name: string) => name.trim().replace(/\s+/g, " ").length >= 2;
