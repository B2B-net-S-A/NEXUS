// Sprzedaż → Oferty: podpisy i drobne decyzje o wyglądzie. Sekcje, dni bez ruchu
// i liczniki liczy backend (services/sales/offers.py); tu nic się nie przelicza.

import type {
  OfferRow,
  OfferScope,
  OfferSectionTotals,
  OfferStep,
  Offers,
  Pipeline,
  Stage,
} from "@/lib/api/sales";
import { formatDayMonthPl } from "@/lib/date-pl";

import { formatDealNumber } from "./format";
import { plural } from "./my-day";

export const OFFER_SCOPES: readonly OfferScope[] = ["mine", "unowned", "all"];

export const OFFER_SCOPE_LABELS: Record<OfferScope, string> = {
  mine: "Moje",
  unowned: "Bez opiekuna",
  all: "Wszystkie",
};

const STEP_KIND: Record<OfferStep["kind"], string> = {
  task: "Zadanie",
  call: "Telefon",
  meeting: "Spotkanie",
};

/** „Moje 25”; przed pierwszą odpowiedzią sam podpis, bez zera, które nic nie znaczy. */
export function scopeLabel(scope: OfferScope, totals: Offers["totals"] | undefined): string {
  if (!totals) return OFFER_SCOPE_LABELS[scope];
  const { in_progress: inProgress, to_decide: toDecide } = totals[scope];
  return `${OFFER_SCOPE_LABELS[scope]} ${inProgress.count + toDecide.count}`;
}

/** „3 pozycje · 110 000 zł MRR”: pozycje, nie oferty, bo „Do decyzji” ma też inne etapy. */
export function sectionHint(totals: OfferSectionTotals): string {
  const count = plural(totals.count, "pozycja", "pozycje", "pozycji");
  return Number(totals.mrr) > 0 ? `${count} · ${formatDealNumber(totals.mrr)} zł MRR` : count;
}

/** Data pierwsza, bo wąska kolumna ucina koniec tekstu, a termin ma być widać zawsze. */
export function offerStepText(step: OfferStep): string {
  return `${formatDayMonthPl(step.at)} · ${step.subject ?? STEP_KIND[step.kind]}`;
}

/**
 * Etap pod nazwą szansy: tylko gdy pozycja nie jest ofertą z głównego lejka,
 * bo tam etap wynika z samej zakładki.
 */
export function stageNote(row: OfferRow, defaultPipelineId: number | null): string | null {
  const inDefault = defaultPipelineId === null || row.pipeline_id === defaultPipelineId;
  if (row.is_offer && inDefault) return null;
  return inDefault ? row.stage.name : `${row.pipeline_name}: ${row.stage.name}`;
}

/** Etapy przegranej lejka; „Przegrana” pierwsza, bo to domyślny wybór przy zamykaniu oferty. */
export function lostStages(pipelines: readonly Pipeline[] | undefined, pipelineId: number): Stage[] {
  const stages = pipelines?.find((pipeline) => pipeline.id === pipelineId)?.stages ?? [];
  return stages
    .filter((stage) => stage.outcome === "lost")
    .sort((a, b) => Number(b.key === "lost") - Number(a.key === "lost"));
}
