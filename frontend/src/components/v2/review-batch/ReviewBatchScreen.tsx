"use client";

import { useCallback, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ds/PageHeader";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { pluralPl } from "@/lib/plural-pl";
import {
  addMoreFromNexus,
  invalidateReviewBatch,
  useReviewBatchQueue,
  useReviewBatchStatus,
  type ReviewBatchJob,
  type ReviewBatchSource,
  type ReviewBatchStatus,
  type ReviewBatchLearnedRule,
  type ReviewBatchWhy,
} from "@/lib/api/reviewBatch";

import { usePlainBrief } from "@/lib/api/plainKnowledge";
import { cn } from "@/lib/utils";

import { ReviewBatchCard } from "./ReviewBatchCard";

// pdf.js i docx-preview nie mogą wejść do chunku ekranu; ten sam podgląd co w screeningu.
const CandidatePreviewPane = dynamic(
  () =>
    import("@/components/v2/screening-form/CandidatePreviewPane").then(
      (m) => m.CandidatePreviewPane,
    ),
  { ssr: false, loading: () => <p className="p-4 text-xs text-muted-foreground">Ładowanie CV…</p> },
);

/**
 * Ekran „Porcja dnia” (makiety M5, M7, M9; decyzje Artura z 07.11.2026).
 * Od 10.11.2026 porcja jest na osobę: tyle osób, ile wynosi jej poziom
 * (10, potem +10 dziennie do 50), tylko z jej rekrutacji, najpierw P0, potem
 * niższe priorytety. Dopóki rekruter nie zdecyduje o porcji, ręczne
 * wyszukiwanie zwraca 423. Kolejność narzuca serwer. Od 09.11.2026 CV
 * i wymagania stoją obok decyzji, a zakładka „Do domknięcia” zbiera
 * screeningi bez wyniku.
 */

function screeningsCount(count: number): string {
  return `${count} ${pluralPl(count, "screeningu", "screeningów", "screeningów")}`;
}

function AddMore({ jobId, title, count }: { jobId: number; title: string; count: number }) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          const added = await addMoreFromNexus(jobId);
          invalidateReviewBatch(queryClient);
          showSuccess(
            added > 0
              ? `Dodano ${added} kolejnych osób od Nexusa: ${title}.`
              : `W puli nie ma już osób od progu porcji: ${title}.`,
          );
        } catch (error) {
          showError(apiErrorMessage(error, "Nie udało się dobrać kolejnych osób."));
        } finally {
          setBusy(false);
        }
      }}
    >
      Dodaj {count} kolejnych od Nexusa
    </Button>
  );
}

/** Pusta kolejka: porcja przejrzana albo czekają screeningi po terminie. */
function QueueEmpty({ data }: { data: ReviewBatchStatus }) {
  const overdue = data.overdue_screenings ?? 0;
  if (overdue > 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="review-batch-empty">
        Nie masz nowych osób. Wyszukiwanie wróci po domknięciu {screeningsCount(overdue)} po
        terminie: zakładka „Do domknięcia”.
      </p>
    );
  }
  if (data.met) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="review-batch-empty">
        Porcja przejrzana. Nowa porcja przyjdzie w następny dzień roboczy o 7:00.
      </p>
    );
  }
  return (
    <p className="text-sm text-muted-foreground" data-testid="review-batch-empty">
      Nie masz teraz osób do przejrzenia, a minimum nie jest jeszcze zrobione. Kolejne osoby
      dobierzesz w zakładce „Rekrutacje”.
    </p>
  );
}

