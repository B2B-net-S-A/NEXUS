// Reguły tablicy bez Reacta: kolumny stanu, filtry, termin, „czeka od”, liczniki.
// Jeden zespół (decyzje Artura z 19.11.2026): kolumny to stan sprawy, a dawne
// kolumny zespołów są etykietami na kartach.

import type { BoCard } from "@/lib/api/back-office";

export type BoFilter = "all" | "free" | "mine" | "overdue" | "week" | "escalated";
export const FILTER_LABELS: Record<BoFilter, string> = {
  all: "Wszystkie",
  free: "Do wzięcia",
  mine: "Moje",
  overdue: "Po terminie",
  week: "Do piątku",
  escalated: "Do przydzielenia",
};

/** Kolumny tablicy: stan sprawy. „Na zewnątrz” = czeka na dział poza back office'em. */
export type BoColumn = "new" | "in_progress" | "waiting" | "outside";
export const COLUMNS: BoColumn[] = ["new", "in_progress", "waiting", "outside"];
export const COLUMN_LABELS: Record<BoColumn, string> = {
  new: "Nowe",
  in_progress: "W toku",
  waiting: "Czeka na kogoś",
  outside: "Na zewnątrz",
};

export function columnOf(card: Pick<BoCard, "state" | "outside_team">): BoColumn {
  if (card.state === "waiting") return card.outside_team ? "outside" : "waiting";
  if (card.state === "in_progress") return "in_progress";
  return "new";
}

export type DueTone = "danger" | "warning" | "neutral";

function day(iso: string): Date {
  return new Date(`${iso.slice(0, 10)}T00:00:00`);
}

function daysBetween(from: string, to: string): number {
  return Math.round((day(to).getTime() - day(from).getTime()) / 86_400_000);
}

export function formatDay(iso: string | null): string {
  if (!iso) return "bez terminu";
  const d = day(iso);
  return `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export function dueTone(due: string | null, today: string): DueTone {
  if (!due) return "neutral";
  const left = daysBetween(today, due);
  if (left < 0) return "danger";
  return left <= 3 ? "warning" : "neutral";
}

/** Piątek tygodnia kalendarza firmy; w sobotę i niedzielę ten, który się zaczyna. */
export function weekEnd(today: string): string {
  const d = day(today);
  const weekday = d.getDay();
  const offset = weekday === 6 ? 6 : weekday === 0 ? 5 : 5 - weekday;
  d.setDate(d.getDate() + offset);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function waitLabel(card: BoCard, today: string): string {
  if (card.state === "waiting" && card.waiting_on) return `czeka na: ${card.waiting_on}`;
  if (card.assignee) return `od ${formatDay(card.created_at)}`;
  if (card.actions.length > 0) return "";
  const waited = daysBetween(card.created_at, today);
  if (waited <= 0) return "dziś";
  return `${waited} ${waited === 1 ? "dzień" : "dni"} bez osoby`;
}

export function isOverdue(card: Pick<BoCard, "due_on">, today: string): boolean {
  return card.due_on != null && card.due_on.slice(0, 10) < today;
}

export function matchesFilter(card: BoCard, filter: BoFilter, me: number, today: string): boolean {
  switch (filter) {
    case "free":
      return card.assignee == null;
    case "mine":
      return card.assignee?.id === me;
    case "escalated":
      return card.escalated && card.assignee == null;
    case "overdue":
      return isOverdue(card, today);
    case "week":
      // „Do piątku” bez zaległych: te są w „Po terminie”.
      return card.due_on != null && !isOverdue(card, today) && card.due_on.slice(0, 10) <= weekEnd(today);
    default:
      return true;
  }
}

/** Etykiety wybrane w filtrze; pusty zbiór = wszystkie. */
export function matchesLabels(card: Pick<BoCard, "lane">, labels: ReadonlySet<string>): boolean {
  return labels.size === 0 || labels.has(card.lane);
}

export function labelCounts(cards: readonly Pick<BoCard, "lane">[]): Map<string, number> {
  const out = new Map<string, number>();
  for (const card of cards) out.set(card.lane, (out.get(card.lane) ?? 0) + 1);
  return out;
}

export function matchesSearch(card: BoCard, search: string): boolean {
  const needle = search.trim().toLocaleLowerCase("pl");
  if (!needle) return true;
  return [card.title, card.person, card.client, card.assignee?.name]
    .filter(Boolean)
    .some((value) => (value as string).toLocaleLowerCase("pl").includes(needle));
}


/** Pierwszeństwo cudze i jeszcze ważne: „Biorę” wymaga świadomego „mimo to”. */
export function othersPriority(card: BoCard, me: number, today: string): boolean {
  const priority = card.priority;
  if (!priority || priority.user_id === me || !priority.until) return false;
  return priority.until.slice(0, 10) >= today;
}

export function amountLabel(card: BoCard): string | null {
  if (!card.amounts?.length) return null;
  return card.amounts
    .map(({ total, currency }) => `${Number(total).toLocaleString("pl-PL", { maximumFractionDigits: 0 })} ${currency}`)
    .join(" + ");
}

export function stepSummary(card: BoCard): string | null {
  if (card.source_kind === "step") return card.parent_title ? `Krok sprawy: ${card.parent_title}` : "Krok sprawy";
  if (!card.steps) return null;
  const word = card.lane === "exit" ? "Wyjście" : card.lane === "entry" ? "Wejście" : "Kroki";
  return `${word} · ${card.steps.done} z ${card.steps.total} kroków`;
}
