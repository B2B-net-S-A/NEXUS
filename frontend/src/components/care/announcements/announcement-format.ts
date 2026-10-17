// Słowa i stany ekranu „Komunikaty” (O12). Czyste funkcje — test obok.

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  AnnouncementKind,
  AnnouncementRow,
  AudienceGroup,
  RecipientStatus,
} from "@/lib/api/care-announcements";
import { formatDayMonthPl } from "@/lib/date-pl";

/** Pola w treści — lustro `announcement_mail.PLACEHOLDERS` (serwer odrzuca inne). */
export const PLACEHOLDERS = ["{imię}", "{opiekun}"] as const;
const PLACEHOLDER_RE = /\{[^{}\s]{1,40}\}/g;

export function unknownPlaceholders(text: string): string[] {
  const found: string[] = [];
  for (const token of text.match(PLACEHOLDER_RE) ?? []) {
    if (!(PLACEHOLDERS as readonly string[]).includes(token) && !found.includes(token)) {
      found.push(token);
    }
  }
  return found;
}

export const KIND_LABELS: Record<AnnouncementKind, string> = {
  mandatory: "Obowiązkowy",
  informational: "Informacyjny",
};

export const KIND_HINTS: Record<AnnouncementKind, string> = {
  mandatory: "sprawy umowy i rozliczeń — idzie do wszystkich z grupy",
  informational: "wydarzenia, życzenia — z linkiem wypisu",
};

export const GROUP_LABELS: Record<AudienceGroup, string> = {
  all: "Wszyscy aktywni konsultanci",
  client: "Klient…",
  owner: "Opiekun…",
  form: "Forma…",
  ending: "Kończący zamówienie",
  selected: "Wybrane osoby…",
};

const RECIPIENT_LABELS: Record<RecipientStatus, string> = {
  pending: "dostanie",
  sending: "w wysyłce",
  sent: "wysłany",
  failed: "błąd wysyłki",
  uncertain: "niepewny — sprawdź w skrzynce",
  bounced: "odbity",
  excluded_no_email: "bez adresu e-mail",
  excluded_opted_out: "wypis z informacyjnych",
  cancelled: "anulowany",
};

export function recipientStatusLabel(status: RecipientStatus): string {
  return RECIPIENT_LABELS[status];
}

/** Liczebnik po polsku: 1 błąd, 2–4 błędy, 5+ błędów (12–14 jak 5+). */
export function plural(count: number, one: string, few: string, many: string): string {
  const tens = count % 100;
  const units = count % 10;
  const word =
    count === 1 ? one : units >= 2 && units <= 4 && (tens < 12 || tens > 14) ? few : many;
  return `${count} ${word}`;
}

export interface StatusView {
  label: string;
  tone: StatusDotTone;
  note: string | null;
}

export function statusView(row: AnnouncementRow): StatusView {
  const { counts } = row;
  const errors = counts.failed + counts.uncertain;
  const parts = [plural(counts.sent, "wysłany", "wysłane", "wysłanych")];
  if (counts.bounced) parts.push(plural(counts.bounced, "odbity", "odbite", "odbitych"));
  if (errors) parts.push(plural(errors, "błąd", "błędy", "błędów"));
  switch (row.status) {
    case "draft":
      return { label: "szkic", tone: "neutral", note: null };
    case "pending":
      return {
        label: row.can_approve ? "czeka na Twoje zatwierdzenie" : "czeka na zatwierdzenie",
        tone: "warning",
        note: null,
      };
    case "queued": {
      const waiting = counts.pending + counts.sending;
      return {
        label: "w kolejce",
        tone: "info",
        note: [...parts, `${waiting} czeka`].join(", "),
      };
    }
    case "sent":
      return {
        label: row.send_finished_at
          ? `wysłany ${formatDayMonthPl(row.send_finished_at)}`
          : "wysłany",
        tone: errors ? "warning" : "success",
        note: parts.join(", "),
      };
    default:
      return {
        label: "anulowany",
        tone: "neutral",
        note: counts.sent ? `${parts[0]} przed anulowaniem` : null,
      };
  }
}

/** Minuty kolejki przy danym tempie (30 maili na minutę). */
export function sendMinutes(recipients: number, ratePerMinute: number): number {
  if (recipients <= 0 || ratePerMinute <= 0) return 0;
  return Math.ceil(recipients / ratePerMinute);
}

export interface SendState {
  saved: boolean;
  /** Niezapisane zmiany rodzaju, tematu albo treści (unieważniają próbę). */
  contentDirty: boolean;
  testCurrent: boolean;
  willReceive: number;
  sendingEnabled: boolean;
  requiresApproval: boolean;
}

/** Zdanie, dlaczego „Wyślij” jest wyłączone, albo `null`. */
export function sendBlocker(state: SendState): string | null {
  if (!state.saved || state.contentDirty || !state.testCurrent) {
    return "Najpierw wyślij komunikat próbnie do siebie — próba jest potrzebna po każdej zmianie treści.";
  }
  if (state.willReceive === 0) {
    return "Nikt z tej grupy nie dostanie komunikatu — brak adresów e-mail albo wszyscy się wypisali.";
  }
  if (!state.sendingEnabled && !state.requiresApproval) {
    return "Wysyłka do konsultantów jest wyłączona — włącza ją administrator.";
  }
  return null;
}
