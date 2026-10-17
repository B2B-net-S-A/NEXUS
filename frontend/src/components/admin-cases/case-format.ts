import type { BadgeProps } from "@/components/ui/badge";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  CaseCard,
  CaseChecklistItem,
  CasePriority,
  CaseStatus,
} from "@/lib/api/admin-cases";
import { formatDayMonthPl } from "@/lib/date-pl";

/** Kolumny tablicy; zamknięte tylko po zaznaczeniu „Pokaż zamknięte”. */
export const BOARD_COLUMNS: readonly CaseStatus[] = ["new", "in_progress", "waiting", "done"];

export const PRIORITY_BADGE: Record<CasePriority, NonNullable<BadgeProps["variant"]>> = {
  P1: "danger",
  P2: "warning",
  P3: "neutral",
};

export const STATUS_TONE: Record<CaseStatus, StatusDotTone> = {
  new: "info",
  in_progress: "warning",
  waiting: "neutral",
  done: "success",
  closed: "neutral",
};

/** Etykieta terminu na karcie; po terminie liczy serwer (kalendarz firmy). */
export function dueLabel(card: Pick<CaseCard, "due_on" | "overdue" | "status">): {
  text: string;
  overdue: boolean;
} | null {
  if (!card.due_on || card.status === "done" || card.status === "closed") return null;
  return card.overdue
    ? { text: `po terminie · ${formatDayMonthPl(card.due_on)}`, overdue: true }
    : { text: `do ${formatDayMonthPl(card.due_on)}`, overdue: false };
}

/** Karty w kolumnach tablicy, w kolejności z serwera (priorytet, termin). */
export function groupByStatus(
  items: readonly CaseCard[],
  columns: readonly CaseStatus[],
): Record<CaseStatus, CaseCard[]> {
  const grouped = {
    new: [],
    in_progress: [],
    waiting: [],
    done: [],
    closed: [],
  } as Record<CaseStatus, CaseCard[]>;
  for (const item of items) {
    if (columns.includes(item.status)) grouped[item.status].push(item);
  }
  return grouped;
}

/** Druga linijka karty: osoba i klient z kontraktu albo pracownik. */
export function caseSubline(card: CaseCard): string | null {
  if (card.contract) {
    return [card.contract.candidate_name, card.contract.client_name]
      .filter(Boolean)
      .join(" · ") || null;
  }
  return card.subject_user?.name ?? null;
}

export function toggleChecklistItem(
  items: readonly CaseChecklistItem[],
  index: number,
): CaseChecklistItem[] {
  return items.map((item, i) => (i === index ? { ...item, done: !item.done } : item));
}

export function addChecklistItem(
  items: readonly CaseChecklistItem[],
  text: string,
): CaseChecklistItem[] {
  const trimmed = text.trim();
  return trimmed ? [...items, { text: trimmed, done: false }] : [...items];
}

export function removeChecklistItem(
  items: readonly CaseChecklistItem[],
  index: number,
): CaseChecklistItem[] {
  return items.filter((_, i) => i !== index);
}

/** „1,2 MB” / „350 kB” — rozmiar załącznika z metadanych maila. */
export function fileSize(bytes: number | null): string {
  if (bytes == null) return "";
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))} kB`;
}
