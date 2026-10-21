// Zgody (0483) — teksty i kroki dla skrzynki, „Moich zgód” i formularza.
// Wszystko liczone z odpowiedzi serwera; reguły drogi zgody zna backend.

import type {
  ApprovalKind,
  ApprovalPayer,
  ApprovalRecurrence,
  ApprovalRequestRow,
  ApprovalStatus,
} from "@/lib/api/hr-approvals";
import { formatMomentPl, monthYearPl } from "@/lib/date-pl";

export const KIND_OPTIONS: {
  value: ApprovalKind;
  label: string;
  hint: string;
}[] = [
  {
    // Ekran wielu osób: neutralnie, z podstawą w umowie (decyzja Artura 21.10.2026).
    value: "bonus",
    label: "Wynagrodzenie dodatkowe",
    hint: "wymaga podstawy: punkt umowy albo aneks",
  },
  {
    value: "subscription",
    label: "Subskrypcja",
    hint: "narzędzie, licencja, abonament",
  },
  { value: "trip", label: "Koszty podróży", hint: "bilety, hotel, dojazdy" },
  { value: "gift", label: "Prezent", hint: "klient, kandydat, zespół" },
  {
    value: "training",
    label: "Szkolenie",
    hint: "kurs, konferencja, certyfikat",
  },
  { value: "other", label: "Inny wydatek", hint: "sprzęt, event, usługa" },
];

export const RECURRENCE_OPTIONS: {
  value: ApprovalRecurrence;
  label: string;
}[] = [
  { value: "once", label: "Raz" },
  { value: "monthly", label: "Co miesiąc" },
  { value: "yearly", label: "Co rok" },
];

export const PAYER_OPTIONS: { value: ApprovalPayer; label: string }[] = [
  { value: "company_invoice", label: "Faktura na firmę" },
  { value: "company_card", label: "Karta firmowa" },
  { value: "reimbursement", label: "Zwrot mi" },
];

export type StatusTone = "neutral" | "warning" | "success" | "danger";

export const STATUS_TONE: Record<ApprovalStatus, StatusTone> = {
  pending_supervisor: "neutral",
  pending_final: "neutral",
  approved: "success",
  rejected: "danger",
  returned: "warning",
  withdrawn: "neutral",
};

/** Kwota z serwera („1500.00”) po polsku: „1 500 zł”, „1 500,50 EUR”. */
export function moneyPl(value: string | null | undefined, currency = "PLN"): string {
  const amount = Number(value);
  if (value === null || value === undefined || !Number.isFinite(amount)) return "—";
  const text = new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(amount);
  return `${text} ${currency === "PLN" ? "zł" : currency}`;
}

/** Kto decyduje teraz — jedno zdanie pod tytułem zgody. */
export function stageLine(row: ApprovalRequestRow): string {
  const finals = row.final_approver_names.join(", ") || "zatwierdzający";
  switch (row.status) {
    case "pending_supervisor":
      return row.needs_final
        ? `U koordynatora (${row.supervisor_name ?? "—"}), potem ${finals}`
        : `U koordynatora (${row.supervisor_name ?? "—"})`;
    case "pending_final":
      return `Czeka na: ${finals}`;
    case "approved":
      return `Zatwierdził(a) ${row.decided_by_name ?? "—"}`;
    case "rejected":
      return `Odrzucił(a) ${row.decided_by_name ?? "—"}`;
    case "returned":
      return `Pytanie od: ${row.decided_by_name ?? "—"}`;
    case "withdrawn":
      return "Wycofana";
  }
}

/** Napis głównego przycisku: przełożony ponad próg popiera, nie zatwierdza. */
export function approveLabel(row: ApprovalRequestRow): string {
  return row.decides_as === "supervisor" && row.needs_final ? "Popieram" : "Zatwierdź";
}

/** Czy decydujący może ustalić inną kwotę (tylko decyzja, która zamyka sprawę). */
export function canChangeAmount(row: ApprovalRequestRow): boolean {
  return !(row.decides_as === "supervisor" && row.needs_final);
}