export function ReviewBatchScreen() {
  const queryClient = useQueryClient();
  const status = useReviewBatchStatus();
  const queue = useReviewBatchQueue({ enabled: Boolean(status.data?.applies) });
  const onDecided = useCallback(() => {
    invalidateReviewBatch(queryClient);
  }, [queryClient]);

  // `isPending`, nie `isLoading`: na serwerze zapytanie jest wyłączone (konto
  // nieznane), więc oba renderowania muszą pokazać to samo — ładowanie.
  if (status.isPending) {
    return <div className="p-6 text-sm text-muted-foreground">Ładowanie porcji…</div>;
  }
  if (status.isError || !status.data) {
    return (
      <div className="p-6 text-sm text-destructive" role="alert">
        {apiErrorMessage(status.error, "Nie udało się wczytać porcji. Odśwież stronę.")}
      </div>
    );
  }
  const data = status.data;
  if (!data.enabled || !data.applies) {
    return (
      <div className="mx-auto max-w-3xl p-6 space-y-2">
        <PageHeader title="Porcja dnia" density="compact" />
        <p className="text-sm text-muted-foreground">
          {data.enabled
            ? "Porcję dnia dostają konta z rolą rekrutera. Ty możesz szukać bez limitu."
            : "Porcja dnia jest wyłączona."}
        </p>
      </div>
    );
  }
  if (hasNoJobs(data)) {
    // `required = 0` bez rekrutacji dawało „Porcja przejrzana”, czyli wyglądało
    // na zrobioną pracę (audyt 12.11.2026, R4).
    return (
      <div className="mx-auto max-w-3xl p-6 space-y-2" data-testid="review-batch-no-jobs">
        <PageHeader title="Porcja dnia" density="compact" />
        <p className="text-sm font-medium text-foreground">Nie masz przypisanych rekrutacji.</p>
        <p className="text-sm text-muted-foreground">
          Poproś Delivery Leada o przypisanie do rekrutacji: porcja bierze osoby tylko z
          rekrutacji, w których pracujesz.
        </p>
      </div>
    );
  }
  return <BatchWorkspace data={data} queue={queue} onDecided={onDecided} />;
}

/** Brak rekrutacji, w których osoba pracuje, i nic do domknięcia ani przejrzenia. */
function hasNoJobs(data: ReviewBatchStatus): boolean {
  return (
    data.team_jobs.length === 0 &&
    data.required === 0 &&
    data.pending === 0 &&
    (data.open_today_screenings ?? []).length === 0
  );
}

type BatchTab = "decide" | "close" | "jobs";

function progressHint(data: ReviewBatchStatus, open: number): string {
  const overdue = data.overdue_screenings ?? 0;
  if (overdue > 0 && data.remaining === 0) {
    return `Wyszukiwanie wróci po domknięciu ${screeningsCount(overdue)} po terminie. Wpisz wynik albo odrzuć z powodem.`;
  }
  if (!data.met) {
    return `Zdecyduj o ${data.required} osobach: „Pasuje” albo „Nie pasuje” z powodem. Potem wyszukiwanie ręczne wraca. Osobę spoza bazy dodasz zawsze.`;
  }
  return open > 0
    ? `Minimum zrobione. ${open} ${pluralPl(open, "osoba czeka", "osoby czekają", "osób czeka")} na wynik screeningu: bez wyniku w 2 dni robocze wyszukiwanie znów się zablokuje.`
    : "Minimum zrobione. Wyszukiwanie ręczne działa do następnego dnia roboczego, 7:00.";
}

/** Skąd licznik ma taką wartość i co odblokuje wyszukiwanie. */
function BatchProgress({ data }: { data: ReviewBatchStatus }) {
  const open = data.open_screenings ?? 0;
  const done = Math.min(data.done_today, data.required);
  const cells = Array.from({ length: data.required }, (_, index) => index < done);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-border bg-card px-3 py-2">
      <h1 className="text-base font-semibold">Porcja dnia</h1>
      <div className="flex items-center gap-2">
        <div className="flex gap-0.5" aria-hidden="true">
          {cells.map((cell, index) => (
            <span
              key={index}
              className={cn("h-2.5 w-4 rounded-sm", cell ? "bg-primary" : "bg-muted")}
            />
          ))}
        </div>
        <span className="text-sm font-semibold tabular-nums" data-testid="review-batch-progress">
          {done} z {data.required}
        </span>
      </div>
      <p className="min-w-0 flex-1 text-xs text-muted-foreground">{progressHint(data, open)}</p>
      {data.sources ? (
        <span className="flex basis-full flex-wrap items-center gap-1 border-t border-border pt-1.5 text-xs" data-testid="review-batch-sources">
          <span className="text-muted-foreground">Twoja porcja dziś: {data.required} ·</span>
          <span className="rounded bg-destructive/15 px-1.5 py-0.5 font-semibold text-destructive tabular-nums">
            {data.sources.p0} z P0
          </span>
          <span className="rounded bg-muted px-1.5 py-0.5 font-medium tabular-nums text-muted-foreground">
            {data.sources.rest} z P1 i niżej
          </span>
          <span className="text-muted-foreground">
            · tylko z Twoich rekrutacji, najpierw P0
            {data.sources.level_next > data.required
              ? ` · jutro ${data.sources.level_next}, jeśli dziś zdecydujesz o wszystkich (rośnie o 10 do ${data.sources.level_cap})`
              : ""}
          </span>
        </span>
      ) : null}
      <span
        className={cn(
          "rounded-full px-2.5 py-0.5 text-xs font-semibold",
          data.met ? "bg-success/15 text-success" : "bg-warning/15 text-warning",
        )}
      >
        {data.met ? "Wyszukiwanie działa" : "Wyszukiwanie zablokowane"}
      </span>
    </div>
  );
}

