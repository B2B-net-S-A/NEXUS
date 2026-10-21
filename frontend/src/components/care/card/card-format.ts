// Karta konsultanta (decyzja 3 z 22.10.2026) — czyste reguły wyświetlania:
// cztery liczby, filtry „Historii”, otwarte sprawy. Bez Reacta, z testami.

import type {
  CardCase,
  CardKpis,
  ConsultantCardData,
  TimelineEvent,
  TimelineKind,
} from "@/lib/api/care";
import { EXTENSION_LABELS, type ExtensionOutlook } from "@/lib/api/client-people";
import { formatIsoDatePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

import { scoreText } from "../cadence-format";

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

export function lastContactKpi(kpi: CardKpis["last_contact"]): KpiView {
  if (!kpi) return { label: "Ostatni kontakt", value: "brak rozmów", note: null, tone: "warning" };
  return {
    label: "Ostatni kontakt",
    value: daysAgoText(kpi.days_ago),
    note: formatIsoDatePl(kpi.on),
    tone: kpi.days_ago > 60 ? "warning" : "neutral",
  };
}

export function satisfactionKpi(kpi: CardKpis["satisfaction"]): KpiView {
  if (!kpi) return { label: "Zadowolenie", value: "—", note: "bez oceny", tone: "neutral" };
  const tone: KpiTone = kpi.value <= 2 ? "danger" : kpi.value === 3 ? "warning" : "good";
  let note: string | null = null;
  if (kpi.previous != null) {
    note =
      kpi.previous === kpi.value
        ? "bez zmiany"
        : `${kpi.previous > kpi.value ? "spadek" : "wzrost"} z ${kpi.previous}/5`;
  }
  return { label: "Zadowolenie", value: `${kpi.value}/5`, note, tone };
}

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
  const note = [extension ? `przedłużenie: ${extension}` : null, formatIsoDatePl(kpi.on)]
    .filter(Boolean)
    .join(" · ");
  const tone: KpiTone =
    kpi.avg == null ? "neutral" : kpi.avg < 3 ? "danger" : kpi.avg < 4 ? "warning" : "good";
  return { label, value: kpi.avg == null ? "bez ocen" : `${scoreText(kpi.avg)} / 5`, note, tone };
}

export function orderEndKpi(kpi: CardKpis["order_end"]): KpiView {
  const label = "Koniec zamówienia";
  if (!kpi) return { label, value: "bez daty", note: "nic się nie kończy", tone: "neutral" };
  const tone: KpiTone = kpi.days < 0 ? "neutral" : kpi.days <= 30 ? "danger" : kpi.days <= 60 ? "warning" : "neutral";
  return { label, value: daysAheadText(kpi.days), note: formatIsoDatePl(kpi.on), tone };
}

export function cardKpis(card: Pick<ConsultantCardData, "kpis" | "can_see_feedback">): KpiView[] {
  return [
    lastContactKpi(card.kpis.last_contact),
    satisfactionKpi(card.kpis.satisfaction),
    managerFeedbackKpi(card.kpis.manager_feedback, card.can_see_feedback),
    orderEndKpi(card.kpis.order_end),
  ];
}

const CLOSED_CASE = new Set(["done", "closed"]);

export function openCases(cases: CardCase[]): CardCase[] {
  return cases.filter((item) => !CLOSED_CASE.has(item.status));
}

/** „Sprawy · 2 otwarte”. */
export function casesHeading(cases: CardCase[]): string {
  const open = openCases(cases).length;
  return open ? `Sprawy · ${countPl(open, "otwarta", "otwarte", "otwartych")}` : "Sprawy";
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
  plan: null,
};

/** Zdarzenia „Historii” dla filtra: przeszłe od najnowszych i — tylko we „Wszystko” — przed nami. */
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
  const ahead = filter === "all" ? events.filter((event) => event.future) : [];
  return { past, ahead };
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
