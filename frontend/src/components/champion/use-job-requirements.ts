"use client";

/**
 * Wymagania i warunki rekrutacji do podglądu w panelu osoby — jedno liczenie
 * dla listy „Wymagania” (`JobRequirementsSummary`) i paska nad CV
 * (`JobRequirementsStrip`, 13.10.2026).
 *
 * Te same dane co „Czego szukamy” i „Warunki” w Briefie Championa: profil spod
 * klucza edytora (`["champion-profile", jobId]`), budżet „od–do” z rekrutacji
 * w cache strony (`["job", id]`, bez własnego zapytania). Lista i pasek
 * używają tych samych kluczy, więc razem robią jedno żądanie.
 */

import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import { useCachedJob } from "@/lib/cached-job";
import { JOB_WORK_MODE_LABEL, seedChampionFromJob } from "@/lib/champion-job-seed";
import { criticalBriefLine, includesLabel, type CriticalResolution } from "@/lib/critical-skills";
import { formatBudgetHourly, formatJobBudgetLabel, type JobBudgetSource } from "@/lib/job-budget";
import { officeDaysLabel, officeDaysShort } from "@/lib/office-days";
import { resolveViewState, type ViewState } from "@/lib/view-state";

import { stackNames } from "./BriefParts";
import { useChampionProfile } from "./ChampionBriefForRecruiters";

/** Warunki rekrutacji; `null` = nie podano. */
export interface JobRequirementConditions {
  budget: string | null;
  location: string | null;
  workMode: string | null;
  /** „2 dni w biurze” / „2 dni w miesiącu w biurze” — lista warunków. */
  office: string | null;
  /** „2 dni/tydz.” — pasek nad CV. */
  officeShort: string | null;
  start: string | null;
  length: string | null;
  /** „5+ lat”. */
  seniority: string | null;
  language: string | null;
}

export interface JobRequirements {
  mustCritical: string[];
  mustOther: string[];
  nice: string[];
  critical: CriticalResolution | null;
  /** Zdanie o krytycznych („Nie zdecydowano…”) — tylko gdy DL jeszcze nie wybrał. */
  criticalLine: string | null;
  experience: ChampionProfile["experience"] | undefined;
  notes: string;
  conditions: JobRequirementConditions;
  /** Słowa lupy „Szukaj w CV” z serwera (`requirement_find_words`). */
  findWords: Readonly<Record<string, readonly string[]>>;
}

/**
 * Słowa, których „Szukaj w CV” szuka dla wymagania (16.10.2026): „.NET lub
 * C#” → „.NET”, „C#” i warianty nazw. Pusta lista = lupa szuka samej nazwy.
 */
export function requirementFindWords(
  findWords: JobRequirements["findWords"],
  name: string,
): readonly string[] {
  const exact = findWords[name];
  if (exact) return exact;
  const key = name.trim().toLocaleLowerCase("pl");
  const match = Object.entries(findWords).find(
    ([label]) => label.trim().toLocaleLowerCase("pl") === key,
  );
  return match ? match[1] : [];
}

function findWordsFromResponse(raw: unknown): Record<string, string[]> {
  if (!raw || typeof raw !== "object") return {};
  return Object.fromEntries(
    Object.entries(raw as Record<string, unknown>)
      .filter((entry): entry is [string, unknown[]] => Array.isArray(entry[1]))
      .map(([label, words]) => [label, words.filter((w): w is string => typeof w === "string")]),
  );
}

/**
 * Same słowa lupy — przegląd DL (23.10.2026) nie potrzebuje reszty wymagań.
 * Ten sam klucz co `useJobRequirements`, więc bez drugiego żądania.
 */
export function useRequirementFindWords(jobId: number): JobRequirements["findWords"] {
  const query = useChampionProfile(jobId);
  return findWordsFromResponse(query.data?.requirement_find_words);
}

export interface JobRequirementsQuery {
  state: ViewState;
  refetch: () => void;
  requirements: JobRequirements;
}

function text(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

export function useJobRequirements(jobId: number, budgetHourly: number | null = null): JobRequirementsQuery {
  const query = useChampionProfile(jobId);
  const job = useCachedJob<JobBudgetSource>(jobId);

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });

  const profile: Partial<ChampionProfile> = query.data
    ? seedChampionFromJob(
        { ...EMPTY_CHAMPION_PROFILE, ...(query.data.champion_profile as Partial<ChampionProfile>) },
        query.data.job_values,
        query.data.job_title,
      ).profile
    : {};
  const basics = profile.basics ?? {};
  const must = stackNames(profile.stack?.must);
  const critical = (query.data?.critical_resolution as CriticalResolution | null | undefined) ?? null;
  const criticalNames = critical?.effective ?? [];

  const workMode = basics.work_mode ? (JOB_WORK_MODE_LABEL[basics.work_mode] ?? basics.work_mode) : null;
  const office = basics.onsite_days_per_month
    ? `${officeDaysLabel(null, basics.onsite_days_per_month)} w biurze`
    : basics.onsite_days_per_week
      ? `${basics.onsite_days_per_week} dni w biurze`
      : null;
  const officeShort =
    basics.onsite_days_per_month || basics.onsite_days_per_week
      ? officeDaysShort(basics.onsite_days_per_week || null, basics.onsite_days_per_month || null)
      : null;
  const budget =
    formatJobBudgetLabel(job) ??
    (basics.rate_value != null
      ? `do ${formatBudgetHourly(basics.rate_value)} PLN/h`
      : budgetHourly != null
        ? `do ${formatBudgetHourly(budgetHourly)} PLN/h`
        : null);

  return {
    state,
    refetch: () => void query.refetch(),
    requirements: {
      mustCritical: must.filter((name) => includesLabel(criticalNames, name)),
      mustOther: must.filter((name) => !includesLabel(criticalNames, name)),
      nice: stackNames(profile.stack?.nice),
      critical,
      criticalLine: criticalBriefLine(critical),
      experience: profile.experience,
      notes: profile.stack?.notes?.trim() ?? "",
      conditions: {
        budget,
        location: text(basics.candidate_location_pref),
        workMode,
        office,
        officeShort,
        start: text(basics.start_date),
        length: text(basics.contract_length),
        seniority: basics.seniority_min_years != null ? `${basics.seniority_min_years}+ lat` : null,
        language: text(basics.language),
      },
      findWords: findWordsFromResponse(query.data?.requirement_find_words),
    },
  };
}
