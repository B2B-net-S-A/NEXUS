// Karta konsultanta (decyzja 3 z 22.10.2026, makiety P2 i S3) — czyste reguły
// wyświetlania: podtytuł, cztery liczby, wiersze spraw, filtry „Historii”.
// Bez Reacta, z testami.

import type {
  CadenceLevel,
  CardCase,
  CardKpis,
  ConsultantCardData,
  TimelineEvent,
  TimelineKind,
} from "@/lib/api/care";
import { EXTENSION_LABELS, type ExtensionOutlook } from "@/lib/api/client-people";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

import { contractForm, scoreText } from "../cadence-format";

export type KpiTone = "neutral" | "good" | "warning" | "danger";

export interface KpiView {
  label: string;
  value: string;
  note: string | null;
  tone: KpiTone;
}

/** „dziś”, „wczoraj”, „12 dni temu”. */
export function daysAgoText(days: number): string {
  if (days <= 0) return "dziś";
  if (days === 1) return "wczoraj";
  return `${days} dni temu`;
}

/** „dziś”, „jutro”, „za 34 dni”, „minął 3 dni temu”. */
export function daysAheadText(days: number): string {
  if (days === 0) return "dziś";
  if (days === 1) return "jutro";
  if (days > 1) return `za ${days} dni`;
  return days === -1 ? "minął wczoraj" : `minął ${-days} dni temu`;
}

/** Rytm w podpisie liczby „Ostatni kontakt” — krótko, jak na makiecie P2. */
export const CADENCE_SHORT: Record<CadenceLevel, string> = {
  biweekly: "co 2 tyg.",
  monthly: "co miesiąc",
  quarterly: "co kwartał",
  milestones: "tylko kamienie",
  paused: "wstrzymany",
};

/** „01.10”, a z innego roku niż dziś — pełna data. */
export function shortDate(iso: string, today: string): string {
  return iso.slice(0, 4) === today.slice(0, 4) ? formatDayMonthPl(iso) : formatIsoDatePl(iso);
}

/** „Ostatni kontakt”: data, a pod nią „20 dni temu · rytm co 2 tyg.”. */
export function lastContactKpi(
  kpi: CardKpis["last_contact"],
  cadence: { level: CadenceLevel; until_on: string | null } | null = null,
  today: string = kpi?.on ?? "",
): KpiView {
  const rhythm = cadence
    ? `rytm ${CADENCE_SHORT[cadence.level]}${cadence.until_on ? ` do ${formatDayMonthPl(cadence.until_on)}` : ""}`
    : null;
  if (!kpi) return { label: "Ostatni kontakt", value: "brak rozmów", note: rhythm, tone: "warning" };
  return {
    label: "Ostatni kontakt",
    value: shortDate(kpi.on, today),
    note: [daysAgoText(kpi.days_ago), rhythm].filter(Boolean).join(" · "),
    tone: kpi.days_ago > 60 ? "warning" : "neutral",
  };
}

/** „Zadowolenie”: „4 / 5”, pod spodem „było 5 / 5” albo „bez zmian”. */
export function satisfactionKpi(kpi: CardKpis["satisfaction"]): KpiView {
  if (!kpi) return { label: "Zadowolenie", value: "—", note: "bez oceny", tone: "neutral" };
  const tone: KpiTone = kpi.value <= 2 ? "danger" : kpi.value === 3 ? "warning" : "good";
  let note: string | null = null;
  if (kpi.previous != null) {
    note = kpi.previous === kpi.value ? "bez zmian" : `było ${kpi.previous} / 5`;
  }
  return { label: "Zadowolenie", value: `${kpi.value} / 5`, note, tone };
}

/** „Opinia menedżera”: „4,0”, pod spodem „przedłużenie: tak” (bez prognozy — data opinii). */
export function managerFeedbackKpi(
  kpi: CardKpis["manager_feedback"],
  canSee: boolean,
): KpiView {
  const label = "Opinia menedżera";
  if (!canSee) {
    return { label, value: "—", note: "widzi opiekun, DL, HoR i admin", tone: "neutral" };
  }
  if (!kpi) return { label, value: "brak opinii", note: null, tone: "neutral" };
  const extension =
    kpi.extension && kpi.extension in EXTENSION_LABELS
      ? EXTENSION_LABELS[kpi.extension as ExtensionOutlook]
      : kpi.extension;
  const note = extension ? `przedłużenie: ${extension}` : `z ${formatIsoDatePl(kpi.on)}`;
  const tone: KpiTone =
    kpi.avg == null ? "neutral" : kpi.avg < 3 ? "danger" : kpi.avg < 4 ? "warning" : "good";
  return { label, value: kpi.avg == null ? "bez ocen" : scoreText(kpi.avg), note, tone };
}

