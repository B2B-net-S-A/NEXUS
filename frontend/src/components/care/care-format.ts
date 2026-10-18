// Czyste pomocniki ekranów opieki (bez Reacta — testowalne bez montowania).

import type {
  CareConversation,
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

/** Technologie widoczne w filtrze obszaru (pusty filtr = wszystkie). */
export function technologiesInArea(
  technologies: MapTechnology[],
  area: string | null,
): MapTechnology[] {
  if (!area) return technologies;
  return technologies.filter((tech) => tech.areas.includes(area));
}

/** Krótki opis liczb źródeł do dymka („2 karty, 1 rekrutacja…”). */
export function sourceSummary(tech: MapTechnology): string {
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
