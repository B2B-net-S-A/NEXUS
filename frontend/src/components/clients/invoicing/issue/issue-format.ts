// Logika ekranów wystawiania faktur (E4) bez Reacta — kroki karty, tony stanów,
// podgląd kwoty pozycji przy edycji.

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  IssueLine,
  IssuedInvoiceCard,
  IssuedInvoiceRow,
  IssuedStatus,
} from "@/lib/api/issued-invoices";

export const STATUS_TONE: Record<IssuedStatus, StatusDotTone> = {
  draft: "neutral",
  sending: "info",
  sent: "info",
  accepted: "success",
  rejected: "danger",
  failed: "warning",
  cancelled: "neutral",
};

export type StepState = "done" | "current" | "todo" | "failed";

export interface InvoiceStep {
  key: "draft" | "send" | "accepted" | "upo" | "paid";
  label: string;
  detail: string | null;
  state: StepState;
}

/** Szkic → Wyślij do KSeF → Przyjęta (numer KSeF) → UPO → Zapłacona. */
export function invoiceSteps(card: IssuedInvoiceCard): InvoiceStep[] {
  const accepted = card.status === "accepted";
  const sentOnce = card.status !== "draft";
  const paid = card.payment.status === "paid";
  const sendState: StepState =
    card.status === "rejected" || card.status === "failed"
      ? "failed"
      : accepted
        ? "done"
        : card.status === "sending" || card.status === "sent"
          ? "current"
          : "todo";
  return [
    {
      key: "draft",
      label: "Szkic",
      detail: card.invoice_number ?? "numer przy wysyłce",
      state: sentOnce ? "done" : "current",
    },
    {
      key: "send",
      label: "Wyślij do KSeF",
      detail:
        sendState === "failed"
          ? card.status === "rejected"
            ? "odrzucona"
            : "nie wysłano"
          : sendState === "current"
            ? "czeka na wynik"
            : null,
      state: card.status === "draft" && card.can_send ? "current" : sendState,
    },
    {
      key: "accepted",
      label: "Przyjęta",
      detail: card.ksef_number,
      state: accepted ? "done" : "todo",
    },
    {
      key: "upo",
      label: "UPO",
      detail: card.has_upo ? "pobrane" : accepted ? "czeka" : null,
      state: card.has_upo ? "done" : accepted ? "current" : "todo",
    },
    {
      key: "paid",
      label: "Zapłacona",
      detail:
        card.payment.status === "partial"
          ? "częściowo"
          : paid
            ? "z wyciągu"
            : null,
      state: paid ? "done" : accepted ? (card.payment.status === "partial" ? "current" : "todo") : "todo",
    },
  ];
}

export function paymentLabel(row: IssuedInvoiceRow): string {
  switch (row.payment.status) {
    case "paid":
      return "zapłacona";
    case "partial":
      return "częściowo";
    case "unpaid":
      return "czeka na zapłatę";
    default:
      return "—";
  }
}

function toNumber(raw: string | null | undefined): number | null {
  if (raw == null) return null;
  const value = raw.replace(/\s/g, "").replace(",", ".");
  if (!/^-?\d+(\.\d+)?$/.test(value)) return null;
  return Number(value);
}

/** Podgląd wartości netto pozycji przy edycji (serwer liczy ostatecznie). */
export function previewNet(line: Pick<IssueLine, "quantity" | "unit_price">): string | null {
  const quantity = toNumber(line.quantity);
  const price = toNumber(line.unit_price);
  if (quantity == null || price == null) return null;
  return (Math.round(quantity * price * 100) / 100).toFixed(2);
}

/** Tekst dziesiętny z przecinkiem (pole formularza) → z kropką dla API. */
export function apiDecimal(raw: string | null | undefined): string | null {
  if (raw == null) return null;
  const value = raw.replace(/\s/g, "").replace(",", ".");
  return value === "" ? null : value;
}

export function sendDisabledReason(card: IssuedInvoiceCard, ksefReason: string | null): string | null {
  if (card.can_send) return null;
  if (!card.editable) return null;
  if (ksefReason) return ksefReason;
  if (card.problems.length) return `Uzupełnij przed wysyłką: ${card.problems[0]}`;
  return "Wysyłka niedostępna.";
}
