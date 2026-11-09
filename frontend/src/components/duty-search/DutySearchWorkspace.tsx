"use client";

/**
 * „Kto już to robił” — wyszukiwanie po celu projektu i obowiązkach
 * (decyzja Artura 09.11.2026, reguła
 * `docs/claude/kandydaci-wyszukiwanie/kto-juz-to-robil-wyszukiwanie-po-celu.md`).
 *
 * Dwa wejścia: rekrutacja (`?mode=goal&job=…`, obowiązki z Championa) i okno
 * „Z requestu” → „Cel projektu” (`?mode=goal&run=…`). Przebieg liczy się
 * w tle 1,5–2 min; awaria to komunikat, nigdy pusta lista.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Check,
  CircleDashed,
  ExternalLink,
  Loader2,
  Minus,
  Pencil,
  Quote,
  RefreshCw,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  UserPlus,
} from "lucide-react";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { proposalsBulkApi } from "@/lib/candidate-search-api";
import {
  dutyFailureMessage,
  dutyRunIsActive,
  dutySearchApi,
  dutySearchKeys,
  type DutyCapability,
  type DutyCapState,
  type DutyResult,
  type DutyRun,
  type DutyTier,
  type DutyUsage,
} from "@/lib/duty-search-api";

const POLL_MS = 3000;

type ShownTier = Exclude<DutyTier, "brak">;

const TIER_LABEL: Record<DutyTier, string> = {
  zrobil_to: "Robił to",
  bardzo_blisko: "Bardzo blisko",
  ma_klocki: "Ma klocki",
  brak: "Bez dowodu celu",
};

const TIER_HINT: Record<DutyTier, string> = {
  zrobil_to: "prowadził albo wykonał podobny cel",
  bardzo_blisko: "rdzeń celu w innej technologii, skali albo jako współwykonawca",
  ma_klocki: "ma umiejętności składowe, ale CV nie pokazuje takiego projektu",
  brak: "AI nie znalazło w CV cytatu związanego z celem",
};

const TIER_CLASS: Record<DutyTier, string> = {
  zrobil_to: "bg-success-muted text-success-muted-foreground border-success/30",
  bardzo_blisko: "bg-info-muted text-info-muted-foreground border-info/30",
  ma_klocki: "bg-muted text-muted-foreground border-border",
  brak: "bg-background text-muted-foreground border-dashed border-border",
};

function shortCap(name: string): string {
  const clean = name.replace(/\s*\(.*?\)\s*/g, " ").trim();
  return clean.length > 34 ? `${clean.slice(0, 32)}…` : clean;
}

function CapDot({ state }: { state: DutyCapState | undefined }) {
  if (state === "tak")
    return (
      <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-success text-success-foreground">
        <Check className="h-3 w-3" aria-label="tak" />
      </span>
    );
  if (state === "czesciowo")
    return (
      <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-warning-muted text-warning-muted-foreground">
        <Minus className="h-3 w-3" aria-label="częściowo" />
      </span>
    );
  return (
    <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-border text-muted-foreground">
      <CircleDashed className="h-3 w-3" aria-label="brak w CV" />
    </span>
  );
}

function UsageNote({ usage }: { usage: DutyUsage | undefined }) {
  if (!usage) return null;
  return (
    <span className="text-xs text-muted-foreground">
      Dziś: {usage.used_today} z {usage.daily_limit} wyszukiwań
    </span>
  );
}

interface ResultCardProps {
  runId: string;
  r: DutyResult;
  caps: DutyCapability[];
  jobId: number | null;
}