/** „Koniec zamówienia”: „22.11”, pod spodem „za 32 dni”. */
export function orderEndKpi(kpi: CardKpis["order_end"], today: string = kpi?.on ?? ""): KpiView {
  const label = "Koniec zamówienia";
  if (!kpi) return { label, value: "bez daty", note: "nic się nie kończy", tone: "neutral" };
  const tone: KpiTone = kpi.days < 0 ? "neutral" : kpi.days <= 30 ? "danger" : kpi.days <= 60 ? "warning" : "neutral";
  return { label, value: shortDate(kpi.on, today), note: daysAheadText(kpi.days), tone };
}

export function cardKpis(
  card: Pick<ConsultantCardData, "kpis" | "can_see_feedback"> & {
    cadence?: ConsultantCardData["cadence"];
  },
  today?: string,
): KpiView[] {
  return [
    lastContactKpi(card.kpis.last_contact, card.cadence ?? null, today),
    satisfactionKpi(card.kpis.satisfaction),
    managerFeedbackKpi(card.kpis.manager_feedback, card.can_see_feedback),
    orderEndKpi(card.kpis.order_end, today),
  ];
}

const KNOWN_FORMS = ["b2b", "uop", "uzlecenie"] as const;

/** Forma umowy słowem („B2B”, „Zlecenie”); nieznana zostaje tekstem z serwera. */
export function formText(form: string | null): string | null {
  if (!form) return null;
  const known = KNOWN_FORMS.find((value) => value === form);
  return known ? contractForm(known) : form;
}

