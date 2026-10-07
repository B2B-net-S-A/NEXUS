"use client";

/**
 * Wymagania rekrutacji w skrócie — zakładka „Wymagania” podglądu obok
 * formularza screeningu (0424, 07.10.2026).
 *
 * Te same dane i ten sam wygląd co „Czego szukamy” i „Warunki” w Briefie
 * Championa (`ChampionBriefView`): profil spod klucza edytora
 * (`["champion-profile", jobId]`), budżet „od–do” z rekrutacji w cache strony
 * (`["job", id]`, bez własnego zapytania). Tylko odczyt — rekruter ma je przed
 * oczami w trakcie rozmowy. Klik w chip technologii szuka jej w CV obok.
 */

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Skeleton } from "@/components/ui/skeleton";
import { TooltipProvider } from "@/components/ui/tooltip";
import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import { usePlainBrief } from "@/lib/api/plainKnowledge";
import { useCachedJob } from "@/lib/cached-job";
import { JOB_WORK_MODE_LABEL, seedChampionFromJob } from "@/lib/champion-job-seed";
import { criticalBriefLine } from "@/lib/critical-skills";
import { formatBudgetHourly, formatJobBudgetLabel, type JobBudgetSource } from "@/lib/job-budget";
import { officeDaysLabel } from "@/lib/office-days";
import { buildGlossaryLookup } from "@/lib/plain-glossary-lookup";
import { resolveViewState } from "@/lib/view-state";

import { Chips, Fact, stackNames } from "./BriefParts";
import { ExperienceChips, useChampionProfile } from "./ChampionBriefForRecruiters";

function Eyebrow({ children }: { children: string }) {
  return <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</p>;
}

export interface JobRequirementsSummaryProps {
  jobId: number;
  /** Budżet PLN/h z Tablicy — gdy rekrutacji nie ma w cache strony. */
  budgetHourly?: number | null;
  /** Klik w chip technologii (np. „szukaj w CV”). */
  onPickRequirement?: (name: string) => void;
}

export function JobRequirementsSummary({ jobId, budgetHourly = null, onPickRequirement }: JobRequirementsSummaryProps) {
  const query = useChampionProfile(jobId);
  const plainQuery = usePlainBrief(jobId);
  const job = useCachedJob<JobBudgetSource>(jobId);
  const glossary = buildGlossaryLookup(plainQuery.data?.glossary);

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading") {
    return (
      <div className="space-y-2" aria-busy="true">
        <Skeleton className="h-24 w-full rounded-xl" />
        <Skeleton className="h-32 w-full rounded-xl" />
      </div>
    );
  }
  if (state !== "ready" && state !== "empty") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }

  const profile: Partial<ChampionProfile> = query.data
    ? seedChampionFromJob(
        { ...EMPTY_CHAMPION_PROFILE, ...(query.data.champion_profile as Partial<ChampionProfile>) },
        query.data.job_values,
        query.data.job_title,
      ).profile
    : {};
  const basics = profile.basics ?? {};
  const must = stackNames(profile.stack?.must);
  const nice = stackNames(profile.stack?.nice);
  const critical = query.data?.critical_resolution ?? null;
  const criticalLine = criticalBriefLine(critical);
  const workMode = basics.work_mode ? (JOB_WORK_MODE_LABEL[basics.work_mode] ?? basics.work_mode) : null;
  const office = basics.onsite_days_per_month
    ? `${officeDaysLabel(null, basics.onsite_days_per_month)} w biurze`
    : basics.onsite_days_per_week
      ? `${basics.onsite_days_per_week} dni w biurze`
      : null;
  const budget =
    formatJobBudgetLabel(job) ??
    (basics.rate_value != null
      ? `do ${formatBudgetHourly(basics.rate_value)} PLN/h`
      : budgetHourly != null
        ? `do ${formatBudgetHourly(budgetHourly)} PLN/h`
        : null);

  return (
    <TooltipProvider delayDuration={150}>
      <div className="space-y-4" data-testid="job-requirements-summary">
        <section aria-label="Czego szukamy" className="space-y-2.5">
          <div className="space-y-1.5">
            <Eyebrow>Musi mieć</Eyebrow>
            {must.length > 0 ? (
              <Chips
                items={must}
                tone="must"
                critical={critical?.effective ?? []}
                glossary={glossary}
                onPick={onPickRequirement}
              />
            ) : (
              <p className="text-[13px] text-muted-foreground">— brak</p>
            )}
            {criticalLine ? <p className="text-[12px] text-muted-foreground">{criticalLine}</p> : null}
          </div>
          <div className="space-y-1.5">
            <Eyebrow>Mile widziane</Eyebrow>
            {nice.length > 0 ? (
              <Chips items={nice} tone="nice" glossary={glossary} onPick={onPickRequirement} />
            ) : (
              <p className="text-[13px] text-muted-foreground">— brak</p>
            )}
          </div>
          <ExperienceChips experience={profile.experience} />
          {profile.stack?.notes?.trim() ? (
            <p className="text-[13px] text-muted-foreground">Niuanse: {profile.stack.notes}</p>
          ) : null}
        </section>
        <section aria-label="Warunki rekrutacji">
          <dl className="divide-y divide-border/60">
            <Fact label="Budżet" value={budget ?? "nie podano"} muted={!budget} />
            <Fact
              label="Lokalizacja"
              value={basics.candidate_location_pref?.trim() || "nie podano"}
              muted={!basics.candidate_location_pref?.trim()}
            />
            <Fact label="Tryb pracy" value={workMode ?? "nie podano"} muted={!workMode} />
            <Fact label="Dni w biurze" value={office ?? "nie podano"} muted={!office} />
            <Fact label="Start" value={basics.start_date?.trim() || "nie podano"} muted={!basics.start_date} />
            <Fact label="Długość" value={basics.contract_length?.trim() || "nie podano"} muted={!basics.contract_length} />
            <Fact
              label="Doświadczenie"
              value={basics.seniority_min_years != null ? `${basics.seniority_min_years}+ lat` : "nie podano"}
              muted={basics.seniority_min_years == null}
            />
            <Fact label="Język pracy" value={basics.language?.trim() || "nie podano"} muted={!basics.language} />
          </dl>
        </section>
      </div>
    </TooltipProvider>
  );
}
