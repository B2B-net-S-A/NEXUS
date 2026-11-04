// Czyste pomocniki listy „Opieka · Ten tydzień” (bez Reacta — testowalne bez montowania).

import {
  FRONT_OFFICE_REASON_LABELS,
  type CareWeek,
  type FrontOfficeReason,
  type WeekContact,
  type WeekReason,
} from "@/lib/api/care";
import { formatDayMonthPl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Data `days` dni po `iso` (RRRR-MM-DD), bez przesunięć strefy. */
export function shiftIso(iso: string, days: number): string {
  const match = ISO.exec(iso);
  if (!match) return iso;
  const moment = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]) + days));
  return moment.toISOString().slice(0, 10);
}

/** „19–23.10” albo „28.10–01.11” — tydzień pracy w nagłówku listy. */
export function weekRangeLabel(from: string, to: string): string {
  const a = ISO.exec(from);
  const b = ISO.exec(to);
  if (!a || !b) return `${from} – ${to}`;
  if (a[2] === b[2]) return `${a[3]}–${b[3]}.${b[2]}`;
  return `${a[3]}.${a[2]}–${b[3]}.${b[2]}`;
}

/** Sam powód, bez terminu: „dzień 30”, „umówiony kontakt z 19.09”. */
export function reasonWhat(reason: WeekReason): string {
  return reason.kind === "follow_up"
    ? `umówiony kontakt${reason.from_conversation_on ? ` z ${formatDayMonthPl(reason.from_conversation_on)}` : ""}`
    : reason.kind === "pre_end"
      ? "30 dni przed końcem zamówienia"
      : reason.label.toLowerCase();
}

/** Dni między dwiema datami RRRR-MM-DD (b − a). */
export function daysBetween(a: string, b: string): number {
  const ma = ISO.exec(a);
  const mb = ISO.exec(b);
  if (!ma || !mb) return 0;
  const ta = Date.UTC(Number(ma[1]), Number(ma[2]) - 1, Number(ma[3]));
  const tb = Date.UTC(Number(mb[1]), Number(mb[2]) - 1, Number(mb[3]));
  return Math.round((tb - ta) / 86_400_000);
}

/** „kończy projekt · chce zmiany projektu”. */
export function frontOfficeText(reasons: FrontOfficeReason[]): string {
  return reasons.map((r) => FRONT_OFFICE_REASON_LABELS[r]).join(" · ");
}

/** Konsultanci menedżera w prośbie o opinię: „Jan K., Ewa L.” (imię + inicjał). */
export function shortNames(names: (string | null)[]): string {
  return names
    .map((name) => {
      const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
      if (!parts.length) return "konsultant";
      if (parts.length === 1) return parts[0];
      return `${parts[0]} ${parts[parts.length - 1][0]}.`;
    })
    .join(", ");
}

// ── Plan dni (makieta „Opieka · Ten tydzień”, 19.10.2026) ───────────────────

const WEEKDAY_SHORT = ["pn", "wt", "śr", "cz", "pt"];

export interface WeekColumn {
  /** `before` — zaległe (albo wcześniejsze niż ten tydzień), inaczej data dnia. */
  key: string;
  label: string;
  day: string | null;
  isToday: boolean;
  /** Dzień tego tygodnia, który już minął (puste = „—”, nie „wolne”). */
  isPast: boolean;
  items: WeekContact[];
}

/**
 * Kolumny „Zaległe · pn … pt”. Zaległa rozmowa (termin przed dziś) stoi
 * w „Zaległe”, nawet gdy termin wypadł w tym tygodniu — to ona czeka
 * najdłużej. W tygodniu z przyszłości pierwsza kolumna to „Wcześniej”, gdy nic
 * nie jest po terminie. Termin po piątku (serwer go nie zwraca) trafia do
 * piątku, żeby nic nie znikło.
 */
