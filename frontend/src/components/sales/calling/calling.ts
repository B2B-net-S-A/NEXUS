// Sprzedaż → Dzwonienie: podpisy i proste decyzje ekranu. Kolejność kolejki, daty
// powrotu i los wierszy importu liczy backend (services/sales/calling*.py).

import type { BadgeProps } from "@/components/ui/badge";
import { CALL_OUTCOME_LABELS } from "@/lib/api/sales";
import type {
  CallQueue,
  ImportFate,
  ImportPreview,
  QueueItem,
  QueueOutcome,
  QueueSection,
} from "@/lib/api/sales-calling";
import { formatWeekdayDayPl } from "@/lib/date-pl";

import { plural } from "../my-day";

export const SECTION_ORDER: QueueSection[] = ["callbacks", "meetings", "new"];

export const SECTION_TITLES: Record<QueueSection, string> = {
  callbacks: "Oddzwonienia na dziś",
  meetings: "Spotkania bez terminu · ustal datę",
  new: "Nowe rekordy kampanii",
};

/** Wyniki z datą powrotu: klik otwiera wybór dnia, reszta zapisuje się od razu. */
export const DATED_OUTCOMES = ["call_back", "not_now"] as const;
export type DatedOutcome = (typeof DATED_OUTCOMES)[number];

export const DATE_PRESETS: Record<DatedOutcome, { label: string; days: number }[]> = {
  call_back: [
    { label: "Jutro", days: 1 },
    { label: "Za 3 dni", days: 3 },
    { label: "Za tydzień", days: 7 },
  ],
  not_now: [
    { label: "Za miesiąc", days: 30 },
    { label: "Za kwartał", days: 90 },
    { label: "Za pół roku", days: 180 },
  ],
};

export function outcomeLabel(outcome: QueueOutcome): string {
  return CALL_OUTCOME_LABELS[outcome];
}

export function isDated(outcome: QueueOutcome): outcome is DatedOutcome {
  return (DATED_OUTCOMES as readonly string[]).includes(outcome);
}

const SATURDAY = 5;
const SUNDAY = 6;

/**
 * Dzień `days` dni po `todayIso` w kalendarzu firmy (data z serwera, bez strefy
 * przeglądarki); z soboty i niedzieli przechodzi na poniedziałek.
 */
export function plusDaysIso(todayIso: string, days: number): string {
  const [year, month, day] = todayIso.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  const weekday = (date.getUTCDay() + 6) % 7;
  if (weekday === SATURDAY) date.setUTCDate(date.getUTCDate() + 2);
  if (weekday === SUNDAY) date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

/** „pt 06.11” dla chwili z API, w kalendarzu firmy (nie w strefie przeglądarki ani UTC). */
export function weekdayOf(iso: string | null | undefined, timeZone = "Europe/Warsaw"): string {
  if (!iso) return "—";
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) return "—";
  return formatWeekdayDayPl(moment.toLocaleDateString("sv-SE", { timeZone }));
}

export function queueItems(queue: CallQueue): QueueItem[] {
  return SECTION_ORDER.flatMap((section) => queue[section]);
}

/** Następna pozycja po zapisanej; z końca listy wraca na początek. */
export function nextKey(items: readonly QueueItem[], currentKey: string): string | null {
  const index = items.findIndex((item) => item.key === currentKey);
  const rest = items.filter((item) => item.key !== currentKey);
  if (rest.length === 0) return null;
  return (items[index + 1] ?? rest[0]).key;
}

/**
 * Którą pozycję pokazać. Wybrana zostaje, dopóki jest na liście: odświeżenie kolejki
 * (np. nowa szansa w „spotkaniach bez terminu”) nie może podmienić karty w trakcie
 * pracy. Gdy zniknęła po zapisie, bierzemy następną z poprzedniej kolejności.
 */
export function resolveSelection(
  items: readonly QueueItem[],
  selectedKey: string | null,
  previousOrder: readonly string[],
): QueueItem | null {
  const current = items.find((item) => item.key === selectedKey);
  if (current) return current;
  const index = selectedKey === null ? -1 : previousOrder.indexOf(selectedKey);
  if (index >= 0) {
    const after = [...previousOrder.slice(index + 1), ...previousOrder.slice(0, index)];
    for (const key of after) {
      const next = items.find((item) => item.key === key);
      if (next) return next;
    }
  }
  return items[0] ?? null;
}