/** Podtytuł karty: „Java Developer · Bank Przykładowy · B2B od 25.12.2025 · opiekun Natalia O.”. */
export function cardSubtitle(
  card: Pick<ConsultantCardData, "role" | "client_name" | "form" | "start_on" | "owner">,
): string {
  const since = card.start_on
    ? [formText(card.form), `od ${formatIsoDatePl(card.start_on)}`].filter(Boolean).join(" ")
    : formText(card.form);
  return [
    card.role,
    card.client_name,
    since,
    card.owner.name ? `opiekun ${card.owner.name}` : "bez opiekuna",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** „zespół 9 osób (4 z zewnątrz: Dostawca A, Dostawca B)” — `null`, gdy nic nie wiemy. */
export function teamText(
  size: string | null,
  externals: number | null,
  vendors: string[],
): string | null {
  const who = vendors.length ? vendors.join(", ") : null;
  const outside =
    externals != null ? `${externals} z zewnątrz${who ? `: ${who}` : ""}` : who ? `dostawcy: ${who}` : null;
  if (size) return `zespół ${size} osób${outside ? ` (${outside})` : ""}`;
  return outside;
}

const CLOSED_CASE = new Set(["done", "closed"]);

export function openCases(cases: CardCase[]): CardCase[] {
  return cases.filter((item) => !CLOSED_CASE.has(item.status));
}

export function closedCases(cases: CardCase[]): CardCase[] {
  return cases.filter((item) => CLOSED_CASE.has(item.status));
}

/** „Sprawy · 2 otwarte”. */
export function casesHeading(cases: CardCase[]): string {
  const open = openCases(cases).length;
  return open ? `Sprawy · ${countPl(open, "otwarta", "otwarte", "otwartych")}` : "Sprawy";
}

/** Źródło sprawy słowem (makieta S3: „ręcznie”, „z maila”). */
export const CASE_SOURCE_LABELS: Record<string, string> = {
  manual: "ręcznie",
  mail: "z maila",
  contract: "z kontraktu",
  lifecycle: "z wejścia albo odejścia",
  compass_import: "z Compassa",
};

/**
 * Podpis wiersza sprawy: „Negocjacje · ręcznie · prowadzi Natalia O. · treść
 * tylko w Sprawach”. Osoba ukryta przed czytającym (`assignee_hidden`) — nic
 * o osobie (nie „bez osoby”); dopisek o treści tylko przy ukrytej treści.
 */
export function caseMeta(item: CardCase): string {
  const person = item.assignee_name
    ? `prowadzi ${item.assignee_name}`
    : item.assignee_hidden
      ? null
      : "bez osoby";
  return [
    item.area_label,
    CASE_SOURCE_LABELS[item.source] ?? null,
    person,
    item.content_hidden ? "treść tylko w Sprawach" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export type CaseStatusTone = "info" | "warning" | "neutral";

/** Pigułka statusu w karcie: krótko, jak na tablicy (Nowa · W toku · Czeka). */
export function caseStatusPill(item: CardCase): { label: string; tone: CaseStatusTone } {
  switch (item.status) {
    case "new":
      return { label: "Nowa", tone: "info" };
    case "in_progress":
      return { label: "W toku", tone: "warning" };
    case "waiting":
      return { label: "Czeka", tone: "neutral" };
    default:
      return { label: item.status_label, tone: "neutral" };
  }
}

/** Termin wiersza: „odezwać się 26.10” przy „Czeka”, inaczej „do 27.10”. */
export function caseWhen(item: CardCase): string | null {
  if (item.status === "waiting" && item.follow_up_on) {
    return `odezwać się ${formatDayMonthPl(item.follow_up_on)}`;
  }
  if (item.due_on) return `do ${formatDayMonthPl(item.due_on)}`;
  if (item.follow_up_on) return `odezwać się ${formatDayMonthPl(item.follow_up_on)}`;
  return null;
}

/** „Zamknięte: Wejście konsultanta · 18.09 · 4/4” — zamknięte sprawy jedną linią. */
export function closedCasesLine(cases: CardCase[]): string | null {
  const closed = closedCases(cases);
  if (!closed.length) return null;
  const parts = closed.map((item) =>
    [
      item.title,
      item.closed_on ? formatDayMonthPl(item.closed_on) : null,
      item.checklist_total ? `${item.checklist_done ?? 0}/${item.checklist_total}` : null,
    ]
      .filter(Boolean)
      .join(" · "),
  );
  return `Zamknięte: ${parts.join("; ")}`;
}

export type HistoryFilter = "all" | "talks" | "cases" | "feedback" | "contract";

export const HISTORY_FILTERS: { value: HistoryFilter; label: string }[] = [
  { value: "all", label: "Wszystko" },
  { value: "talks", label: "Rozmowy" },
  { value: "cases", label: "Sprawy" },
  { value: "feedback", label: "Opinie" },
  { value: "contract", label: "Umowa i zamówienia" },
];

/** Do którego filtra należy zdarzenie osi; `null` = tylko „Wszystko”. */
export const KIND_FILTER: Record<TimelineKind, HistoryFilter | null> = {
  conversation: "talks",
  tech_card: "talks",
  // Punkt planu to zapowiedź rozmowy — stoi też w „Rozmowach” (makieta P2).
  plan: "talks",
  feedback: "feedback",
  case_opened: "cases",
  case_closed: "cases",
  case_linked: "cases",
  recruitment: "contract",
  start: "contract",
  order_start: "contract",
  order_end: "contract",
  contract_end: "contract",
  redeploy: null,
  owner: null,
  cadence: null,
  cadence_return: null,
  handoff: null,
};

/**
 * Zdarzenia „Historii” dla filtra: przeszłe od najnowszych i — na górze
 * listy — to, co przed nami (najbliższe najpierw). „Wszystko” pokazuje całą
 * przyszłość, inne filtry tylko jej zdarzenia (plan rozmowy w „Rozmowach”).
 */
export function historyEvents(
  events: TimelineEvent[],
  filter: HistoryFilter,
): { past: TimelineEvent[]; ahead: TimelineEvent[] } {
  const matches = (event: TimelineEvent) =>
    filter === "all" || (KIND_FILTER[event.kind] ?? null) === filter;
  const past = events
    .filter((event) => !event.future && matches(event))
    .slice()
    .sort((a, b) => (a.on === b.on ? 0 : a.on < b.on ? 1 : -1));
  const ahead = events
    .filter((event) => event.future && matches(event))
    .slice()
    .sort((a, b) => (a.on === b.on ? 0 : a.on < b.on ? -1 : 1));
  return { past, ahead };
}

/** Dopisek zdarzenia w tej samej linii: cytat po „—”, reszta po „·”. */
export function eventDetailSeparator(detail: string): string {
  return detail.startsWith("„") ? " — " : " · ";
}

/** Liczba zdarzeń przy filtrze (bez przyszłych). */
export function historyCounts(events: TimelineEvent[]): Record<HistoryFilter, number> {
  const counts: Record<HistoryFilter, number> = { all: 0, talks: 0, cases: 0, feedback: 0, contract: 0 };
  for (const event of events) {
    if (event.future) continue;
    counts.all += 1;
    const key = KIND_FILTER[event.kind] ?? null;
    if (key) counts[key] += 1;
  }
  return counts;
}
