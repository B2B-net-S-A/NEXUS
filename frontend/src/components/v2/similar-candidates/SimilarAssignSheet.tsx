"use client";

/**
 * „Przypisz” z zakładki „Podobni” (22.10.2026, decyzje Artura): na górze
 * rekrutacje w toku osoby z profilu, potem moje otwarte, niżej wyszukiwarka
 * wszystkich otwartych. Przy każdej rekrutacji wynik sprawdzenia: czy osoba
 * (albo zaznaczeni) spełnia umiejętności krytyczne i czy już jest w tej
 * rekrutacji. Brak krytycznej to ostrzeżenie z powodem, nie blokada — osoba
 * jest domyślnie odznaczona, a zaznaczona wymaga zdania „dlaczego mimo to”,
 * które trafia na kartę jako notatka (serwer pilnuje tego samego, 422).
 */

import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleHelp, Search, XCircle } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { JobPickName } from "@/components/v2/jobs/JobPickName";
import { invalidateCandidateMutation } from "@/components/v2/pages/candidate-cache";
import { jobsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import { candidateSearchApi, proposalsBulkApi } from "@/lib/candidate-search-api";
import {
  SIMILAR_CHECK_MAX_PAIRS,
  checkVerdict,
  criticalSourcesText,
  similarCandidatesApi,
  verdictText,
  type CandidateCheck,
  type JobCheck,
  type SimilarCandidate,
} from "@/lib/api/similarCandidates";
import {
  addPlan,
  checksByCandidate,
  defaultSelected,
  mergePickableJobs,
  personFirstName,
  personName,
  type PickableJob,
} from "@/lib/similar-candidates-view";
import type { JobNames } from "@/lib/job-names";
import { cn } from "@/lib/utils";

import { candidateBoardHref } from "@/components/v2/candidate-profile/profile-helpers";

interface SimilarAssignSheetProps {
  sourceCandidateId: number;
  sourceName: string;
  people: SimilarCandidate[];
  sourceJobs: PickableJob[];
  myJobs: PickableJob[];
  initialJobId: number | null;
  onClose: () => void;
  onAdded: (candidateIds: number[]) => void;
}

/** Ile rekrutacji listy sprawdzamy od razu (limit trasy). */
const LIST_CHECK_MAX_JOBS = 25;

function useDebounced<T>(value: T, ms: number): T {
  const [out, setOut] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setOut(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return out;
}

export function SimilarAssignSheet({
  sourceCandidateId,
  sourceName,
  people,
  sourceJobs,
  myJobs,
  initialJobId,
  onClose,
  onAdded,
}: SimilarAssignSheetProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const single = people.length === 1;
  const ids = useMemo(() => people.map((p) => p.id), [people]);
  const [jobId, setJobId] = useState<number | null>(initialJobId);
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query.trim(), 250);
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [selected, setSelected] = useState<Set<number> | null>(null);
  const [saving, setSaving] = useState(false);
  const [doneJobs, setDoneJobs] = useState<Set<number>>(new Set());
  const panelRef = React.useRef<HTMLElement | null>(null);
  // Panel „Kogo dodać” stoi pod listą — na laptopie 1280×720 poza ekranem.
  useEffect(() => {
    if (jobId != null) panelRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [jobId]);

  const listJobs = useMemo(() => mergePickableJobs(sourceJobs, myJobs), [sourceJobs, myJobs]);
  const listJobIds = useMemo(
    () => listJobs.slice(0, LIST_CHECK_MAX_JOBS).map((j) => j.id),
    [listJobs],
  );
  const listChecks = useQuery({
    queryKey: ["candidate-similar-check-jobs", sourceCandidateId, listJobIds, ids],
    queryFn: () => similarCandidatesApi.check(sourceCandidateId, listJobIds, ids),
    enabled: listJobIds.length > 0 && listJobIds.length * ids.length <= SIMILAR_CHECK_MAX_PAIRS,
    staleTime: 60_000,
  });

  const searchQuery = useQuery({
    queryKey: ["candidate-similar-job-search", debounced],
    queryFn: () =>
      jobsApi
        .list({ status: "published", q: debounced, page_size: 10 })
        .then((r) => {
          const data = r.data as { items?: Array<JobNames & { id: number; client_name?: string | null }> };
          return (data.items ?? []).map(
            (job): PickableJob => ({
              id: job.id,
              names: job,
              clientName: job.client_name ?? null,
              group: "search",
            }),
          );
        }),
    enabled: debounced.length >= 2,
    staleTime: 60_000,
  });
  const searchJobs = useMemo(
    () => (searchQuery.data ?? []).filter((job) => !listJobs.some((l) => l.id === job.id)),
    [searchQuery.data, listJobs],
  );
  const allJobs = useMemo(() => [...listJobs, ...searchJobs], [listJobs, searchJobs]);
  const job = allJobs.find((j) => j.id === jobId) ?? null;

  const listCheckFor = (id: number): JobCheck | undefined =>
    listChecks.data?.find((j) => j.job_id === id);
  const selectedCheck = useQuery({
    queryKey: ["candidate-similar-check-jobs", sourceCandidateId, [jobId], ids],
    queryFn: () => similarCandidatesApi.check(sourceCandidateId, [jobId as number], ids),
    enabled: jobId != null && !listCheckFor(jobId),
    staleTime: 60_000,
  });
  const jobCheck = jobId != null ? (listCheckFor(jobId) ?? selectedCheck.data?.[0]) : undefined;
  const checks = useMemo(() => checksByCandidate(jobCheck), [jobCheck]);
  const scores = useQuery({
    queryKey: ["candidate-similar-scores", jobId, ids],
    queryFn: () => candidateSearchApi.matchScores(jobId as number, ids),
    enabled: jobId != null,
    staleTime: 60_000,
    retry: false,
  });

  // Po wyborze rekrutacji: zaznaczeni ci, którzy spełniają krytyczne.
  useEffect(() => {
    setSelected(jobCheck ? defaultSelected(ids, checks) : null);
    setReasons({});
  }, [jobCheck, ids, checks]);

  const plan = addPlan(selected ?? new Set(), checks, reasons);
  const checkError = selectedCheck.isError || (listChecks.isError && jobId != null && !jobCheck);

  const submit = async () => {
    if (jobId == null || plan.ids.length === 0 || plan.waitingForReason.length > 0) return;
    setSaving(true);
    try {
      const result = await proposalsBulkApi.add(jobId, {
        candidate_ids: plan.ids,
        source: "similar_candidates",
        reasons: plan.reasons,
      });
      const summary = summarizeBulkResult(result);
      const extras = [
        summary.skipped.length ? `pominięto: ${formatReasonCounts(summary.skipped)}` : "",
        summary.warnings.length ? `ostrzeżenia: ${formatReasonCounts(summary.warnings)}` : "",
      ].filter(Boolean);
      showSuccess(
        `Dodano ${summary.added} ${summary.added === 1 ? "osobę" : "osoby"} do „Nowi”` +
          (extras.length ? ` (${extras.join("; ")})` : "."),
      );
      for (const id of result.added) invalidateCandidateMutation(queryClient, id, "assignment");
      void queryClient.invalidateQueries({ queryKey: ["candidate-similar-check-jobs", sourceCandidateId] });
      void queryClient.invalidateQueries({ queryKey: ["candidate-similar-check", sourceCandidateId] });
      setDoneJobs((prev) => new Set(prev).add(jobId));
      onAdded(result.added);
      if (single && result.added.length > 0) onClose();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się dodać do rekrutacji."));
    } finally {
      setSaving(false);
    }
  };

  const title = single
    ? `Dodaj do rekrutacji: ${personName(people[0])}`
    : `Przypisz ${people.length} zaznaczone osoby do rekrutacji`;
  const anyMissing = plan.ids.some((id) => (checks.get(id)?.missing.length ?? 0) > 0);

  return (
    <Sheet open onOpenChange={(open) => (open ? undefined : onClose())}>
      <SheetContent side="right" size="xl">
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>
            Podobni do: {sourceName}. Przy każdej rekrutacji widać, czy{" "}
            {single
              ? `${personFirstName(people[0])} spełnia`
              : "zaznaczone osoby spełniają"}{" "}
            umiejętności krytyczne — podobieństwo nie znaczy, że pasuje.
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-4">
          <JobGroup
            title={`Rekrutacje w toku: ${sourceName}`}
            empty={`${sourceName} nie jest teraz w żadnej rekrutacji.`}
            jobs={listJobs.filter((j) => j.group === "source")}
            people={people}
            checkFor={listCheckFor}
            checking={listChecks.isPending && listChecks.fetchStatus !== "idle"}
            selectedId={jobId}
            doneJobs={doneJobs}
            onPick={setJobId}
          />
          <JobGroup
            title="Moje otwarte"
            empty="Nie prowadzisz teraz otwartych rekrutacji."
            jobs={listJobs.filter((j) => j.group === "mine")}
            people={people}
            checkFor={listCheckFor}
            checking={listChecks.isPending && listChecks.fetchStatus !== "idle"}
            selectedId={jobId}
            doneJobs={doneJobs}
            onPick={setJobId}
          />
          <section aria-label="Inne otwarte rekrutacje" className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Inne otwarte
            </h3>
            <Input
              leadingIcon={<Search className="h-4 w-4" />}
              placeholder="Tytuł, klient albo numer…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Szukaj rekrutacji"
            />
            {searchQuery.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {apiErrorMessage(searchQuery.error, "Nie udało się wyszukać rekrutacji.")}
              </p>
            ) : searchQuery.isSuccess && searchJobs.length === 0 ? (
              <p className="text-sm text-muted-foreground">Brak innych otwartych rekrutacji o tej nazwie.</p>
            ) : null}
            <div className="space-y-1.5">
              {searchJobs.map((j) => (
                <JobRow
                  key={j.id}
                  job={j}
                  summary={j.id === jobId ? summaryFor(jobCheck, people) : null}
                  selected={j.id === jobId}
                  done={doneJobs.has(j.id)}
                  onPick={() => setJobId(j.id)}
                />
              ))}
            </div>
          </section>

          {job ? (
            <section
              ref={panelRef}
              aria-label="Kogo dodać"
              className="space-y-2 rounded-lg border border-primary/30 bg-primary/5 p-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <JobPickName job={job.names} className="text-sm" />
                {jobCheck && jobCheck.critical_labels.length > 0 ? (
                  <span className="text-xs text-muted-foreground">
                    Krytyczne: {jobCheck.critical_labels.join(", ")}
                  </span>
                ) : null}
              </div>
              {checkError ? (
                <p role="alert" className="text-sm text-destructive">
                  Nie udało się sprawdzić umiejętności krytycznych. Spróbuj wybrać rekrutację jeszcze raz.
                </p>
              ) : !jobCheck ? (
                <p className="text-sm text-muted-foreground">Sprawdzam umiejętności krytyczne…</p>
              ) : (
                <ul className="space-y-2">
                  {people.map((person) => (
                    <PersonCheck
                      key={person.id}
                      person={person}
                      check={checks.get(person.id)}
                      score={scores.data?.scores[String(person.id)]}
                      jobId={job.id}
                      checked={selected?.has(person.id) ?? false}
                      onChecked={(on) =>
                        setSelected((prev) => {
                          const next = new Set(prev ?? []);
                          if (on) next.add(person.id);
                          else next.delete(person.id);
                          return next;
                        })
                      }
                      reason={reasons[person.id] ?? ""}
                      onReason={(text) => setReasons((prev) => ({ ...prev, [person.id]: text }))}
                    />
                  ))}
                </ul>
              )}
            </section>
          ) : null}
        </SheetBody>
        <SheetFooter className="flex-wrap items-center gap-2 sm:justify-between">
          <span className="text-xs text-muted-foreground">
            {job == null
              ? "Wybierz rekrutację."
              : plan.waitingForReason.length > 0
                ? "Napisz, dlaczego mimo braku krytycznej."
                : plan.ids.length === 0
                  ? "Nikt nie jest zaznaczony."
                  : `Dodamy ${plan.ids.length} ${plan.ids.length === 1 ? "osobę" : "osoby"} do „Nowi”.`}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>
              Anuluj
            </Button>
            <Button
              onClick={() => void submit()}
              loading={saving}
              disabled={job == null || plan.ids.length === 0 || plan.waitingForReason.length > 0}
            >
              {anyMissing
                ? "Dodaj mimo to"
                : single || plan.ids.length === 0
                  ? "Dodaj"
                  : `Dodaj ${plan.ids.length}`}
            </Button>
          </div>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function summaryFor(check: JobCheck | undefined, people: SimilarCandidate[]): React.ReactNode {
  if (!check) return null;
  if (people.length === 1) {
    const verdict = checkVerdict(check.candidates.find((c) => c.candidate_id === people[0].id));
    return verdict ? <VerdictBadge kind={verdict.kind}>{verdictText(verdict)}</VerdictBadge> : null;
  }
  if (check.critical_labels.length === 0) {
    return <VerdictBadge kind="no_critical">Rekrutacja bez krytycznych</VerdictBadge>;
  }
  const meeting = check.candidates.filter((c) => checkVerdict(c)?.kind === "met").length;
  return (
    <VerdictBadge kind={meeting === people.length ? "met" : "missing"}>
      {meeting} z {people.length} spełnia krytyczne
    </VerdictBadge>
  );
}

function VerdictBadge({
  kind,
  children,
}: {
  kind: "met" | "missing" | "in_job" | "no_critical";
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-5 max-w-full items-center rounded-full px-2 text-[11px] font-medium",
        kind === "met" && "bg-success-muted text-success-muted-foreground",
        kind === "missing" && "bg-warning-muted text-warning-muted-foreground",
        (kind === "in_job" || kind === "no_critical") && "bg-muted text-muted-foreground",
      )}
    >
      <span className="truncate">{children}</span>
    </span>
  );
}

function JobGroup({
  title,
  empty,
  jobs,
  people,
  checkFor,
  checking,
  selectedId,
  doneJobs,
  onPick,
}: {
  title: string;
  empty: string;
  jobs: PickableJob[];
  people: SimilarCandidate[];
  checkFor: (id: number) => JobCheck | undefined;
  checking: boolean;
  selectedId: number | null;
  doneJobs: Set<number>;
  onPick: (id: number) => void;
}) {
  return (
    <section aria-label={title} className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {title}
      </h3>
      {jobs.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <div className="space-y-1.5">
          {jobs.map((job) => (
            <JobRow
              key={job.id}
              job={job}
              summary={
                summaryFor(checkFor(job.id), people) ??
                (checking ? <span className="text-xs text-muted-foreground">Sprawdzam…</span> : null)
              }
              selected={job.id === selectedId}
              done={doneJobs.has(job.id)}
              onPick={() => onPick(job.id)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function JobRow({
  job,
  summary,
  selected,
  done,
  onPick,
}: {
  job: PickableJob;
  summary: React.ReactNode;
  selected: boolean;
  done: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={selected}
      className={cn(
        "flex w-full min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-lg border px-3 py-2 text-left transition-colors",
        selected ? "border-primary bg-primary/5" : "border-border hover:border-primary/40",
      )}
    >
      <span className="min-w-0 flex-1">
        <JobPickName job={job.names} className="text-sm" />
        {job.clientName ? (
          <span className="block truncate text-xs text-muted-foreground">{job.clientName}</span>
        ) : null}
      </span>
      <span className="flex shrink-0 items-center gap-2">
        {done ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium text-success-muted-foreground">
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
            Dodano
          </span>
        ) : null}
        {summary}
      </span>
    </button>
  );
}

function PersonCheck({
  person,
  check,
  score,
  jobId,
  checked,
  onChecked,
  reason,
  onReason,
}: {
  person: SimilarCandidate;
  check: CandidateCheck | undefined;
  score: number | undefined;
  jobId: number;
  checked: boolean;
  onChecked: (on: boolean) => void;
  reason: string;
  onReason: (text: string) => void;
}) {
  const verdict = checkVerdict(check);
  const name = personName(person);
  const missing = (check?.missing.length ?? 0) > 0;
  const reasonId = `similar-reason-${person.id}`;
  return (
    <li className={cn("rounded-lg border bg-card p-3", missing ? "border-warning/40" : "border-border")}>
      <div className="flex items-start gap-3">
        <Checkbox
          checked={checked}
          disabled={!check || Boolean(check.in_job)}
          onCheckedChange={(value) => onChecked(value === true)}
          aria-label={`Dodaj: ${name}`}
          className="mt-0.5"
        />
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-semibold text-foreground">{name}</span>
            <span className="flex items-center gap-2">
              {verdict ? <VerdictBadge kind={verdict.kind}>{verdictText(verdict)}</VerdictBadge> : null}
              {typeof score === "number" ? (
                <span className="text-xs text-muted-foreground">dopasowanie {Math.round(score)}%</span>
              ) : null}
            </span>
          </div>
          {check?.in_job ? (
            <p className="text-xs text-muted-foreground">
              {check.in_job.label} ·{" "}
              <Link href={candidateBoardHref(jobId, person.id)} className="text-primary hover:underline">
                {check.in_job.closed ? "Przywróć na Tablicy" : "Otwórz kartę"}
              </Link>
            </p>
          ) : check && check.critical.length > 0 ? (
            <ul className="space-y-0.5 text-xs">
              {check.critical.map((item) => (
                <li key={item.label} className="flex items-start gap-1.5">
                  {item.status === "met" ? (
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
                  ) : item.status === "missing" ? (
                    <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
                  ) : (
                    <CircleHelp className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
                  )}
                  <span>
                    <span className="font-medium text-foreground">{item.label}</span>
                    {" — "}
                    {item.status === "met"
                      ? `jest: ${criticalSourcesText(item.sources)}`
                      : item.status === "missing"
                        ? "nie ma w CV, profilu ani notatkach"
                        : "nie da się sprawdzić słowem — do rozmowy"}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {missing && checked ? (
            <div className="space-y-1">
              <label htmlFor={reasonId} className="flex items-center gap-1 text-xs font-medium text-foreground">
                <AlertTriangle className="h-3.5 w-3.5 text-warning" aria-hidden />
                Dlaczego mimo to? Zdanie trafi na kartę jako notatka „Do sprawdzenia”.
              </label>
              <Textarea
                id={reasonId}
                rows={2}
                maxLength={1000}
                value={reason}
                onChange={(e) => onReason(e.target.value)}
                placeholder="Np. jest w opisie ostatniego projektu, choć nie w CV — dopytam w rozmowie."
              />
            </div>
          ) : null}
        </div>
      </div>
    </li>
  );
}