export function queueLine(queue: CallQueue): string {
  const { callbacks, meetings, new: fresh, later } = queue.counts;
  return [
    `${callbacks} do oddzwonienia`,
    plural(meetings, "spotkanie bez terminu", "spotkania bez terminu", "spotkań bez terminu"),
    plural(fresh, "nowy w kolejce", "nowe w kolejce", "nowych w kolejce"),
    ...(later > 0 ? [`${later} wróci w swoim dniu`] : []),
  ].join(" · ");
}

export function isQueueEmpty(queue: CallQueue): boolean {
  return queueItems(queue).length === 0;
}

/** Druga linia wiersza: co było ostatnio i która to rozmowa. */
export function itemReason(item: QueueItem, todayIso: string): string {
  if (item.section === "meetings") return "Spotkanie umówione, w NEXUSIE bez daty";
  if (item.state === "new") {
    return item.opportunity_id !== null
      ? `${item.opportunity_title ?? "Szansa"} · Lead od ${weekdayOf(item.since)}`
      : "Nowy rekord, jeszcze bez rozmowy";
  }
  const parts = [
    `${outcomeLabel(item.state)} ${weekdayOf(item.last_outcome_at)}`,
    `${item.attempts + 1}. rozmowa`,
  ];
  if (item.due_on && item.due_on < todayIso) parts.push(`termin minął ${formatWeekdayDayPl(item.due_on)}`);
  return parts.join(" · ");
}

export function itemTitle(item: QueueItem): string {
  if (item.campaign) return `Kampania: ${item.campaign.name}`;
  return item.section === "meetings" ? "Szansa na etapie Spotkanie kwalifikujące" : "Szansa na etapie Lead";
}

export const FATE_LABELS: Record<ImportFate, string> = {
  new_company: "Nowa firma",
  linked: "Połączono z kartą",
  already_in_campaign: "Już w kampanii",
  other_caller: "Dzwoni ktoś inny",
  client: "Klient NEXUSA",
  do_not_contact: "Nie kontaktować",
  no_phone: "Brak telefonu",
};

export const FATE_TONES: Record<ImportFate, NonNullable<BadgeProps["variant"]>> = {
  new_company: "neutral",
  linked: "success",
  already_in_campaign: "info",
  other_caller: "warning",
  client: "danger",
  do_not_contact: "danger",
  no_phone: "outline",
};

const SUMMARY_ORDER: ImportFate[] = [
  "already_in_campaign",
  "other_caller",
  "client",
  "do_not_contact",
  "no_phone",
];

const SUMMARY_TEXT: Record<ImportFate, string> = {
  new_company: "nowe firmy",
  linked: "z istniejącą kartą firmy",
  already_in_campaign: "już w kampanii",
  other_caller: "dzwoni ktoś inny",
  client: "klienci NEXUSA",
  do_not_contact: "nie kontaktować",
  no_phone: "bez telefonu",
};

/** „148 trafi do kolejki, w tym 31 do istniejącej karty firmy · 9 klienci NEXUSA”. */
export function importSummary(preview: Pick<ImportPreview, "addable" | "counts" | "without_company">): string {
  const linked = preview.counts.linked ?? 0;
  const parts = [
    `${preview.addable} trafi do kolejki${linked > 0 ? `, w tym ${linked} do istniejącej karty firmy` : ""}`,
  ];
  for (const fate of SUMMARY_ORDER) {
    const count = preview.counts[fate] ?? 0;
    if (count > 0) parts.push(`${count} ${SUMMARY_TEXT[fate]}`);
  }
  if (preview.without_company > 0) parts.push(`${preview.without_company} bez nazwy firmy pominięto`);
  return parts.join(" · ");
}

export const IMPORT_ACCEPT = ".csv,.xlsx";
export const IMPORT_MAX_BYTES = 2 * 1024 * 1024;

/** Odmowa po stronie przeglądarki, zanim plik pójdzie na serwer (serwer sprawdza to samo). */
export function fileProblem(file: Pick<File, "name" | "size">): string | null {
  const name = file.name.toLowerCase();
  if (!name.endsWith(".csv") && !name.endsWith(".xlsx")) return "Import przyjmuje plik CSV albo Excel (.xlsx).";
  if (file.size > IMPORT_MAX_BYTES) return "Plik przekracza limit 2 MB.";
  return null;
}
