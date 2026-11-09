/**
 * Jedna lista kandydatów (`SINGLE_CANDIDATE_LIST_ENABLED`, 08.11.2026): filtry
 * zamiast zakładek. Stare adresy (`?wintab=postings`, `similar`) i kafle prowadzą
 * dalej na tę samą listę z właściwym filtrem. Reguły:
 * docs/claude/rekrutacja-tablica/jedna-lista-kandydatow.md.
 */

import type { ProposalListFilter } from "@/lib/job-proposals-api";
import type { ProposalEntry } from "@/lib/proposals-merge";
import { PROPOSAL_SOURCE_LABEL, type CandidateWindowTab } from "@/components/v2/recruitment/types";

export const SINGLE_LIST_FILTERS: readonly { key: ProposalListFilter; label: string }[] = [
  { key: "all", label: "Wszyscy" },
  { key: "applied", label: "Zgłosili się" },
  { key: "new_in_base", label: "Nowi w bazie" },
  { key: "portal", label: "Z portali" },
  { key: "similar", label: "Podobne" },
  { key: "known", label: "Znamy" },
];

/** Zakładki okna, które przy jednej liście są jej filtrami. */
export function isSingleListTab(tab: CandidateWindowTab): boolean {
  return tab === "base" || tab === "postings" || tab === "similar";
}

/** Filtr wynikający z adresu; „Propozycje z bazy” niesie wybór z panelu. */
export function filterOfTab(
  tab: CandidateWindowTab,
  panelFilter: ProposalListFilter,
): ProposalListFilter {
  if (tab === "postings") return "portal";
  if (tab === "similar") return "similar";
  return panelFilter;
}

export function tabOfFilter(filter: ProposalListFilter): CandidateWindowTab {
  if (filter === "portal") return "postings";
  if (filter === "similar") return "similar";
  return "base";
}

/**
 * Plakietki wiersza: skąd osoba jest. „Nowy · N dni” rysuje wiersz sam, a przy
 * osobie spoza skrzynki (żywy przegląd, podobne projekty) czytamy same źródła.
 */
export function singleListBadges({ row, detail }: ProposalEntry): string[] {
  const out: string[] = [];
  const labels = detail.labels ?? [];
  if (labels.includes("applied")) out.push("Zgłosił(a) się");
  if (labels.includes("portal")) out.push(row.sources.includes("job_board") ? "Z portalu" : "Nowe CV");
  if (row.sources.includes("reassign")) out.push(PROPOSAL_SOURCE_LABEL.reassign);
  else if (labels.includes("similar") || row.sources.includes("similar_projects")) out.push("Podobna");
  if (row.sources.includes("trainee")) out.push(PROPOSAL_SOURCE_LABEL.trainee);
  if (row.sources.includes("recommendation")) out.push(PROPOSAL_SOURCE_LABEL.recommendation);
  if (labels.includes("known")) out.push("Znamy");
  if (out.length === 0 && row.sources.includes("full_base")) out.push("Z bazy");
  return out;
}