/** Linijka szczegółu premii: „Wypłata z listą: październik 2026”. */
export function payoutLine(row: ApprovalRequestRow): string | null {
  if (row.kind !== "bonus" || !row.payout_year || !row.payout_month) return null;
  return monthYearPl({ year: row.payout_year, month: row.payout_month });
}

/** Co stanie się po „Zatwierdź” / „Popieram” — (nagłówek, zdanie) pod przyciskami. */
export function afterDecision(row: ApprovalRequestRow): {
  label: string;
  text: string;
} {
  if (row.decides_as === "supervisor" && row.needs_final) {
    const finals = row.final_approver_names.join(", ") || "zatwierdzającego";
    return {
      label: "Po poparciu",
      text: `zgoda trafi do: ${finals} — kwota jest ponad Twój próg, decyzja należy do zatwierdzającego.`,
    };
  }
  return { label: "Po zatwierdzeniu", text: afterApproval(row) };
}

/** Co stanie się po zatwierdzeniu — zdanie pod przyciskami decyzji. */
export function afterApproval(row: ApprovalRequestRow): string {
  if (row.kind === "bonus") {
    const month = payoutLine(row);
    return `Wynagrodzenie dodatkowe trafi do Płac jako przyznane${month ? ` na ${month}` : ""} — bez drugiej akceptacji. ${row.beneficiary_name ?? "Osoba"} dostanie powiadomienie.`;
  }
  return `${row.requester_name ?? "Autor"} dostanie powiadomienie, że może kupić albo zapłacić.`;
}

export interface TimelineStep {
  key: string;
  title: string;
  detail: string | null;
  state: "done" | "current" | "todo";
}

/** Oś zgody w „Moich zgodach”: wysłana → poparcie → decyzja. */
export function timeline(row: ApprovalRequestRow): TimelineStep[] {
  const steps: TimelineStep[] = [
    {
      key: "sent",
      title: "Wysłana",
      detail: formatMomentPl(row.submitted_at),
      state: "done",
    },
  ];
  if (row.supervisor_name) {
    const endorsed = row.endorsed_by_name !== null;
    const supervisorClosed = !row.needs_final && row.decided_by_name === row.supervisor_name;
    steps.push({
      key: "supervisor",
      title: endorsed
        ? `Poparł(a) ${row.endorsed_by_name}`
        : supervisorClosed
          ? `Koordynator: ${row.supervisor_name}`
          : `U koordynatora: ${row.supervisor_name}`,
      detail: endorsed
        ? [formatMomentPl(row.endorsed_at), row.endorse_note].filter(Boolean).join(" · ")
        : null,
      state:
        endorsed || supervisorClosed || row.status === "pending_final"
          ? "done"
          : row.status === "pending_supervisor"
            ? "current"
            : "todo",
    });
  }
  const decided = ["approved", "rejected", "returned"].includes(row.status);
  steps.push({
    key: "decision",
    title: decided
      ? `${row.status === "approved" ? "Zatwierdził(a)" : row.status === "rejected" ? "Odrzucił(a)" : "Pytanie od"} ${row.decided_by_name ?? "—"}`
      : row.status === "withdrawn"
        ? "Wycofana"
        : `Decyzja: ${row.needs_final ? row.final_approver_names.join(", ") || "zatwierdzający" : (row.supervisor_name ?? "koordynator")}`,
    detail: decided
      ? [formatMomentPl(row.decided_at), row.decision_note].filter(Boolean).join(" · ")
      : null,
    state:
      decided || row.status === "withdrawn"
        ? "done"
        : row.status === "pending_final"
          ? "current"
          : "todo",
  });
  return steps;
}

/** Czy zgodę trzeba ruszyć do jutra (pilne w skrzynce). */
export function isUrgent(row: ApprovalRequestRow, today: string): boolean {
  if (!row.needed_by) return false;
  const tomorrow = new Date(`${today}T00:00:00Z`);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  return row.needed_by <= tomorrow.toISOString().slice(0, 10);
}
