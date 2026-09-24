/**
 * „Dodaj kandydatów” → Propozycje: fakty zamiast pustych pól.
 *
 * Czyste funkcje nad odpowiedzią `GET /api/jobs/{id}/proposal-facts`
 * (`ProposalFacts`). Zasady:
 *  - czego nie wiemy, tego nie piszemy — żadnych „stawka —”, „—” w środku
 *    zdania ani zer; znany fakt wchodzi, nieznany znika z linii;
 *  - historia u TEGO klienta („Był(a) u tego klienta: … — doszedł(a) do …”)
 *    bije ogólną linię o podobnym projekcie, bo mówi więcej o szansach;
 *  - sortowanie „najpierw byli u tego klienta” jest stabilne — reszta zostaje
 *    w kolejności propozycji (dopasowanie ↓, nowe, nazwisko).
 */

import type { ProposalClientHistory, ProposalFacts } from "@/lib/job-proposals-api";
import { availabilityLabel, formatHourlyRate } from "@/lib/proposals-merge";
import { countPl } from "@/lib/plural-pl";

export function yearsLabel(years: number | null | undefined): string | null {
  if (years == null || !Number.isFinite(years) || years <= 0) return null;
  return `${countPl(Math.round(years), "rok", "lata", "lat")} dośw.`;
}

/** Tryb pracy osoby z dni w biurze i preferencji — tylko to, co wiemy. */
export function workModeLabel(facts: Pick<ProposalFacts, "max_onsite_days_per_week" | "remote_modes">): string | null {
  const days = facts.max_onsite_days_per_week;
  if (days === 0) return "tylko zdalnie";
  if (typeof days === "number" && days > 0) {
    return days >= 5 ? "także w biurze" : `do ${countPl(days, "dnia", "dni", "dni")} w biurze`;
  }
  const modes = new Set(facts.remote_modes ?? []);
  if (modes.size === 1 && modes.has("remote")) return "tylko zdalnie";
  if (modes.has("hybrid")) return "hybrydowo";
  if (modes.has("onsite")) return "stacjonarnie";
  return null;
}

/** Stawka tylko, gdy znana. PLN → „150 zł/h”, inna waluta z kodem. */
export function factsRateLabel(facts: Pick<ProposalFacts, "expected_rate_hourly" | "expected_rate_currency">): string | null {
  const value = facts.expected_rate_hourly;
  if (value == null || !Number.isFinite(value) || value <= 0) return null;
  const currency = (facts.expected_rate_currency ?? "PLN").trim().toUpperCase();
  // „zł”/„ZŁ”/„ZL” z importu to też złotówki.
  const isPln = currency === "PLN" || currency === "ZŁ" || currency === "ZL";
  return isPln ? formatHourlyRate(value) : `${Math.round(value)} ${currency}/h`;
}

/** Linia „Ostatnio: …” — stanowisko, staż, miasto, tryb, dostępność, stawka. */
export function proposalFactsLine(facts: ProposalFacts | null | undefined, now: Date = new Date()): string | null {
  if (!facts) return null;
  const role = facts.title
    ? [facts.title, facts.company ? `@ ${facts.company}` : null].filter(Boolean).join(" ")
    : facts.company ?? "";
  const parts = [
    role || null,
    yearsLabel(facts.years_experience),
    facts.city?.trim() || null,
    workModeLabel(facts),
    availabilityLabel(facts.availability_status, facts.availability_date, now),
    factsRateLabel(facts),
  ].filter((p): p is string => Boolean(p));
  return parts.length > 0 ? parts.join(" · ") : null;
}

const OUTCOME_SUFFIX: Record<string, string> = {
  rejected: " (odrzucony/a)",
  withdrawn: " (zrezygnował/a)",
  in_progress: " (w toku)",
  hired: "",
};

export function clientHistoryLine(history: ProposalClientHistory | null | undefined): string | null {
  if (!history) return null;
  const where = history.title?.trim() || `rekrutacja #${history.job_id}`;
  const suffix = OUTCOME_SUFFIX[history.outcome] ?? "";
  return `Był(a) u tego klienta: ${where} — doszedł(a) do etapu „${history.furthest_stage_label}”${suffix}`;
}

export type ProposalSortMode = "client_first" | "proposals";

/**
 * „Najpierw byli u tego klienta” — osoby z historią u klienta na górę
 * (dalszy etap wyżej), reszta w kolejności wejścia. Stabilne.
 */
export function sortByClientHistory<T extends { candidateId: number }>(
  rows: readonly T[],
  factsById: ReadonlyMap<number, ProposalFacts>,
  rank: (stage: string) => number = defaultStageRank,
): T[] {
  return rows
    .map((row, index) => ({ row, index, history: factsById.get(row.candidateId)?.client_history ?? null }))
    .sort((a, b) => {
      if (Boolean(a.history) !== Boolean(b.history)) return a.history ? -1 : 1;
      if (a.history && b.history) {
        const diff = rank(b.history.furthest_stage) - rank(a.history.furthest_stage);
        if (diff !== 0) return diff;
      }
      return a.index - b.index;
    })
    .map((x) => x.row);
}

const STAGE_ORDER = [
  "posting",
  "new",
  "prep_call",
  "screening",
  "verified",
  "interview",
  "cv_sent",
  "client_interview",
  "acceptance",
  "negotiation",
  "onboarding",
  "hired",
];

function defaultStageRank(stage: string): number {
  return STAGE_ORDER.indexOf(stage);
}
