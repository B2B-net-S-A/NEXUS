// Sprzedaż — krok i ostatni kontakt na ekranach. Definicje są w backendzie
// (services/sales/next_step.py), tu tylko podpisy i decyzje o wyglądzie.

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  CallOutcome,
  DecisionMapEntry,
  Opportunity,
  OpportunityLastContact,
  OpportunityStep,
  Stage,
} from "@/lib/api/sales";
import { formatDayMonthPl } from "@/lib/date-pl";
import { currencySymbol } from "@/lib/money";

import { formatDealNumber } from "./format";

const STEP_KIND: Record<OpportunityStep["kind"], string> = {
  task: "zadanie",
  call: "telefon",
  meeting: "spotkanie",
};

export function stepLabel(item: Opportunity): string {
  if (item.next_step) return `${STEP_KIND[item.next_step.kind]} ${formatDayMonthPl(item.next_step.at)}`;
  if (item.overdue_step) return `zaległe ${formatDayMonthPl(item.overdue_step.at)}`;
  return "brak kroku";
}

export function stepTone(item: Opportunity): StatusDotTone {
  if (item.next_step) return "info";
  if (item.overdue_step) return "warning";
  return item.step_alarm ? "danger" : "neutral";
}

const CONTACT_KIND: Record<OpportunityLastContact["kind"], string> = {
  call: "telefon",
  email: "mail",
  meeting: "spotkanie",
  note: "notatka",
};

function contactKindLabel(contact: OpportunityLastContact): string {
  if (contact.kind === "email" && contact.direction === "out") return "mail od nas";
  if (contact.kind === "email" && contact.direction === "in") return "mail od klienta";
  return CONTACT_KIND[contact.kind];
}

export function lastContactLabel(contact: OpportunityLastContact | null): string {
  if (!contact) return "brak kontaktu";
  return `${formatDayMonthPl(contact.at)} ${contactKindLabel(contact)}`;
}

function money(value: string | null, currency: string): string {
  return `${formatDealNumber(value)} ${currencySymbol(currency)}`;
}

/** „40 000 zł mies.”: bez dopisku kwota na tablicy czytana była jak wartość umowy. */
export function amountLabel(item: Opportunity): string {
  const monthly = Number(item.mrr_value ?? 0);
  const oneOff = Number(item.one_off_value ?? 0);
  if (monthly > 0 && oneOff > 0) return `${money(item.value, item.currency)} łącznie`;
  if (monthly > 0) return `${money(item.mrr_value, item.currency)} mies.`;
  if (oneOff > 0) return `${money(item.one_off_value, item.currency)} jednorazowo`;
  return Number(item.value ?? 0) > 0 ? money(item.value, item.currency) : "bez kwoty";
}

const LEGAL_FORMS =
  /\s*(sp[óo]łka z ograniczoną odpowiedzialnością|sp[óo]łka akcyjna|sp\.\s*z\s*o\.\s*o\.|s\.\s*a\.)/gi;

/** Nazwa firmy na kafelku bez formy prawnej; pełna zostaje w dymku. */
export function shortCompany(name: string): string {
  return name.replace(LEGAL_FORMS, "").replace(/"/g, "").replace(/\s+/g, " ").trim();
}

export function hasNoStep(item: Opportunity): boolean {
  return item.status === "open" && !item.next_step && !item.overdue_step;
}

export interface BoardCounters {
  open: number;
  noStep: number;
  waiting: number;
}

export function boardCounters(items: readonly Opportunity[]): BoardCounters {
  const open = items.filter((item) => item.status === "open");
  return {
    open: open.length,
    noStep: open.filter(hasNoStep).length,
    waiting: open.filter((item) => item.waiting_for_reply).length,
  };
}

export function canDragOpportunity(item: Opportunity, canEdit: boolean): boolean {
  return canEdit && item.status === "open" && item.stage.outcome === "open" && !item.archived_at;
}

/**
 * Cofnięcie to drugi `/move`, a `apply_stage` (lifecycle.py) ustawia `qualified_at`
 * przy każdym wejściu na linię kwalifikacji i niczego nie czyści. Ruch na tę linię
 * albo z niej nie dostaje więc „Cofnij”: dwa kliknięcia zawyżałyby KPI bez żadnej pracy.
 */
export function canUndoMove(from: Stage, target: Stage, stages: readonly Stage[]): boolean {
  const positions = stages.filter((stage) => stage.qualifies).map((stage) => stage.position);
  if (positions.length === 0) return true;
  const line = Math.min(...positions);
  return from.position < line && target.position < line;
}

const ROLE_RANK: Partial<Record<NonNullable<DecisionMapEntry["our_role"]>, number>> = {
  champion: 0,
  decision_maker: 1,
  economic_buyer: 2,
  influencer: 3,
};
const NO_RANK = 9;
const LEADERSHIP_LEVEL = 2;
const QUEUE_SIZE = 2;

function roleRank(entry: DecisionMapEntry): number {
  return (entry.our_role && ROLE_RANK[entry.our_role]) ?? NO_RANK;
}

function isIndicated(entry: DecisionMapEntry): boolean {
  return (
    roleRank(entry) !== NO_RANK ||
    (entry.decision_level !== null && entry.decision_level !== undefined && entry.decision_level <= LEADERSHIP_LEVEL)
  );
}

/** Do kogo dzwonić: osoby z rolą albo z zarządu i dyrekcji, z numerem, bez sprzeciwu. */
export function callQueue(entries: readonly DecisionMapEntry[]): DecisionMapEntry[] {
  return entries
    .filter((entry) => Boolean(entry.phone) && !entry.do_not_contact && isIndicated(entry))
    .sort(
      (a, b) =>
        roleRank(a) - roleRank(b) || (a.decision_level ?? NO_RANK) - (b.decision_level ?? NO_RANK),
    )
    .slice(0, QUEUE_SIZE);
}

/** Bez odmiany nazwisk: automat myliłby się na obcych i rzadszych nazwiskach. */
export function callAdvice(queue: readonly DecisionMapEntry[]): string | null {
  const [first, second] = queue;
  if (!first) return null;
  return second ? `Zadzwoń: ${first.name}, potem ${second.name}` : `Zadzwoń: ${first.name}`;
}

const OUTCOME_PRESET: Record<Exclude<CallOutcome, "do_not_contact">, { what: string; days: number }> = {
  connected: { what: "Wysłać podsumowanie rozmowy", days: 1 },
  no_answer: { what: "Zadzwonić ponownie", days: 1 },
  call_back: { what: "Oddzwonić", days: 3 },
  wants_offer: { what: "Przygotować i wysłać ofertę", days: 7 },
  not_now: { what: "Wrócić do tematu", days: 30 },
};

export function outcomePreset(outcome: Exclude<CallOutcome, "do_not_contact">): { what: string; days: number } {
  return OUTCOME_PRESET[outcome];
}
