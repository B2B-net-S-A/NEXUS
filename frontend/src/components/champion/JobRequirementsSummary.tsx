"use client";

/**
 * Wymagania rekrutacji — zakładka „Wymagania” podglądu w panelu osoby
 * (0424, 07.10.2026; lista ze zdaniem „po ludzku” od 09.10.2026, D5).
 *
 * Te same dane co „Czego szukamy” i „Warunki” w Briefie Championa
 * (`ChampionBriefView`): profil spod klucza edytora
 * (`["champion-profile", jobId]`), budżet „od–do” z rekrutacji w cache strony
 * (`["job", id]`, bez własnego zapytania). Tylko odczyt — rekruter ma je przed
 * oczami w trakcie rozmowy.
 *
 * Każde wymaganie to wiersz: nazwa, pod nią jedno zdanie ze słowniczka
 * (`usePlainBrief().glossary`, tylko gotowe hasła) i „Szukaj w CV”. Wymaganie
 * bez gotowego hasła pokazuje samą nazwę. W szerokiej strefie warunki
 * rekrutacji stoją obok listy, w wąskiej — pod nią.
 */

import type { ReactNode } from "react";
import { Search, Star } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EMPTY_CHAMPION_PROFILE, type ChampionProfile } from "@/lib/api";
import { usePlainBrief, type GlossaryTerm } from "@/lib/api/plainKnowledge";
import { useCachedJob } from "@/lib/cached-job";
import { JOB_WORK_MODE_LABEL, seedChampionFromJob } from "@/lib/champion-job-seed";
import { criticalBriefLine, includesLabel } from "@/lib/critical-skills";
import { formatBudgetHourly, formatJobBudgetLabel, type JobBudgetSource } from "@/lib/job-budget";
import { officeDaysLabel } from "@/lib/office-days";
import { buildGlossaryLookup, glossaryKey } from "@/lib/plain-glossary-lookup";
import { resolveViewState } from "@/lib/view-state";

import { stackNames } from "./BriefParts";
import { ExperienceChips, useChampionProfile } from "./ChampionBriefForRecruiters";

function Eyebrow({ children }: { children: string }) {
  return <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</p>;
}

function RequirementRow({
  name,
  term,
  critical,
  onPick,
}: {
  name: string;
  term: GlossaryTerm | undefined;
  critical: boolean;
  onPick?: (name: string) => void;
}) {
  return (
    <li
      className="flex items-start gap-3 rounded-lg border border-border bg-card px-3 py-2.5"
      data-critical={critical || undefined}
      data-glossary={term?.term_key}
    >
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-1.5 text-[15px] font-semibold leading-snug text-foreground">
          {critical ? <Star className="h-3.5 w-3.5 shrink-0 fill-primary text-primary" aria-hidden /> : null}
          <span className="min-w-0 break-words">{name}</span>
          {critical ? <span className="sr-only"> — krytyczna</span> : null}
        </p>
        {term ? <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{term.summary}</p> : null}
      </div>
      {onPick ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="shrink-0"
          aria-label={`Szukaj „${name}” w CV`}
          onClick={() => onPick(name)}
        >
          <Search className="h-3.5 w-3.5" aria-hidden /> Szukaj w CV
        </Button>
      ) : null}
    </li>
  );
}

function RequirementGroup({
  title,
  hint,
  items,
  critical,
  glossary,
  onPick,
}: {
  title: string;
  hint?: string | null;
  items: string[];
  critical: boolean;
  glossary: Map<string, GlossaryTerm>;
  onPick?: (name: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Eyebrow>{title}</Eyebrow>
      {items.length > 0 ? (
        <ul className="space-y-1.5">
          {items.map((name) => (
            <RequirementRow
              key={name}
              name={name}
              term={glossary.get(glossaryKey(name))}
              critical={critical}
              onPick={onPick}
            />
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted-foreground">— brak</p>
      )}
      {hint ? <p className="text-[12px] text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Condition({ label, value, muted = false }: { label: string; value: ReactNode; muted?: boolean }) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-2 py-1.5">
      <dt className="text-[13px] text-muted-foreground">{label}</dt>
      <dd className={muted ? "text-sm text-muted-foreground" : "text-sm font-medium text-foreground"}>{value}</dd>
    </div>
  );
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

  const criticalNames = critical?.effective ?? [];
  const mustCritical = must.filter((name) => includesLabel(criticalNames, name));
  const mustOther = must.filter((name) => !includesLabel(criticalNames, name));

  return (
    <div className="@container" data-testid="job-requirements-summary">
      <div className="grid gap-5 @2xl:grid-cols-[minmax(0,1fr)_17rem]">
        <section aria-label="Czego szukamy" className="space-y-4">
          {mustCritical.length > 0 ? (
            <RequirementGroup
              title="Krytyczne"
              // Wybór Delivery Leada widać na liście; zdanie zostaje tylko dla
              // podpowiedzi z historii („Nie zdecydowano…”).
              hint={critical?.decided ? null : criticalLine}
              items={mustCritical}
              critical
              glossary={glossary}
              onPick={onPickRequirement}
            />
          ) : null}
          {/* Gdy wszystkie „musi mieć” są krytyczne, pusta grupa „— brak”
              mówiłaby coś odwrotnego. */}
          {mustOther.length > 0 || mustCritical.length === 0 ? (
            <RequirementGroup
              title="Musi mieć"
              hint={mustCritical.length === 0 ? criticalLine : null}
              items={mustOther}
              critical={false}
              glossary={glossary}
              onPick={onPickRequirement}
            />
          ) : null}
          <RequirementGroup
            title="Mile widziane"
            items={nice}
            critical={false}
            glossary={glossary}
            onPick={onPickRequirement}
          />
          <ExperienceChips experience={profile.experience} />
          {profile.stack?.notes?.trim() ? (
            <p className="text-sm text-muted-foreground">Niuanse: {profile.stack.notes}</p>
          ) : null}
        </section>
        <section aria-label="Warunki rekrutacji" className="space-y-1.5">
          <Eyebrow>Warunki rekrutacji</Eyebrow>
          <dl className="divide-y divide-border/60 rounded-lg border border-border bg-card px-3">
            <Condition label="Budżet" value={budget ?? "nie podano"} muted={!budget} />
            <Condition
              label="Lokalizacja"
              value={basics.candidate_location_pref?.trim() || "nie podano"}
              muted={!basics.candidate_location_pref?.trim()}
            />
            <Condition label="Tryb pracy" value={workMode ?? "nie podano"} muted={!workMode} />
            <Condition label="Dni w biurze" value={office ?? "nie podano"} muted={!office} />
            <Condition label="Start" value={basics.start_date?.trim() || "nie podano"} muted={!basics.start_date} />
            <Condition
              label="Długość"
              value={basics.contract_length?.trim() || "nie podano"}
              muted={!basics.contract_length}
            />
            <Condition
              label="Doświadczenie"
              value={basics.seniority_min_years != null ? `${basics.seniority_min_years}+ lat` : "nie podano"}
              muted={basics.seniority_min_years == null}
            />
            <Condition label="Język pracy" value={basics.language?.trim() || "nie podano"} muted={!basics.language} />
          </dl>
        </section>
      </div>
    </div>
  );
}
