"use client";

/**
 * Zakładka „Podobni” (22.10.2026, makiety https://claude.ai/artifact/VufQ5HYPcK59YZ5ZjgdCKs).
 *
 * Osoby z podobnym CV i umiejętnościami — kolejność bez żadnej rekrutacji
 * (podobny ≠ pasujący, decyzja Artura). „Sprawdź pod rekrutację” tylko
 * nakłada wynik umiejętności krytycznych na wiersze, kolejności nie zmienia.
 * „Porównaj” otwiera dwie kolumny obok siebie, „Przypisz” — okno z
 * rekrutacjami osoby z profilu i moimi, ze sprawdzeniem i zdaniem przy braku
 * krytycznej. Bez licznika na zakładce: liczba wymagałaby zapytania przy
 * każdym otwarciu profilu.
 */

import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleSlash, GitCompare, UserPlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AvailabilityPill } from "@/components/ds/AvailabilityPill";
import { getCandidateInitials } from "@/components/v2/pages/candidate-list-helpers";
import { jobsApi, skillsApi } from "@/lib/api";
import { candidateSearchApi } from "@/lib/candidate-search-api";
import {
  DEFAULT_SIMILAR_FILTERS,
  SIMILARITY_LEVEL_LABEL,
  SIMILAR_PAGE_SIZE,
  checkVerdict,
  similarCandidatesApi,
  verdictText,
  type CheckVerdict,
  type SimilarCandidate,
  type SimilarFilters,
} from "@/lib/api/similarCandidates";
import { skillDictionaryIndex } from "@/lib/skill-display";
import {
  checksByCandidate,
  jobLabel,
  mergePickableJobs,
  personName,
  prettySkill,
  rateText,
  sharedSkillsText,
  type PickableJob,
} from "@/lib/similar-candidates-view";
import type { JobNames } from "@/lib/job-names";
import { cn } from "@/lib/utils";

import { SectionError, SectionLoading } from "@/components/v2/candidate-profile/profile-shared";
import { splitRecruitments, type RecruitmentHistoryItem } from "@/components/v2/candidate-profile/profile-helpers";
import { SimilarAssignSheet } from "./SimilarAssignSheet";
import { SimilarCompareSheet } from "./SimilarCompareSheet";

/** Najwięcej osób w jednym przypisaniu — tyle ocenia jedno zapytanie o dopasowanie. */
const BULK_MAX = 20;

interface SimilarCandidatesTabProps {
  candidateId: number;
  candidateName: string;
  /** Rekrutacje osoby z profilu (`/history`) — trafiają na górę wyboru. */
  recruitments: RecruitmentHistoryItem[];
  canWrite: boolean;
}

/** Rekrutacje w toku osoby z profilu — pierwsza grupa wyboru. */
export function sourceRecruitmentJobs(history: RecruitmentHistoryItem[]): PickableJob[] {
  return splitRecruitments(history)
    .active.filter((item) => typeof item.job_id === "number")
    .map((item) => ({
      id: item.job_id as number,
      names: {
        id: item.job_id as number,
        title: (item.job_title as string | null) ?? null,
        working_title: (item.job_working_title as string | null) ?? null,
        client_reference: (item.job_client_reference as string | null) ?? null,
      },
      clientName: (item.client_name as string | null) ?? null,
      group: "source" as const,
    }));
}

interface JobListItem extends JobNames {
  id: number;
  client_name?: string | null;
}

export function useMyOpenJobs(enabled: boolean) {
  // Ten sam klucz co `JobPicker` i okno „Przypisz do rekrutacji” — jedna odpowiedź w cache.
  return useQuery({
    queryKey: ["job-picker", "mine"],
    queryFn: () =>
      jobsApi
        .list({ mine: true, open_only: true, page_size: 20 })
        .then((r) => r.data as { items: JobListItem[] }),
    enabled,
    staleTime: 60_000,
  });
}

export function myJobs(items: JobListItem[] | undefined): PickableJob[] {
  return (items ?? []).map((job) => ({
    id: job.id,
    names: job,
    clientName: job.client_name ?? null,
    group: "mine" as const,
  }));
}

export function useSkillDictionary() {
  const query = useQuery({
    queryKey: ["skills-dictionary", 500],
    queryFn: () => skillsApi.list(500).then((r) => r.data.items),
    staleTime: 60 * 60 * 1000,
    retry: false,
  });
  return useMemo(() => skillDictionaryIndex(query.data), [query.data]);
}