const VIA_LABEL: Record<NonNullable<ReviewBatchWhy["via"]>, string> = {
  owner: "prowadzisz",
  assignment: "przypisanie",
  collaborator: "współpraca",
};

function p0Until(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

const SOURCE_LABEL: Record<ReviewBatchSource, string> = {
  p0: "P0",
  p1: "P1 Pilne",
  p2: "Bez priorytetu",
  accepting: "Przyjmujemy kandydatów",
};

/** Jedno zdanie: dlaczego ta osoba jest w Twojej porcji (decyzje Artura 10.11.2026). */
function WhyLine({ why }: { why: ReviewBatchWhy }) {
  return (
    <p className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs leading-snug" data-testid="review-why" data-tour="review-batch.why">
      <span className="font-medium text-muted-foreground">Masz tę osobę, bo:</span>
      <span className="text-muted-foreground">
        Twoja rekrutacja{why.via ? ` (${VIA_LABEL[why.via]})` : ""}
      </span>
      <span className="text-muted-foreground">·</span>
      {why.source === "p0" ? (
        <span className="rounded bg-destructive/15 px-1.5 py-0.5 font-semibold text-destructive">
          P0 do {p0Until(why.p0_until)}
        </span>
      ) : (
        <span className="rounded bg-muted px-1.5 py-0.5 font-medium">{SOURCE_LABEL[why.source]}</span>
      )}
    </p>
  );
}

/** „Z Waszych odrzuceń: wymagamy doświadczenia w Angular (5×)” — reguła R1. */
export function learnedRulesLine(rules: readonly ReviewBatchLearnedRule[] | undefined): string | null {
  if (!rules || rules.length === 0) return null;
  const parts = rules.map(
    (rule) =>
      `${rule.level === "experience" ? "doświadczenia w" : "śladu"} ${rule.label} (${rule.count}×)`,
  );
  return `Z odrzuceń: wymagamy ${parts.join(", ")}`;
}

function JobContext({
  jobId,
  title,
  why,
  rules,
}: {
  jobId: number;
  title: string;
  why?: ReviewBatchWhy;
  rules?: readonly ReviewBatchLearnedRule[];
}) {
  const learned = learnedRulesLine(rules);
  const brief = usePlainBrief(jobId);
  const oneLiner = brief.data?.one_liner ?? null;
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2" data-testid="review-job-context">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Rekrutacja</span>
        <Link href={`/jobs/${jobId}`} target="_blank" className="text-xs text-primary hover:underline">Otwórz</Link>
      </div>
      <div className="text-sm font-semibold leading-snug">{title}</div>
      {why ? <WhyLine why={why} /> : null}
      {oneLiner ? <p className="mt-1 text-xs leading-snug text-muted-foreground">{oneLiner}</p> : null}
      {learned ? (
        <p className="mt-1 text-xs leading-snug text-primary" data-testid="review-learned-rules">
          {learned}
        </p>
      ) : null}
    </div>
  );
}

const GROUPS: { key: ReviewBatchSource; title: string; hint: string }[] = [
  { key: "p0", title: "P0", hint: "Najpierw. Dopóki tu są osoby, porcja idzie stąd." },
  { key: "p1", title: "P1 Pilne", hint: "Po P0." },
  { key: "p2", title: "Bez priorytetu", hint: "Po P1." },
  { key: "accepting", title: "Przyjmujemy kandydatów", hint: "Na końcu." },
];

