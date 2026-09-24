// Follow-up z kandydatem, gdy klient milczy — zdania i etykiety (0372).
//
// Regułę (kto dzwoni, kiedy) liczy serwer; tu wyłącznie prezentacja:
// termin, plakietka, powód, ostatni kontakt. Czyste funkcje — testy bez
// montowania komponentów.

import type {
  FollowupCallerReason,
  FollowupColumn,
  FollowupOutcome,
  FollowupProcess,
  FollowupRow,
  FollowupState,
} from "@/lib/api/candidateFollowups";
import { pluralPl } from "@/lib/plural-pl";

export type FollowupTone = "danger" | "warning" | "neutral";

const BUSINESS_TZ = "Europe/Warsaw";

/** „DD.MM” z daty kalendarzowej (RRRR-MM-DD) albo chwili ISO. */
export function shortDate(value: string): string {
  const plain = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (plain) return `${plain[3]}.${plain[2]}`;
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return value;
  return moment.toLocaleDateString("pl-PL", {
    timeZone: BUSINESS_TZ,
    day: "2-digit",
    month: "2-digit",
  });
}

/** „Anna Kowalczyk” → „Anna K.” — tak rekruterzy mówią o sobie na Tablicy. */
export function shortPersonName(name: string | null | undefined): string {
  if (!name) return "";
  const parts = name.trim().split(/\s+/);
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts[0]} ${parts[parts.length - 1].charAt(0)}.`;
}

export function followupTone(state: FollowupState): FollowupTone {
  if (state === "overdue") return "danger";
  if (state === "today") return "warning";
  return "neutral";
}

export function followupDueLabel(
  row: Pick<FollowupRow, "state" | "overdue_days" | "due_on">,
): string {
  switch (row.state) {
    case "overdue":
      return `zaległy ${row.overdue_days} ${pluralPl(row.overdue_days, "dzień", "dni", "dni")}`;
    case "today":
      return "dziś";
    case "tomorrow":
      return "jutro";
    default:
      return shortDate(row.due_on);
  }
}

const COLUMN_LABEL: Record<FollowupColumn, string> = {
  cv_sent: "CV wysłane",
  client_interview: "po rozmowie u klienta",
};

/** „Nordea · CV wysłane, 16 dni” — chip procesu na liście. */
export function processChipLabel(p: FollowupProcess): string {
  const who = p.client_name ?? p.job_title;
  const days = `${p.silent_days} ${pluralPl(p.silent_days, "dzień", "dni", "dni")}`;
  return `${who} · ${COLUMN_LABEL[p.column] ?? p.column}, ${days}`;
}

export function columnLabel(column: FollowupColumn): string {
  return COLUMN_LABEL[column] ?? column;
}

const CONTACT_KIND: Record<string, string> = {
  note: "notatka",
  call: "telefon",
  email: "mail",
  meeting: "spotkanie",
  followup: "follow-up",
};

/** „Ostatni kontakt 08.09 (Anna K., notatka)” albo „Brak kontaktu od wysłania CV”. */
export function lastContactLabel(
  row: Pick<FollowupRow, "last_contact_at" | "last_contact_by" | "last_contact_kind">,
): string {
  if (!row.last_contact_at) return "Brak kontaktu od wysłania CV";
  const details = [
    shortPersonName(row.last_contact_by),
    row.last_contact_kind ? CONTACT_KIND[row.last_contact_kind] ?? row.last_contact_kind : "",
  ].filter(Boolean);
  return `Ostatni kontakt ${shortDate(row.last_contact_at)}${
    details.length ? ` (${details.join(", ")})` : ""
  }`;
}

/** Dlaczego dzwoni ta osoba — zdanie w doku Tablicy i w oknie. */
export function callerReasonSentence(
  row: Pick<FollowupRow, "caller_reason" | "caller_name" | "processes">,
): string {
  const lead = row.processes[0];
  const leadLabel = lead
    ? `${lead.client_name ?? lead.job_title}, ${columnLabel(lead.column)}`
    : "";
  const reason = row.caller_reason as FollowupCallerReason;
  switch (reason) {
    case "furthest":
      return `prowadzi proces, który zaszedł najdalej (${leadLabel})`;
    case "recent_contact":
      return "prowadzi jeden z procesów i ostatnio rozmawiał(a) z kandydatem";
    case "substitute":
      return "zastępuje właściciela procesu (nieobecność w COMPASS)";
    case "next_process":
      return "właściciel najdalszego procesu ma nieaktywne konto";
    case "claim":
      return "przejął(a) tę rundę";
    default:
      return "żaden właściciel procesu nie jest aktywny";
  }
}

export interface OutcomeOption {
  value: FollowupOutcome;
  label: string;
  hint: string;
}

export const OUTCOME_OPTIONS: OutcomeOption[] = [
  {
    value: "connected",
    label: "Rozmawialiśmy, dalej czeka",
    hint: "zamyka rundę dla wszystkich procesów",
  },
  {
    value: "changed",
    label: "Rozmawialiśmy, coś się zmieniło",
    hint: "inna oferta, dostępność, stawka, rezygnacja z procesu",
  },
  {
    value: "no_answer",
    label: "Nie odebrał",
    hint: "przypomnimy za 2 dni robocze",
  },
  {
    value: "callback",
    label: "Prosi o kontakt później",
    hint: "wybierz dzień",
  },
];

export const HISTORY_OUTCOME_LABEL: Record<string, string> = {
  connected: "dalej czeka",
  changed: "zmiana",
  no_answer: "nie odebrał",
  callback: "prosi o kontakt później",
};

/** Plakietka na karcie Tablicy: „Follow-up: Anna K. · zaległy 2 dni”
 *  (albo „Ty”, gdy dzwoni patrzący). */
export function cardBadgeLabel(
  badge: {
    caller_id: number | null;
    caller_name: string | null;
    state: FollowupState;
    overdue_days: number;
    due_on: string;
  },
  viewerId: number | null | undefined,
): string {
  const who =
    badge.caller_id == null
      ? "brak opiekuna"
      : badge.caller_id === viewerId
        ? "Ty"
        : shortPersonName(badge.caller_name) || "ktoś z zespołu";
  return `Follow-up: ${who} · ${followupDueLabel(badge)}`;
}

/** Dzisiejsza data kalendarza firmy (RRRR-MM-DD) — `min` pola „oddzwoń”. */
export function todayInBusinessTz(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: BUSINESS_TZ }).format(now);
}

/** Data `days` dni po `isoDate` (RRRR-MM-DD), bez przesunięć strefy. */
export function addDaysIso(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const moment = new Date(Date.UTC(y, m - 1, d + days));
  return moment.toISOString().slice(0, 10);
}

/** Zdanie pod wyborem wyniku: co się stanie po zapisie. */
export function nextStepSentence(outcome: FollowupOutcome, callbackOn: string | null): string {
  switch (outcome) {
    case "no_answer":
      return "Przypomnimy za 2 dni robocze. Zegar się nie zeruje.";
    case "callback":
      return callbackOn
        ? `Przypomnimy ${shortDate(callbackOn)}.`
        : "Wybierz dzień, w którym oddzwonić.";
    case "changed":
      return "Następny follow-up za 14 dni, jeśli klient dalej będzie milczał. Właściciele procesów, których dotyczy zmiana, dostaną powiadomienie.";
    default:
      return "Następny follow-up za 14 dni, jeśli klient dalej będzie milczał. Notatka trafi do profilu kandydata.";
  }
}