function ResultCard({ runId, r, caps, jobId }: ResultCardProps) {
  const { showSuccess, showError } = useToast();
  const [vote, setVote] = useState<"up" | "down" | null>(r.feedback);
  const [added, setAdded] = useState(false);
  const feedback = useMutation({
    mutationFn: (next: "up" | "down" | null) => dutySearchApi.feedback(runId, r.candidate_id, next),
    onError: (error) => showError(apiErrorMessage(error, "Nie zapisano oceny „Trafne?”.")),
  });
  const add = useMutation({
    mutationFn: () =>
      proposalsBulkApi.add(jobId as number, { candidate_ids: [r.candidate_id], source: "duty_search" }),
    onSuccess: (res) => {
      if (res.total_added > 0) {
        setAdded(true);
        showSuccess(`${r.name} — dodano do Nowych.`);
      } else {
        showError(`${r.name} — nie dodano (osoba jest już w tej rekrutacji albo jest wykluczona).`);
      }
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się dodać osoby do rekrutacji.")),
  });
  const setVoteAndSave = (next: "up" | "down") => {
    const value = vote === next ? null : next;
    setVote(value);
    feedback.mutate(value);
  };
  const first = r.evidence[0];
  return (
    <li className="rounded-lg border border-border bg-card p-3" data-testid="duty-result">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-foreground">{r.name}</span>
            <span
              title={TIER_HINT[r.tier]}
              className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${TIER_CLASS[r.tier]}`}
            >
              {TIER_LABEL[r.tier]}
            </span>
            {r.confidence !== null && r.tier !== "brak" ? (
              <span className="text-xs text-muted-foreground">pewność {r.confidence}%</span>
            ) : null}
            {r.from_goal_only ? (
              <span
                title="Zwykłe wyszukiwanie po profilu nie pokazało tej osoby w pierwszej pięćdziesiątce"
                className="rounded-full border border-primary/30 bg-primary/5 px-2 py-0.5 text-[11px] font-medium text-primary"
              >
                znalezione po celu
              </span>
            ) : null}
            {r.error ? (
              <span className="text-[11px] text-warning-muted-foreground">
                {r.error === "no_cv" ? "brak tekstu CV" : "AI nie oceniło"}
              </span>
            ) : null}
          </div>
          <div className="truncate text-xs text-muted-foreground">
            {r.position || "—"}
            {r.years_it ? ` · ${r.years_it} lat w IT` : ""}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <span
            title="Dopasowanie profilu — ta sama liczba co w „Z requestu”"
            className="mr-1 inline-flex h-7 items-center rounded-md border border-border px-2 text-xs tabular-nums text-muted-foreground"
          >
            Dop. <span className="ml-1 font-semibold text-foreground">{r.fit_score ?? "—"}</span>
          </span>
          {jobId ? (
            <button
              type="button"
              disabled={add.isPending || added}
              onClick={() => add.mutate()}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-primary/30 bg-card px-2 text-xs font-semibold text-primary hover:bg-primary/5 disabled:opacity-60"
            >
              {add.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : added ? (
                <Check className="h-3.5 w-3.5" aria-hidden />
              ) : (
                <UserPlus className="h-3.5 w-3.5" aria-hidden />
              )}
              {added ? "Dodano" : "Dodaj do Nowych"}
            </button>
          ) : null}
          <Link
            href={`/candidates/${r.candidate_id}`}
            target="_blank"
            className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            Profil
          </Link>
        </div>
      </div>

      {first || r.question ? (
        <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
          <div className="min-w-0 space-y-1.5">
            {first ? (
              <figure className="rounded-md border-l-2 border-primary/50 bg-muted/40 px-2.5 py-1.5">
                <blockquote className="flex gap-1.5 text-[13px] leading-snug text-foreground">
                  <Quote className="mt-0.5 h-3 w-3 shrink-0 text-primary/60" aria-hidden />
                  <span className="line-clamp-2">{first.quote}</span>
                </blockquote>
                {first.where ? (
                  <figcaption className="mt-0.5 truncate pl-[18px] text-[11px] text-muted-foreground">
                    {first.where}
                  </figcaption>
                ) : null}
              </figure>
            ) : null}
            {first?.meaning ? (
              <p className="text-xs leading-snug text-foreground">
                <span className="font-semibold">Co z tego wynika: </span>
                {first.meaning}
              </p>
            ) : null}
            {r.question ? (
              <p className="text-xs leading-snug text-muted-foreground">
                <span className="font-semibold text-foreground">Zapytaj na rozmowie: </span>
                {r.question}
              </p>
            ) : null}
          </div>
          <div className="space-y-1 md:border-l md:border-border md:pl-3">
            {caps.map((c) => (
              <div key={c.name} className="flex items-center gap-1.5 text-[11px] text-foreground" title={c.name}>
                <CapDot state={r.capabilities[c.name]} />
                <span className="truncate">{shortCap(c.name)}</span>
              </div>
            ))}
            <div className="flex items-center gap-1 pt-1">
              <span className="text-[11px] text-muted-foreground">Trafne?</span>
              <button
                type="button"
                aria-label="Trafne"
                aria-pressed={vote === "up"}
                onClick={() => setVoteAndSave("up")}
                className={`rounded p-1 hover:bg-muted ${vote === "up" ? "text-success" : "text-muted-foreground"}`}
              >
                <ThumbsUp className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                aria-label="Nietrafne"
                aria-pressed={vote === "down"}
                onClick={() => setVoteAndSave("down")}
                className={`rounded p-1 hover:bg-muted ${vote === "down" ? "text-destructive" : "text-muted-foreground"}`}
              >
                <ThumbsDown className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </li>
  );
}

interface GoalPanelProps {
  run: DutyRun;
  fromJob: boolean;
  draft: string;
  onDraft: (value: string) => void;
}

function GoalPanel({ run, fromJob, draft, onDraft }: GoalPanelProps) {
  const [open, setOpen] = useState(false);
  return (
    <section className="rounded-lg border border-border bg-card px-3 py-2" aria-label="Cel i co sprawdzamy">
      <div className="flex items-start gap-2">
        <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
        <p className="min-w-0 flex-1 text-[13px] leading-snug text-foreground">
          <span className="font-semibold">Szukamy osób, które już: </span>
          {run.plan.summary || run.title || "—"}
        </p>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="inline-flex shrink-0 items-center gap-1 text-xs text-primary hover:underline"
        >
          <Pencil className="h-3 w-3" aria-hidden />
          {open ? "Zwiń" : fromJob ? "Obowiązki i kryteria" : "Cel i kryteria"}
        </button>
      </div>
      {run.plan.capabilities.length ? (
        <ul className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-6">
          <li className="text-xs text-muted-foreground">Sprawdzamy w CV:</li>
          {run.plan.capabilities.map((c) => (
            <li
              key={c.name}
              title={c.hint}
              className="inline-flex items-center gap-1 rounded-full border border-border bg-background px-2 py-0.5 text-xs text-foreground"
            >
              <span className="text-[9px] text-primary" aria-label={`waga ${c.weight}`}>
                {"●".repeat(Math.max(1, Math.min(3, c.weight)))}
              </span>
              {shortCap(c.name)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 pl-6 text-xs text-muted-foreground">
          AI nie rozpisało celu — oceny idą względem samego opisu.
        </p>
      )}
      {open ? (
        <div className="mt-2 grid grid-cols-1 gap-4 border-t border-border pt-2 md:grid-cols-2">
          <div className="min-w-0 space-y-1">
            <label htmlFor="duty-goal-edit" className="text-xs font-semibold text-muted-foreground">
              {fromJob ? "Obowiązki (zmiana dotyczy tylko tego wyszukiwania)" : "Co osoba ma zrobić"}
            </label>
            <textarea
              id="duty-goal-edit"
              value={draft}
              onChange={(e) => onDraft(e.target.value)}
              rows={7}
              className="w-full rounded-md border border-input bg-background p-2 text-[13px] leading-snug"
            />
            <p className="text-xs text-muted-foreground">Po zmianie kliknij „Szukaj ponownie”.</p>
          </div>
          <div className="min-w-0 space-y-2 text-xs">
            {run.plan.signals.length ? (
              <div>
                <p className="font-semibold text-muted-foreground">Po czym poznamy, gdy CV nazywa to inaczej</p>
                <ul className="mt-1 space-y-0.5 pl-3">
                  {run.plan.signals.map((s) => (
                    <li key={s.signal} className="list-disc text-foreground">
                      {s.signal} {s.why ? <span className="text-muted-foreground">— {s.why}</span> : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {run.plan.anti.length ? (
              <p className="text-muted-foreground">
                <span className="font-semibold">Nie liczymy: </span>
                {run.plan.anti.join(" · ")}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

function RunningPanel({ run }: { run: DutyRun | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const started = run?.created_at ? Date.parse(run.created_at) : now;
  const seconds = Math.max(0, Math.round((now - started) / 1000));
  return (
    <section
      className="flex items-start gap-3 rounded-lg border border-border bg-card p-4"
      role="status"
      data-testid="duty-search-running"
    >
      <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-primary" aria-hidden />
      <div className="space-y-1 text-sm">
        <p className="font-semibold text-foreground">
          Szukamy, kto już to robił… <span className="tabular-nums text-muted-foreground">{seconds} s</span>
        </p>
        <p className="text-muted-foreground">
          AI rozpisuje cel, szukamy w całej bazie i AI czyta ok. 100 najbliższych CV. Zwykle 1,5–2 min. Możesz
          zamknąć tę stronę — wynik zapisze się przy tej rekrutacji albo pod tym adresem.
        </p>
      </div>
    </section>
  );
}

function FailedPanel({ code, onRetry, retrying }: { code: string | null; onRetry?: () => void; retrying?: boolean }) {
  return (
    <section
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm"
      data-testid="duty-search-failed"
    >
      <p className="text-foreground">{dutyFailureMessage(code)}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-semibold hover:bg-muted disabled:opacity-60"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          Uruchom ponownie
        </button>
      ) : null}
    </section>
  );
}

function Results({ run, jobId }: { run: DutyRun; jobId: number | null }) {
  const [tier, setTier] = useState<ShownTier | "all">("all");
  const [showRest, setShowRest] = useState(false);
  const withEvidence = run.results.filter((r) => r.tier !== "brak");
  const rest = run.results.filter((r) => r.tier === "brak");
  const shown = withEvidence.filter((r) => tier === "all" || r.tier === tier);
  const count = (t: ShownTier) => withEvidence.filter((r) => r.tier === t).length;
  const seconds = run.stats.seconds ?? 0;
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Poziom dopasowania">
          {(["all", "zrobil_to", "bardzo_blisko", "ma_klocki"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tier === t}
              title={t === "all" ? undefined : TIER_HINT[t]}
              onClick={() => setTier(t)}
              className={`inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[13px] font-semibold ${
                tier === t
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-card text-foreground hover:border-primary/40"
              }`}
            >
              {t === "all" ? "Wszyscy" : TIER_LABEL[t]}
              <span className="tabular-nums text-muted-foreground">{t === "all" ? withEvidence.length : count(t)}</span>
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          AI przeczytało {run.stats.judged ?? "—"} CV · {Math.floor(seconds / 60)}:
          {String(Math.round(seconds % 60)).padStart(2, "0")} min · każdy poziom ma cytat z CV
          {run.stats.canonical_degraded ? " · bez listy „Dopasowanie” (chwilowa awaria)" : ""}
        </p>
      </div>
      {shown.length ? (
        <ul className="space-y-2">
          {shown.map((r) => (
            <ResultCard key={r.candidate_id} runId={run.run_id} r={r} caps={run.plan.capabilities} jobId={jobId} />
          ))}
        </ul>
      ) : (
        <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
          {withEvidence.length
            ? "Nikt w tej grupie. Wybierz inny poziom."
            : "AI nie znalazło w przeczytanych CV cytatu związanego z celem. Spróbuj opisać cel inaczej albo szerzej."}
        </p>
      )}
      {rest.length ? (
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => setShowRest((v) => !v)}
            aria-expanded={showRest}
            className="text-xs font-medium text-muted-foreground hover:text-foreground"
          >
            {showRest ? "Ukryj" : "Pokaż"} osoby bez dowodu celu ({rest.length}) — przeczytane, bez cytatu o celu
          </button>
          {showRest ? (
            <ul className="space-y-2">
              {rest.map((r) => (
                <ResultCard key={r.candidate_id} runId={run.run_id} r={r} caps={run.plan.capabilities} jobId={jobId} />
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

interface RunAreaProps {
  run: DutyRun | null;
  jobId: number | null;
  draft: string;
  onDraft: (value: string) => void;
  onRestart?: () => void;
  restarting?: boolean;
}

function RunArea({ run, jobId, draft, onDraft, onRestart, restarting }: RunAreaProps) {
  if (!run || dutyRunIsActive(run.state)) return <RunningPanel run={run} />;
  if (run.state === "failed") return <FailedPanel code={run.error_code} onRetry={onRestart} retrying={restarting} />;
  return (
    <>
      <GoalPanel run={run} fromJob={jobId !== null} draft={draft} onDraft={onDraft} />
      <Results run={run} jobId={jobId} />
    </>
  );
}

function useRunQuery(runId: string | null) {
  return useQuery({
    queryKey: dutySearchKeys.run(runId ?? ""),
    queryFn: ({ signal }) => dutySearchApi.run(runId as string, signal),
    enabled: Boolean(runId),
    refetchInterval: (query) => (dutyRunIsActive(query.state.data?.state) ? POLL_MS : false),
  });
}

function JobDutySearch({ jobId }: { jobId: number }) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const latest = useQuery({
    queryKey: dutySearchKeys.jobLatest(jobId),
    queryFn: ({ signal }) => dutySearchApi.jobLatest(jobId, signal),
    refetchInterval: (query) => (dutyRunIsActive(query.state.data?.run?.state) ? POLL_MS : false),
  });
  const [draft, setDraft] = useState<string | null>(null);
  const goalText = draft ?? latest.data?.run?.goal ?? latest.data?.duties ?? "";
  const start = useMutation({
    mutationFn: () => {
      const edited = draft !== null && draft.trim() !== (latest.data?.duties ?? "").trim();
      return dutySearchApi.start({ job_id: jobId, goal: edited ? draft.trim() : undefined });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: dutySearchKeys.jobLatest(jobId) }),
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się uruchomić wyszukiwania.")),
  });
  const data = latest.data;
  const run = data?.run ?? null;
  const active = dutyRunIsActive(run?.state) || start.isPending;
  const canStart = goalText.trim().length >= 30 && !active;

  return (
    <div className="space-y-3" data-testid="duty-search">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link
            href={`/jobs/${jobId}`}
            className="inline-flex max-w-full items-center gap-1.5 truncate text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4 shrink-0" aria-hidden />
            <span className="truncate">{data?.title ?? "Rekrutacja"}</span>
          </Link>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">Kto już to robił</h1>
        </div>
        <div className="flex items-center gap-3">
          <UsageNote usage={run?.usage ?? data?.usage} />
          {run ? (
            <button
              type="button"
              onClick={() => start.mutate()}
              disabled={!canStart}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden />
              Szukaj ponownie
            </button>
          ) : null}
        </div>
      </div>
      {latest.isPending ? (
        <p className="text-sm text-muted-foreground">Wczytuję…</p>
      ) : latest.isError ? (
        <section role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm">
          {apiErrorMessage(latest.error, "Nie udało się wczytać wyszukiwania dla tej rekrutacji.")}
        </section>
      ) : !run && !start.isPending ? (
        <section className="space-y-3 rounded-lg border border-border bg-card p-4">
          <p className="text-sm text-muted-foreground">
            Szukamy osób, które robiły to, co opisują obowiązki z Championa — także gdy w CV nazwały to inaczej. Każdą
            ocenę popiera cytat z CV. Trwa 1,5–2 min.
          </p>
          <label htmlFor="duty-job-goal" className="block text-sm font-semibold text-foreground">
            Obowiązki z Championa
          </label>
          <textarea
            id="duty-job-goal"
            value={goalText}
            onChange={(e) => setDraft(e.target.value)}
            rows={8}
            placeholder="Champion tej rekrutacji nie ma obowiązków. Opisz, co osoba ma zrobić."
            className="w-full rounded-md border border-input bg-background p-2.5 text-sm leading-snug"
          />
          <button
            type="button"
            onClick={() => start.mutate()}
            disabled={!canStart}
            className="inline-flex h-9 items-center gap-1.5 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            <Sparkles className="h-4 w-4" aria-hidden />
            Szukaj, kto już to robił
          </button>
        </section>
      ) : (
        <RunArea
          run={start.isPending ? null : run}
          jobId={jobId}
          draft={goalText}
          onDraft={setDraft}
          onRestart={() => start.mutate()}
          restarting={start.isPending}
        />
      )}
    </div>
  );
}

function StandaloneDutySearch({ runId }: { runId: string }) {
  const query = useRunQuery(runId);
  const [draft, setDraft] = useState<string | null>(null);
  const run = query.data ?? null;
  return (
    <div className="space-y-3" data-testid="duty-search">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <Link href="/candidates" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
            <ArrowLeft className="h-4 w-4" aria-hidden />
            Kandydaci
          </Link>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">Kto już to robił</h1>
        </div>
        <UsageNote usage={run?.usage} />
      </div>
      {query.isPending ? (
        <p className="text-sm text-muted-foreground">Wczytuję…</p>
      ) : query.isError ? (
        <section role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm">
          {apiErrorMessage(query.error, "Nie udało się wczytać wyszukiwania.")}
        </section>
      ) : (
        <RunArea run={run} jobId={null} draft={draft ?? run?.goal ?? ""} onDraft={setDraft} />
      )}
    </div>
  );
}

export interface DutySearchWorkspaceProps {
  jobId?: number | null;
  runId?: string | null;
}

export function DutySearchWorkspace({ jobId, runId }: DutySearchWorkspaceProps) {
  const job = useMemo(() => (jobId && Number.isFinite(jobId) && jobId > 0 ? jobId : null), [jobId]);
  if (job) return <JobDutySearch jobId={job} />;
  if (runId) return <StandaloneDutySearch runId={runId} />;
  return (
    <div className="space-y-2" data-testid="duty-search">
      <h1 className="text-lg font-semibold tracking-tight text-foreground">Kto już to robił</h1>
      <p className="text-sm text-muted-foreground">
        Otwórz rekrutację i wybierz „Szukaj → Kto już to robił” albo na liście Kandydatów kliknij „Z requestu” →
        „Cel projektu”.
      </p>
    </div>
  );
}