export function weekColumns(contacts: WeekContact[], week: CareWeek["week"]): WeekColumn[] {
  const days = WEEKDAY_SHORT.map((_, index) => shiftIso(week.from, index));
  // Najdłużej po terminie na górze — pod limitem kolumny zostają najstarsze.
  const before = contacts
    .filter((row) => row.overdue || row.due_on < week.from)
    .sort((a, b) => a.due_on.localeCompare(b.due_on));
  const rest = contacts.filter((row) => !before.includes(row));
  const columns: WeekColumn[] = [
    {
      key: "before",
      label: week.is_current || before.some((row) => row.overdue) ? "Zaległe" : "Wcześniej",
      day: null,
      isToday: false,
      isPast: false,
      items: before,
    },
  ];
  days.forEach((day, index) => {
    const last = index === days.length - 1;
    columns.push({
      key: day,
      label: `${WEEKDAY_SHORT[index]} ${Number(day.slice(8, 10))}`,
      day,
      isToday: day === week.today,
      isPast: day < week.today,
      items: rest.filter((row) => row.due_on === day || (last && row.due_on > day)),
    });
  });
  return columns;
}

/**
 * Kart widocznych w kolumnie od razu; reszta pod „Pokaż wszystkie (N)”.
 * Prod 20.10.2026: „Wszyscy w moim zakresie” miało 482 zaległe karty w jednej
 * kolumnie (decyzja Artura 20.10.2026: pierwsze 8 najdłużej zaległych).
 */
export const COLUMN_VISIBLE = 8;

/** Karty kolumny do pokazania i ile schowano. Wybrana karta spoza limitu rozwija kolumnę. */
export function visibleCards(
  items: WeekContact[],
  expanded: boolean,
  selectedId: number | null = null,
  limit = COLUMN_VISIBLE,
): { shown: WeekContact[]; hidden: number } {
  const selectedAt = items.findIndex((row) => row.contract_id === selectedId);
  if (expanded || items.length <= limit || selectedAt >= limit) return { shown: items, hidden: 0 };
  return { shown: items.slice(0, limit), hidden: items.length - limit };
}

/** Pasek tygodnia: zapisane rozmowy z wszystkich zaplanowanych (zapisane + otwarte). */
export function weekProgress(counts: CareWeek["counts"]): {
  done: number;
  total: number;
  percent: number;
} {
  const done = counts.done ?? 0;
  const total = done + counts.contacts;
  return { done, total, percent: total ? Math.round((done / total) * 100) : 0 };
}

export type PillTone = "danger" | "info" | "neutral" | "warning";

/**
 * Pigułka powodu na karcie: zaległa — czerwona z liczbą dni („3 dni po ·
 * dzień 30”), umówiony kontakt — niebieska. W kolumnie dnia termin widać
 * z nagłówka; poza nią (`withDate`) pigułka niesie datę.
 */
export function reasonPill(
  reason: WeekReason,
  today: string,
  withDate = false,
): { text: string; tone: PillTone } {
  const what = reasonWhat(reason);
  if (reason.due_on < today) {
    const days = daysBetween(reason.due_on, today);
    return { text: `${countPl(days, "dzień", "dni", "dni")} po · ${what}`, tone: "danger" };
  }
  const when = reason.due_on === today ? "dziś" : formatDayMonthPl(reason.due_on);
  return {
    text: withDate ? `${when} · ${what}` : what,
    tone: reason.kind === "follow_up" ? "info" : "neutral",
  };
}

const SIGNAL_PILLS: Record<string, string> = {
  attrition_risk: "ryzyko odejścia",
  wants_change: "chce zmiany projektu",
  project_end: "kończy projekt",
};

/** Sygnały z kolejki „Do przepięcia” jako krótkie pigułki („kończy projekt”). */
export function signalPills(row: WeekContact): string[] {
  const out = row.signals.map((s) => SIGNAL_PILLS[s] ?? s);
  for (const reason of row.front_office.reasons) {
    const text = FRONT_OFFICE_REASON_LABELS[reason];
    if (!out.includes(text)) out.push(text);
  }
  return out;
}

/** „czeka od 14.10” (termin minął albo dziś) albo „do 23.10”. */
export function feedbackDueText(dueOn: string, today: string): { text: string; overdue: boolean } {
  return dueOn <= today
    ? { text: `czeka od ${formatDayMonthPl(dueOn)}`, overdue: dueOn < today }
    : { text: `do ${formatDayMonthPl(dueOn)}`, overdue: false };
}
