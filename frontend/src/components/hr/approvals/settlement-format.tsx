// Rozliczenie zgody (etap 3, 0486) — zdania i plakietki liczone z odpowiedzi
// serwera. Próg dopłaty, stany i porównanie liczy backend; tu tylko słowa.

import type {
  ApprovalComparison,
  ApprovalRequestRow,
  ApprovalSettlement,
} from "@/lib/api/hr-approvals";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

const COMPARISON_TONE: Record<ApprovalComparison["status"], string> = {
  fits: "bg-success-muted text-success-muted-foreground",
  over: "bg-warning-muted text-warning-muted-foreground",
  unknown: "bg-muted text-muted-foreground",
};

export function comparisonLabel(comparison: ApprovalComparison): string {
  if (comparison.status === "fits") return "mieści się";
  if (comparison.status === "over") return `+${comparison.percent ?? "?"}% vs zgoda`;
  return "do sprawdzenia";
}

export function ComparisonPill({ comparison }: { comparison: ApprovalComparison }) {
  return (
    <span
      className={cn(
        "whitespace-nowrap rounded-full px-2 py-px align-middle text-[11px] font-semibold",
        COMPARISON_TONE[comparison.status],
      )}
    >
      {comparisonLabel(comparison)}
    </span>
  );
}

/**
 * Podpowiedź o terminie przy rozliczeniu: [pogrubiony początek, reszta].
 * Zgoda „raz” bez dokumentu nie wygasa (decyzja Artura 22.10.2026) —
 * delegacja czy szkolenie rozliczają się rachunkiem po wydarzeniu.
 */
export function expiryHint(row: Pick<ApprovalRequestRow, "recurrence">): [string, string] {
  return row.recurrence === "once"
    ? ["Zgoda nie wygasa", " — rachunek dołączysz także po wyjeździe czy szkoleniu."]
    : ["Zgoda wygasa po 30 dniach", ", jeśli nic nie dołączysz — Finanse nie widzą wtedy „wiszącej” kwoty."];
}

/** Jedno zdanie: co dalej z rozliczeniem tej zgody. */
export function settlementLine(row: ApprovalRequestRow, settlement: ApprovalSettlement): string {
  switch (settlement.status) {
    case "open":
      return `Kup i dołącz fakturę albo paragon${
        settlement.expires_on ? ` do ${formatIsoDatePl(settlement.expires_on)}` : ""
      }. Faktura z KSeF na NIP firmy przypnie się sama, gdy sprzedawca się zgadza.`;
    case "documented":
      if (settlement.documents.some((doc) => doc.topup?.status === "pending")) {
        return "Prośba o dopłatę czeka na zatwierdzającego — potem rozliczą Finanse.";
      }
      if (settlement.comparison?.status === "over" && !settlement.documents.some((doc) => doc.topup)) {
        return `Dokumenty przekraczają zgodę o więcej niż ${settlement.tolerance_percent}% — poproś o dopłatę.`;
      }
      return "Dokument jest przy zgodzie — rozliczą go Finanse.";
    case "settled":
      return `Rozliczona przez ${settlement.settled_by_name ?? "Finanse"}${
        settlement.settled_at ? ` ${formatIsoDatePl(settlement.settled_at)}` : ""
      }.`;
    case "expired":
      return "Zgoda wygasła — 30 dni bez faktury ani paragonu. Gdy zakup jest dalej potrzebny, poproś o nową.";
    case "active":
      return row.kind === "subscription"
        ? "Subskrypcja jest w rejestrze Finansów. Dołączaj kolejne faktury, jeśli nie przychodzą przez KSeF."
        : "Wydatek cykliczny w rejestrze Finansów — każdą fakturę rozliczają osobno.";
    case "ended":
      return `Zakończona${settlement.ended_on ? ` ${formatIsoDatePl(settlement.ended_on)}` : ""}.`;
  }
}

/** Czy autor ma coś do zrobienia przy rozliczeniu (grupa „Do zrobienia”). */
export function settlementNeedsAuthor(row: ApprovalRequestRow): boolean {
  const settlement = row.settlement;
  if (!settlement) return false;
  if (settlement.status === "open") return true;
  if (settlement.documents.some((doc) => doc.can_request_topup)) return true;
  return (
    settlement.can_answer_renewal &&
    settlement.renews_on !== null &&
    settlement.renewal_asked_for === settlement.renews_on &&
    settlement.renewal_confirmed_for !== settlement.renews_on
  );
}

/** Plakietka na liście „Moich zgód”: stan rozliczenia zamiast „Zatwierdzona”. */
export function settlementPill(row: ApprovalRequestRow): string | null {
  const settlement = row.settlement;
  if (!settlement) return null;
  if (settlement.status === "open") return "dołącz fakturę";
  if (settlement.documents.some((doc) => doc.can_request_topup)) return "poproś o dopłatę";
  return settlement.status_label;
}