/** Najwyższy poziom, z którego masz dziś osoby: niżej porcja jeszcze nie sięga. */
function firstOpenGroup(jobs: readonly ReviewBatchJob[]): number | null {
  const open = jobs
    .filter((job) => job.pending > 0)
    .map((job) => GROUPS.findIndex((group) => group.key === job.group))
    .filter((index) => index >= 0);
  return open.length > 0 ? Math.min(...open) : null;
}

function JobRow({
  job,
  data,
  waitsFor,
}: {
  job: ReviewBatchJob;
  data: ReviewBatchStatus;
  waitsFor: string | null;
}) {
  const via = job.via ? VIA_LABEL[job.via] : null;
  return (
    <li className="px-3 py-2 text-sm">
      <div className="flex items-center gap-2">
        <Link href={`/jobs/${job.job_id}`} className="min-w-0 flex-1 truncate hover:underline">
          {job.title}
        </Link>
        {job.pending > 0 ? (
          <span className="shrink-0 tabular-nums text-muted-foreground">{job.pending}</span>
        ) : waitsFor ? (
          <span className="shrink-0 text-xs text-muted-foreground">po {waitsFor}</span>
        ) : (
          <AddMore jobId={job.job_id} title={job.title} count={data.more_cards ?? 20} />
        )}
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
        {job.p0 && job.p0_until ? (
          <span className="font-semibold text-destructive">P0 do {p0Until(job.p0_until)}</span>
        ) : null}
        {via ? <span>{via}</span> : null}
      </div>
    </li>
  );
}

