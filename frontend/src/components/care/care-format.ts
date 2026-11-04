// Czyste pomocniki ekranów opieki (bez Reacta — testowalne bez montowania).

import type {
  CareConversation,
  HeatCell,
  MapTechnology,
  RedeployReason,
  TechCard,
} from "@/lib/api/care";
import { countPl } from "@/lib/plural-pl";

export type TimelineEntry =
  | { kind: "conversation"; date: string; id: number; item: CareConversation }
  | { kind: "card"; date: string; id: number; item: TechCard };

/** Oś opieki: rozmowy i karty technologiczne od najnowszych. */
export function careTimeline(
  conversations: CareConversation[],
  cards: TechCard[],
): TimelineEntry[] {
  const entries: TimelineEntry[] = [
    ...conversations.map((item) => ({
      kind: "conversation" as const,
      date: item.occurred_on,
      id: item.id,
      item,
    })),
    ...cards.map((item) => ({
      kind: "card" as const,
      date: item.interview_on,
      id: item.id,
      item,
    })),
  ];
  return entries.sort((a, b) =>
    a.date === b.date
      ? a.kind === b.kind
        ? b.id - a.id
        : a.kind === "card"
          ? -1
          : 1
      : a.date < b.date
        ? 1
        : -1,
  );
}

/** Sygnały rozmowy w jednej linii („ryzyko odejścia · chce zmiany”). */
export function conversationSignals(item: CareConversation): string[] {
  const out: string[] = [];
  if (item.attrition_risk) out.push("ryzyko odejścia");
  if (item.wants_change) out.push("chce zmiany projektu");
  if (item.project_end_on) out.push("koniec projektu");
  if (item.client_hiring) out.push("klient zatrudnia");
  return out;
}

export const REDEPLOY_ORDER: RedeployReason[] = [
  "project_end",
  "attrition_risk",
  "wants_change",
];

/** Krótki opis liczb źródeł do dymka („2 karty, 1 rekrutacja…”). */
export function sourceSummary(tech: Pick<MapTechnology, "counts">): string {
  const parts: string[] = [];
  const { cards, jobs, consultants, notes } = tech.counts;
  if (cards) parts.push(countPl(cards, "karta", "karty", "kart"));
  if (jobs) parts.push(countPl(jobs, "rekrutacja", "rekrutacje", "rekrutacji"));
  if (consultants) parts.push(countPl(consultants, "konsultant", "konsultantów", "konsultantów"));
  if (notes) parts.push(countPl(notes, "notatka", "notatki", "notatek"));
  return parts.join(", ");
}

/** Wpisy technologii z pola tekstowego (przecinek, średnik albo nowa linia). */
export function splitNames(raw: string): string[] {
  return raw
    .split(/[,;\n]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

/** Litery źródeł w komórce mapy cieplnej, w stałej kolejności T · R · K · N. */
const SOURCE_LETTERS: [keyof HeatCell["counts"], string][] = [
  ["cards", "T"],
  ["jobs", "R"],
  ["consultants", "K"],
  ["notes", "N"],
];

export function cellLetters(cell: HeatCell | null): string[] {
  if (!cell) return [];
  return SOURCE_LETTERS.filter(([key]) => cell.counts[key] > 0).map(([, letter]) => letter);
}

/** Siła koloru komórki: 0 — brak, 1–3 — liczba rodzajów źródeł (cztery = 3). */
export function heatLevel(cell: HeatCell | null): 0 | 1 | 2 | 3 {
  const n = cell?.source_count ?? 0;
  return n <= 0 ? 0 : n >= 3 ? 3 : (n as 1 | 2);
}

/** Dymek komórki: „Płatności · Java 17: 3 karty, 4 rekrutacje · 1 otwarta rekrutacja”. */
export function cellTitle(area: string, tech: string, cell: HeatCell | null): string {
  if (!cell) return `${area} · ${tech}: brak źródeł`;
  const parts = [sourceSummary(cell)].filter(Boolean);
  if (cell.open_jobs) {
    parts.push(countPl(cell.open_jobs, "otwarta rekrutacja", "otwarte rekrutacje", "otwartych rekrutacji"));
  }
  return `${area} · ${tech}: ${parts.join(" · ")}`;
}