export function SimilarCandidatesTab({
  candidateId,
  candidateName,
  recruitments,
  canWrite,
}: SimilarCandidatesTabProps) {
  const [filters, setFilters] = useState<SimilarFilters>(DEFAULT_SIMILAR_FILTERS);
  const [rateDraft, setRateDraft] = useState("");
  const [cityDraft, setCityDraft] = useState("");
  const [checkJobId, setCheckJobId] = useState<number | null>(null);
  const [onlyMeeting, setOnlyMeeting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [compareId, setCompareId] = useState<number | null>(null);
  const [assignIds, setAssignIds] = useState<number[] | null>(null);
  const dictionary = useSkillDictionary();
  // Zaznaczenie dotyczy wczytanej listy — po zmianie filtrów osoby mogą z niej
  // zniknąć, a „Przypisz zaznaczonych” nie może po cichu wziąć mniej osób.
  useEffect(() => setSelected(new Set()), [filters]);

  const listQuery = useInfiniteQuery({
    queryKey: ["candidate-similar", candidateId, filters],
    queryFn: ({ pageParam, signal }) =>
      similarCandidatesApi.list(candidateId, filters, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return last.status === "ok" && loaded < last.total ? loaded : undefined;
    },
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });
  const first = listQuery.data?.pages[0];
  const items = useMemo(
    () => (listQuery.data?.pages ?? []).flatMap((p) => p.items),
    [listQuery.data],
  );

  const mineQuery = useMyOpenJobs(true);
  const pickable = useMemo(
    () => mergePickableJobs(sourceRecruitmentJobs(recruitments), myJobs(mineQuery.data?.items)),
    [recruitments, mineQuery.data],
  );
  const checkJob = pickable.find((job) => job.id === checkJobId) ?? null;

  const visibleIds = useMemo(() => items.map((c) => c.id), [items]);
  const checkQuery = useQuery({
    queryKey: ["candidate-similar-check", candidateId, checkJobId, visibleIds],
    queryFn: async () => {
      const chunks: number[][] = [];
      for (let i = 0; i < visibleIds.length; i += SIMILAR_PAGE_SIZE) {
        chunks.push(visibleIds.slice(i, i + SIMILAR_PAGE_SIZE));
      }
      const parts = await Promise.all(
        chunks.map((ids) => similarCandidatesApi.check(candidateId, [checkJobId as number], ids)),
      );
      return checksByCandidate({
        job_id: checkJobId as number,
        critical_labels: parts[0]?.[0]?.critical_labels ?? [],
        candidates: parts.flatMap((p) => p[0]?.candidates ?? []),
      });
    },
    enabled: checkJobId != null && visibleIds.length > 0,
    staleTime: 60_000,
  });
  const scoresQuery = useQuery({
    queryKey: ["candidate-similar-scores", checkJobId, visibleIds],
    queryFn: async () => {
      const out = new Map<number, number>();
      for (let i = 0; i < visibleIds.length; i += SIMILAR_PAGE_SIZE) {
        const res = await candidateSearchApi.matchScores(
          checkJobId as number,
          visibleIds.slice(i, i + SIMILAR_PAGE_SIZE),
        );
        for (const [id, score] of Object.entries(res.scores)) out.set(Number(id), score);
      }
      return out;
    },
    enabled: checkJobId != null && visibleIds.length > 0,
    staleTime: 60_000,
    retry: false,
  });
  const criticalLabels = useMemo(() => {
    const first = checkQuery.data ? [...checkQuery.data.values()][0] : undefined;
    return first?.critical.map((c) => c.label) ?? [];
  }, [checkQuery.data]);

  // „Tylko spełniający” działa wyłącznie na udanym sprawdzeniu rekrutacji
  // z krytycznymi — bez wyniku nie udaje przefiltrowanej listy.
  const canFilterMeeting = checkQuery.isSuccess && criticalLabels.length > 0;
  const rows = useMemo(() => {
    if (!onlyMeeting || !canFilterMeeting || !checkQuery.data) return items;
    return items.filter((c) => checkVerdict(checkQuery.data.get(c.id))?.kind === "met");
  }, [items, onlyMeeting, canFilterMeeting, checkQuery.data]);

  const toggle = (id: number, on: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const applyRate = () => {
    const value = Number(rateDraft.replace(",", "."));
    setFilters((f) => ({ ...f, rateMax: Number.isFinite(value) && value > 0 ? value : null }));
  };
  const applyCity = () => setFilters((f) => ({ ...f, city: cityDraft }));

  const compareIndex = compareId == null ? -1 : items.findIndex((c) => c.id === compareId);
  const assignPeople = useMemo(
    () => (assignIds ?? []).map((id) => items.find((c) => c.id === id)).filter(Boolean) as SimilarCandidate[],
    [assignIds, items],
  );

  return (
    <section aria-label="Podobni kandydaci" className="space-y-3" data-help="candidate.profile.similar">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1 text-sm text-muted-foreground">
          Osoby z podobnym CV i umiejętnościami co {candidateName} — kolejność nie zależy od żadnej
          rekrutacji.
        </p>
        <div className="flex items-center gap-2">
          <label htmlFor="similar-check-job" className="text-xs font-medium text-muted-foreground">
            Sprawdź pod rekrutację
          </label>
          <Select
            value={checkJobId == null ? "none" : String(checkJobId)}
            onValueChange={(value) => {
              setCheckJobId(value === "none" ? null : Number(value));
              setOnlyMeeting(false);
            }}
          >
            <SelectTrigger id="similar-check-job" className="h-9 w-64 max-w-full [&>span]:truncate">
              <SelectValue placeholder="Nie sprawdzaj" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">Nie sprawdzaj</SelectItem>
              {(["source", "mine"] as const).map((group) => {
                const jobs = pickable.filter((job) => job.group === group);
                if (jobs.length === 0) return null;
                return (
                  <SelectGroup key={group}>
                    <SelectLabel>
                      {group === "source" ? `Rekrutacje: ${candidateName}` : "Moje otwarte"}
                    </SelectLabel>
                    {jobs.map((job) => (
                      <SelectItem key={job.id} value={String(job.id)}>
                        {jobLabel(job)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                );
              })}
            </SelectContent>
          </Select>
        </div>
      </div>

      {checkJob ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-primary/25 bg-primary/5 px-3 py-2 text-xs">
          <span className="font-medium text-foreground">{jobLabel(checkJob)}</span>
          <span className="text-muted-foreground">
            {criticalLabels.length > 0
              ? `Krytyczne: ${criticalLabels.join(", ")}`
              : checkQuery.isSuccess
                ? "Rekrutacja nie ma umiejętności krytycznych"
                : checkQuery.isError
                  ? null
                  : "Sprawdzam…"}
          </span>
          <span className="text-muted-foreground">Kolejność bez zmian — najbardziej podobni na górze.</span>
        </div>
      ) : null}
      {checkJob && checkQuery.isError ? (
        <SectionError
          title="Nie udało się sprawdzić umiejętności krytycznych tej rekrutacji."
          onRetry={() => void checkQuery.refetch()}
        />
      ) : null}

      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filtry podobnych">
        <FilterToggle
          on={filters.hideNotLooking}
          onChange={(on) => setFilters((f) => ({ ...f, hideNotLooking: on }))}
        >
          Bez „Nie szuka”
        </FilterToggle>
        <FilterToggle
          on={filters.withoutProcess}
          onChange={(on) => setFilters((f) => ({ ...f, withoutProcess: on }))}
        >
          Bez osób w procesie
        </FilterToggle>
        {canFilterMeeting ? (
          <FilterToggle on={onlyMeeting} onChange={setOnlyMeeting}>
            Tylko spełniający krytyczne
          </FilterToggle>
        ) : null}
        <form
          className="flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            applyRate();
          }}
        >
          <label htmlFor="similar-rate-max" className="sr-only">
            Stawka do (zł/h)
          </label>
          <Input
            id="similar-rate-max"
            inputMode="decimal"
            placeholder="Stawka do, zł/h"
            value={rateDraft}
            onChange={(e) => setRateDraft(e.target.value)}
            onBlur={applyRate}
            className="h-9 w-36"
          />
        </form>
        <form
          className="flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            applyCity();
          }}
        >
          <label htmlFor="similar-city" className="sr-only">
            Miasto
          </label>
          <Input
            id="similar-city"
            placeholder="Miasto"
            value={cityDraft}
            onChange={(e) => setCityDraft(e.target.value)}
            onBlur={applyCity}
            className="h-9 w-32"
          />
        </form>
        {first?.status === "ok" ? (
          <span className="ml-auto text-xs text-muted-foreground">
            {first.total === 1 ? "1 osoba" : `${first.total} osób`} · najbardziej podobni na górze
          </span>
        ) : null}
      </div>

      {listQuery.isPending ? (
        <SectionLoading label="Szukam podobnych osób…" />
      ) : listQuery.isError ? (
        <SectionError
          title="Nie udało się pobrać podobnych osób."
          onRetry={() => void listQuery.refetch()}
        />
      ) : first?.status === "unavailable" ? (
        <SectionError
          title="Wyszukiwarka podobnych chwilowo nie odpowiada — to nie znaczy, że nikogo nie ma."
          onRetry={() => void listQuery.refetch()}
        />
      ) : first?.status === "no_vector" ? (
        <p className="rounded-lg border border-border bg-muted/30 px-4 py-6 text-sm text-muted-foreground">
          Ta osoba nie ma jeszcze przeczytanego CV, a podobnych szukamy po CV i umiejętnościach.
          Wróć tu po wgraniu CV.
        </p>
      ) : listQuery.isSuccess && rows.length === 0 ? (
        <p className="rounded-lg border border-border bg-muted/30 px-4 py-6 text-sm text-muted-foreground">
          {onlyMeeting
            ? "Na wczytanej liście nikt nie spełnia umiejętności krytycznych tej rekrutacji."
            : "Nikt nie pasuje do filtrów. Zdejmij któryś, żeby zobaczyć więcej osób."}
        </p>
      ) : (
        <div className="@container overflow-hidden rounded-lg border border-border">
          <div
            aria-hidden
            className="hidden grid-cols-[1.25rem_minmax(0,1fr)_9rem_8rem_12.5rem] items-center gap-3 bg-muted/40 px-3 py-2 text-[11px] font-medium text-muted-foreground @2xl:grid"
          >
            <span />
            <span>Kandydat</span>
            <span>Podobieństwo</span>
            <span>Stawka · dostępność</span>
            <span />
          </div>
          <ul className="divide-y divide-border">
            {rows.map((person) => (
              <SimilarRow
                key={person.id}
                person={person}
                dictionary={dictionary}
                selected={selected.has(person.id)}
                onSelect={(on) => toggle(person.id, on)}
                selectDisabled={!selected.has(person.id) && selected.size >= BULK_MAX}
                verdict={checkJobId != null ? checkVerdict(checkQuery.data?.get(person.id)) : null}
                checking={checkJobId != null && checkQuery.isPending}
                score={scoresQuery.data?.get(person.id)}
                onCompare={() => setCompareId(person.id)}
                onAssign={canWrite ? () => setAssignIds([person.id]) : undefined}
              />
            ))}
          </ul>
        </div>
      )}

      {listQuery.hasNextPage ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() => void listQuery.fetchNextPage()}
          loading={listQuery.isFetchingNextPage}
        >
          Pokaż kolejnych
        </Button>
      ) : null}

      {selected.size > 0 ? (
        <div className="sticky bottom-2 z-10 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/30 bg-card px-3 py-2 shadow-sm">
          <span className="text-sm font-medium text-foreground">
            Zaznaczono {selected.size}
            {selected.size >= BULK_MAX ? ` (najwyżej ${BULK_MAX} naraz)` : ""}
          </span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => setSelected(new Set())}>
              Odznacz
            </Button>
            {canWrite ? (
              <Button size="sm" onClick={() => setAssignIds([...selected])}>
                Przypisz zaznaczonych do rekrutacji…
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {first && compareIndex >= 0 ? (
        <SimilarCompareSheet
          source={first.source}
          person={items[compareIndex]}
          position={compareIndex}
          total={items.length}
          dictionary={dictionary}
          onPrev={compareIndex > 0 ? () => setCompareId(items[compareIndex - 1].id) : undefined}
          onNext={
            compareIndex < items.length - 1 ? () => setCompareId(items[compareIndex + 1].id) : undefined
          }
          onClose={() => setCompareId(null)}
          onAssign={
            canWrite
              ? () => {
                  setAssignIds([items[compareIndex].id]);
                  setCompareId(null);
                }
              : undefined
          }
        />
      ) : null}

      {assignPeople.length > 0 ? (
        <SimilarAssignSheet
          sourceCandidateId={candidateId}
          sourceName={candidateName}
          people={assignPeople}
          sourceJobs={sourceRecruitmentJobs(recruitments)}
          myJobs={myJobs(mineQuery.data?.items)}
          initialJobId={checkJobId}
          onClose={() => setAssignIds(null)}
          onAdded={(ids) =>
            setSelected((prev) => {
              const next = new Set(prev);
              for (const id of ids) next.delete(id);
              return next;
            })
          }
        />
      ) : null}
    </section>
  );
}

function FilterToggle({
  on,
  onChange,
  children,
}: {
  on: boolean;
  onChange: (on: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={() => onChange(!on)}
      className={cn(
        "inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors",
        on
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-border bg-card text-foreground hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

const VERDICT_TONE: Record<CheckVerdict["kind"], string> = {
  met: "text-success-muted-foreground",
  missing: "text-warning-muted-foreground",
  in_job: "text-muted-foreground",
  no_critical: "text-muted-foreground",
};

function VerdictLine({ verdict, score }: { verdict: CheckVerdict; score?: number }) {
  const Icon =
    verdict.kind === "met" ? CheckCircle2 : verdict.kind === "missing" ? AlertTriangle : CircleSlash;
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1 text-xs font-medium", VERDICT_TONE[verdict.kind])}>
      <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 truncate">
        {verdictText(verdict)}
        {typeof score === "number" ? ` · dopasowanie ${Math.round(score)}%` : ""}
      </span>
    </span>
  );
}

function SimilarRow({
  person,
  dictionary,
  selected,
  onSelect,
  selectDisabled,
  verdict,
  checking,
  score,
  onCompare,
  onAssign,
}: {
  person: SimilarCandidate;
  dictionary: Map<string, string>;
  selected: boolean;
  onSelect: (on: boolean) => void;
  selectDisabled: boolean;
  verdict: CheckVerdict | null;
  checking: boolean;
  score?: number;
  onCompare: () => void;
  onAssign?: () => void;
}) {
  const name = personName(person);
  const meta = [
    person.title,
    person.years_it_experience != null ? `${person.years_it_experience} lat` : null,
    person.city,
  ]
    .filter(Boolean)
    .join(" · ");
  const shown = person.shared_skills.slice(0, 3);
  const rest = person.shared_skills.length - shown.length;
  return (
    <li
      className={cn(
        "grid grid-cols-[1.25rem_minmax(0,1fr)] items-start gap-x-3 gap-y-2 px-3 py-2.5 @2xl:grid-cols-[1.25rem_minmax(0,1fr)_9rem_8rem_12.5rem] @2xl:items-center",
        selected && "bg-primary/5",
      )}
    >
      <Checkbox
        checked={selected}
        disabled={selectDisabled}
        onCheckedChange={(value) => onSelect(value === true)}
        aria-label={`Zaznacz: ${name}`}
        className="mt-1 @2xl:mt-0"
      />
      <div className="flex min-w-0 items-start gap-2.5">
        <span
          aria-hidden
          className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10.5px] font-semibold text-primary"
        >
          {getCandidateInitials(person)}
        </span>
        <div className="min-w-0">
          <button
            type="button"
            onClick={onCompare}
            className="max-w-full truncate text-left text-sm font-semibold text-foreground hover:underline"
          >
            {name}
          </button>
          {meta ? <div className="truncate text-xs text-muted-foreground">{meta}</div> : null}
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1">
            {verdict ? (
              <VerdictLine verdict={verdict} score={score} />
            ) : checking ? (
              <span className="text-xs text-muted-foreground">Sprawdzam…</span>
            ) : (
              <>
                {shown.map((skill) => (
                  <span
                    key={skill}
                    className="inline-flex h-5 items-center rounded-md border border-primary/25 bg-primary/5 px-1.5 text-[11px] text-primary"
                  >
                    {prettySkill(skill, dictionary)}
                  </span>
                ))}
                {rest > 0 ? <span className="text-[11px] text-muted-foreground">+{rest}</span> : null}
              </>
            )}
          </div>
        </div>
      </div>
      <div className="col-start-2 text-xs @2xl:col-start-auto">
        <div className="font-semibold text-foreground">{SIMILARITY_LEVEL_LABEL[person.level]}</div>
        <div className="text-muted-foreground">{sharedSkillsText(person.shared_skills.length)}</div>
      </div>
      <div className="col-start-2 flex flex-wrap items-center gap-x-2 text-xs @2xl:col-start-auto @2xl:block">
        <div className="font-medium text-foreground">{rateText(person.rate_hourly, person.rate_currency)}</div>
        <AvailabilityPill status={person.availability_status} appearance="text" />
      </div>
      <div className="col-start-2 flex gap-1.5 @2xl:col-start-auto @2xl:justify-end">
        <Button size="sm" variant="outline" onClick={onCompare}>
          <GitCompare className="h-3.5 w-3.5" aria-hidden />
          Porównaj
        </Button>
        {onAssign ? (
          <Button size="sm" variant="outline" onClick={onAssign}>
            <UserPlus className="h-3.5 w-3.5" aria-hidden />
            Przypisz
          </Button>
        ) : null}
      </div>
    </li>
  );
}