/** Twoje rekrutacje według priorytetu: skąd porcja bierze osoby (10.11.2026). */
function GroupedJobs({ data }: { data: ReviewBatchStatus }) {
  const first = firstOpenGroup(data.team_jobs);
  return (
    <div className="flex flex-col gap-2" data-testid="review-batch-jobs-grouped">
      {GROUPS.map((group, index) => {
        const jobs = data.team_jobs.filter((job) => job.group === group.key);
        const waitsFor = first !== null && index > first ? GROUPS[first].title : null;
        if (jobs.length === 0) return null;
        return (
          <section key={group.key}>
            <div className="mb-1 flex items-baseline justify-between gap-2 px-1">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {group.title} <span className="tabular-nums opacity-70">{jobs.length}</span>
              </h2>
            </div>
            <p className="mb-1 px-1 text-[11px] leading-snug text-muted-foreground">{group.hint}</p>
            <ul
              className={cn(
                "divide-y divide-border rounded-lg border bg-card",
                group.key === "p0" ? "border-destructive/40" : "border-border",
              )}
            >
              {jobs.map((job) => (
                <JobRow key={job.job_id} job={job} data={data} waitsFor={waitsFor} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function BatchWorkspace({
  data,
  queue,
  onDecided,
}: {
  data: ReviewBatchStatus;
  queue: ReturnType<typeof useReviewBatchQueue>;
  onDecided: () => void;
}) {
  const [tab, setTab] = useState<BatchTab>(
    (data.overdue_screenings ?? 0) > 0 ? "close" : "decide",
  );
  const [picked, setPicked] = useState(0);
  // Klik w „Kluczowe” na karcie: CV po prawej szuka tej frazy (jak „Wymagania”).
  const [searchRequest, setSearchRequest] = useState<{ text: string; nonce: number } | null>(null);
  const next = queue.data?.items?.[0] ?? null;
  const open = data.open_today_screenings ?? [];
  const selected = open[Math.min(picked, Math.max(open.length - 1, 0))] ?? null;
  const preview =
    tab === "decide" && next
      ? { candidateId: next.candidate_id, jobId: next.job_id, stageId: next.stage_id, budget: next.budget_hourly }
      : tab === "close" && selected
        ? { candidateId: selected.candidate_id, jobId: selected.job_id, stageId: null, budget: null }
        : null;
  const tabs: { value: BatchTab; label: string; count: number }[] = [
    { value: "decide", label: "Do decyzji", count: data.pending },
    { value: "close", label: "Do domknięcia", count: open.length },
    { value: "jobs", label: "Rekrutacje", count: data.team_jobs.length },
  ];

  return (
    <div className="flex min-h-0 flex-col gap-2 p-3 lg:h-[calc(100dvh-4rem)]">
      <BatchProgress data={data} />
      <div className="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        <div className="flex w-full shrink-0 flex-col gap-2 overflow-y-auto pr-1 lg:w-[390px]">
          <div className="flex gap-1 rounded-lg bg-muted/50 p-1" role="tablist">
            {tabs.map((item) => (
              <button
                key={item.value}
                type="button"
                role="tab"
                aria-selected={tab === item.value}
                onClick={() => setTab(item.value)}
                className={cn(
                  "flex-1 rounded-md px-2 py-1 text-xs font-medium",
                  tab === item.value ? "bg-card text-foreground shadow-sm" : "text-muted-foreground",
                )}
              >
                {item.label} <span className="tabular-nums opacity-70">{item.count}</span>
              </button>
            ))}
          </div>

          {tab === "decide" ? (
            next ? (
              <>
                <JobContext
                  jobId={next.job_id}
                  title={next.job_title}
                  why={next.why}
                  rules={queue.data?.job_rules?.[String(next.job_id)]}
                />
                <ReviewBatchCard
                  key={next.process_id}
                  item={next}
                  onDecided={onDecided}
                  hideJob
                  onPickRequirement={(text) => setSearchRequest({ text, nonce: Date.now() })}
                />
              </>
            ) : queue.isError ? (
              <div className="text-sm text-destructive" role="alert">
                {apiErrorMessage(queue.error, "Nie udało się wczytać osób z porcji.")}
              </div>
            ) : !queue.isSuccess ? (
              <div className="text-sm text-muted-foreground">Ładowanie osób…</div>
            ) : (
              <QueueEmpty data={data} />
            )
          ) : null}

          {tab === "close" ? (
            <ul className="divide-y divide-border rounded-lg border border-border bg-card" data-testid="review-batch-open-today">
              {open.map((item, index) => {
                const active = selected === item;
                return (
                  <li key={`${item.job_id}-${item.candidate_id}`} className={cn("px-3 py-2", active && "bg-primary/5")}>
                    <button type="button" onClick={() => setPicked(index)} className="block w-full text-left">
                      <span className="flex items-center gap-1.5 text-sm font-medium">
                        <span className="min-w-0 truncate">{item.name}</span>
                        {item.overdue ? (
                          <span className="shrink-0 rounded bg-destructive/15 px-1.5 py-0.5 text-xs font-medium text-destructive">
                            po terminie
                          </span>
                        ) : null}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">{item.job_title}</span>
                    </button>
                    {active ? (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        <Button size="sm" asChild>
                          <Link href={`/jobs/${item.job_id}?candidate=${item.candidate_id}`}>Otwórz screening</Link>
                        </Button>
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : null}

          {tab === "jobs" ? (
            data.team_jobs.some((job) => job.group) ? (
              <GroupedJobs data={data} />
            ) : (
            <ul className="divide-y divide-border rounded-lg border border-border bg-card">
              {data.team_jobs.map((job) => (
                <li key={job.job_id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                  <Link href={`/jobs/${job.job_id}`} className="min-w-0 flex-1 truncate hover:underline">
                    {job.p0 ? <span className="mr-1 font-semibold text-destructive">P0</span> : null}
                    {job.title}
                  </Link>
                  {job.pending > 0 ? (
                    <span className="tabular-nums text-muted-foreground">{job.pending}</span>
                  ) : (
                    <AddMore jobId={job.job_id} title={job.title} count={data.more_cards ?? 20} />
                  )}
                </li>
              ))}
            </ul>
            )
          ) : null}
        </div>

        <div className="hidden min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-card p-2 lg:flex">
          {preview ? (
            <CandidatePreviewPane
              key={`${preview.jobId}-${preview.candidateId}`}
              candidateId={preview.candidateId}
              jobId={preview.jobId}
              stageId={preview.stageId}
              budgetHourly={preview.budget}
              searchRequest={searchRequest}
              className="min-h-0 flex-1"
            />
          ) : (
            <p className="m-auto text-sm text-muted-foreground">Wybierz osobę, żeby zobaczyć jej CV i wymagania.</p>
          )}
        </div>
      </div>
    </div>
  );
}
