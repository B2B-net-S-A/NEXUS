import type { BadgeProps } from "@/components/ui/badge";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  CaseCard,
  CaseChecklistItem,
  CasePriority,
  CaseSource,
  CaseStatus,
} from "@/lib/api/admin-cases";
import { formatDayMonthPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

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

export type DueTone = "overdue" | "week" | "later" | "none";

const ISO_DAY = /^(\d{4})-(\d{2})-(\d{2})/;

function dayNumber(iso: string): number {
  const m = ISO_DAY.exec(iso);
  return m ? Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])) / 86_400_000 : 0;
}

/**
 * Termin w kolorze (makieta 19.10.2026): po terminie — czerwony (liczy
 * serwer), do piątku tego tygodnia — żółty z „dziś” / „jutro” / „za N dni”,
 * później — szary, bez terminu — wyciszony tekst. Zrobiona sprawa bez terminu.
 * Bez `today` (starsza odpowiedź) — jak dotąd „do 21.10”.
 */
export function dueBadge(
  card: Pick<CaseCard, "due_on" | "overdue" | "status">,
  today: string | undefined,
  weekEnd: string | undefined,
): { text: string; tone: DueTone } | null {
  if (card.status === "done" || card.status === "closed") return null;
  if (!card.due_on) return { text: "bez terminu", tone: "none" };
  const date = formatDayMonthPl(card.due_on);
  if (card.overdue) return { text: `po terminie · ${date}`, tone: "overdue" };
  if (!today || !weekEnd) return { text: `do ${date}`, tone: "later" };
  if (card.due_on <= weekEnd) {
    const days = dayNumber(card.due_on) - dayNumber(today);
    const when =
      days <= 0 ? "dziś" : days === 1 ? "jutro" : `za ${countPl(days, "dzień", "dni", "dni")}`;
    return { text: `${when} · ${date}`, tone: "week" };
  }
  return { text: date, tone: "later" };
}

/** Ikona źródła sprawy: skąd się wzięła. */
export const SOURCE_ICON: Record<CaseSource, "mail" | "contract" | "exit" | "manual" | "import"> = {
  mail: "mail",
  contract: "contract",
  lifecycle: "exit",
  manual: "manual",
  compass_import: "import",
};

/** Kropka priorytetu (P1 czerwona, P2 żółta, P3 szara) — etykieta w `title` i dla czytnika. */
export const PRIORITY_DOT: Record<CasePriority, string> = {
  P1: "bg-destructive",
  P2: "bg-warning",
  P3: "bg-muted-foreground/40",
};

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

const POLISH_WORD = /^[a-ząćęłńóśźż]{3,}$/i;

/**
 * Imię w narzędniku do „Powiąż z Jakubem” (makieta S4, 22.10.2026); `null` =
 * nie wiemy, jak je odmienić — przycisk mówi wtedy „Powiąż: <imię i nazwisko>”.
 * Reguły dla polskich imion: -a → -ą (Anna, Kuba), -ek → -kiem (Marek),
 * -eł → -łem (Paweł), -k/-g → -iem (Patryk), -y/-i → -m (Jerzy, Antoni),
 * inna spółgłoska → -em (Jakub, Michał). Imię na -e, -o, -u i obce znaki — `null`.
 */
export function firstNameInstrumental(fullName: string | null | undefined): string | null {
  const first = (fullName ?? "").trim().split(/\s+/)[0] ?? "";
  if (!POLISH_WORD.test(first)) return null;
  const lower = first.toLocaleLowerCase("pl");
  if (lower.endsWith("a")) return `${first.slice(0, -1)}ą`;
  if (lower.endsWith("ek")) return `${first.slice(0, -2)}kiem`;
  if (lower.endsWith("eł")) return `${first.slice(0, -2)}łem`;
  if (/[kg]$/.test(lower)) return `${first}iem`;
  if (/[yi]$/.test(lower)) return `${first}m`;
  if (/[eouąęó]$/.test(lower)) return null;
  return `${first}em`;
}

/**
 * Etykiety „Powiąż z …” dla propozycji „Kogo dotyczy?”: imię w narzędniku,
 * a gdy dwie propozycje mają to samo imię albo imienia nie da się odmienić —
 * pełne imię i nazwisko („Powiąż: Jan Nowak”).
 */
export function linkButtonLabels(
  names: readonly (string | null)[],
): string[] {
  const firsts = names.map((name) => (name ?? "").trim().split(/\s+/)[0]?.toLocaleLowerCase("pl") ?? "");
  return names.map((name, index) => {
    const unique = firsts.filter((first) => first && first === firsts[index]).length === 1;
    const instrumental = unique ? firstNameInstrumental(name) : null;
    if (instrumental) return `Powiąż z ${instrumental}`;
    return name ? `Powiąż: ${name}` : "Powiąż";
  });
}
