"use client";

/**
 * Karta przegranej rekrutacji na spotkaniu z DL (25.11.2026): fakty z NEXUSA,
 * „Dlaczego?” i „Skąd wiesz?” (ten sam zapis co okno zamknięcia), „Co zmieniamy?”
 * i pytanie do hiring managera.
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  LESSON_SCOPES,
  LOST_STAGES,
  LOST_WHY,
  LOST_WHY_SOURCES,
  lostReviewApi,
  lostReviewKeys,
  plNumber,
  toggleLostWhy,
  type LessonScope,
  type LostReviewJob,
  type LostWhyKey,
  type LostWhySource,
} from "@/lib/lost-review";
import { cn } from "@/lib/utils";

import { STAGE_TONE } from "./LostReviewCharts";

function shortDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" });
}

function verdictText(verdicts: string[]): string {
  const counts = new Map<string, number>();
  for (const v of verdicts) counts.set(v, (counts.get(v) ?? 0) + 1);
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([k, n]) => (n > 1 ? `${k} ×${n}` : k))
    .join(", ");
}

export function LostReviewJobCard({
  job,
  highlighted,
}: {
  job: LostReviewJob;
  highlighted?: boolean;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [why, setWhy] = useState<LostWhyKey[]>(job.why);
  const [source, setSource] = useState<LostWhySource | null>(job.source);
  const [lesson, setLesson] = useState("");
  const [scope, setScope] = useState<LessonScope>("client");
  const [askOpen, setAskOpen] = useState(false);
  const stage = LOST_STAGES.find((s) => s.key === job.stage);

  // Zapis po każdym kliknięciu, jeden naraz: klik w trakcie zapisu czeka, a po
  // nim idzie tylko ostatni wybór — dwa PUT-y nie mogą dojść w odwrotnej kolejności.
  const queued = useRef<{ why: LostWhyKey[]; source: LostWhySource | null } | null>(null);
  const inFlight = useRef(false);
  const saveWhy = useMutation({
    mutationFn: (next: { why: LostWhyKey[]; source: LostWhySource | null }) =>
      lostReviewApi.saveWhy(job.job_id, next),
    onError: (e) => {
      queued.current = null;
      setWhy(job.why);
      setSource(job.source);
      showError(apiErrorMessage(e, "Nie udało się zapisać powodu."));
    },
    onSettled: () => {
      const next = queued.current;
      queued.current = null;
      if (next) {
        saveWhy.mutate(next);
        return;
      }
      inFlight.current = false;
      void queryClient.invalidateQueries({ queryKey: lostReviewKeys.all });
    },
  });
  const send = (next: { why: LostWhyKey[]; source: LostWhySource | null }) => {
    if (inFlight.current) {
      queued.current = next;
      return;
    }
    inFlight.current = true;
    saveWhy.mutate(next);
  };
  // Świeże dane z serwera (inna osoba na spotkaniu, okno zamknięcia) — gdy nic
  // nie czeka na zapis. Karta ma klucz `job_id`, więc wpisany wniosek zostaje.
  const serverWhy = job.why.join(",");
  useEffect(() => {
    if (inFlight.current) return;
    setWhy(job.why);
    setSource(job.source);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverWhy, job.source]);

  const addLesson = useMutation({
    mutationFn: () =>
      lostReviewApi.addLesson({ scope, text: lesson, job_id: job.job_id }),
    onSuccess: () => {
      setLesson("");
      showSuccess(scope === "client" ? "Zapisane jako zasada klienta." : "Wniosek zapisany.");
      void queryClient.invalidateQueries({ queryKey: lostReviewKeys.all });
    },
    onError: (e) => showError(apiErrorMessage(e, "Nie udało się zapisać wniosku.")),
  });

  const pickWhy = (key: LostWhyKey) => {
    const next = toggleLostWhy(why, key);
    setWhy(next);
    send({ why: next, source });
  };
  const pickSource = (key: LostWhySource) => {
    const next = source === key ? null : key;
    setSource(next);
    send({ why, source: next });
  };

  return (
    <article
      id={`lost-job-${job.job_id}`}
      className={cn(
        "rounded-xl border bg-card px-4 py-3",
        highlighted ? "border-primary ring-2 ring-primary/30" : "border-border",
      )}
      data-testid="lost-review-job"
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <Link href={`/jobs/${job.job_id}`} className="min-w-0 font-medium text-primary hover:underline">
          {job.title}
        </Link>
        <span className="text-sm text-muted-foreground">
          {job.client_name} · {job.dl_name ?? "bez DL"} · zamknięta {shortDate(job.closed_at)}
        </span>
        {stage ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs">
            <span className={cn("size-2 rounded-full", STAGE_TONE[stage.key])} />
            {stage.label}
          </span>
        ) : null}
        {job.outcome === "idle" ? (
          <span className="rounded-full bg-warning-muted px-2 py-0.5 text-xs text-warning-muted-foreground">
            NEXUS zamknął po 28 dniach
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-sm text-foreground">
        1. CV po {job.days_first_cv === null ? "—" : `${plNumber(job.days_first_cv)} dn.`} · {job.cvs} CV ·{" "}
        {job.interviews} rozm. u klienta · otwarta {plNumber(job.days_open, 0)} dn. ·{" "}
        {job.client_verdicts.length ? (
          <span>Klient o naszych: {verdictText(job.client_verdicts)}</span>
        ) : (
          <span className="text-destructive">klient nie ocenił nikogo z naszych</span>
        )}
      </p>
      {job.notes ? (
        <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">„{job.notes}”</p>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-1">
        <span className="mr-1 text-xs font-semibold text-foreground">Dlaczego?</span>
        {LOST_WHY.map((w) => {
          const on = why.includes(w.key);
          return (
            <button
              key={w.key}
              type="button"
              aria-pressed={on}
              onClick={() => pickWhy(w.key)}
              className={cn(
                "rounded-full border px-2 py-0.5 text-xs",
                on ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted",
              )}
            >
              {w.label}
            </button>
          );
        })}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1">
        <span className="mr-1 text-xs font-semibold text-foreground">Skąd wiesz?</span>
        {LOST_WHY_SOURCES.map((s) => (
          <button
            key={s.key}
            type="button"
            aria-pressed={source === s.key}
            onClick={() => pickSource(s.key)}
            className={cn(
              "rounded-full border px-2 py-0.5 text-xs",
              source === s.key ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-muted",
            )}
          >
            {s.label}
          </button>
        ))}
        {source === "unknown" || !job.client_verdicts.length ? (
          <Button type="button" size="sm" variant="outline" className="ml-auto h-7" onClick={() => setAskOpen(true)}>
            Pytanie do klienta
          </Button>
        ) : null}
      </div>
      <form
        className="mt-2 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (lesson.trim()) addLesson.mutate();
        }}
      >
        <label htmlFor={`lesson-${job.job_id}`} className="sr-only">
          Co zmieniamy?
        </label>
        <input
          id={`lesson-${job.job_id}`}
          value={lesson}
          maxLength={300}
          onChange={(e) => setLesson(e.target.value)}
          placeholder="Co zmieniamy? np. „pierwsze CV do 48 h”"
          className="w-0 min-w-0 flex-1 rounded-md border border-border bg-card px-2.5 py-1.5 text-sm focus:ring-2 focus:ring-primary focus:outline-hidden"
        />
        <label htmlFor={`lesson-scope-${job.job_id}`} className="sr-only">
          Dla kogo
        </label>
        <select
          id={`lesson-scope-${job.job_id}`}
          value={scope}
          onChange={(e) => setScope(e.target.value as LessonScope)}
          className="rounded-md border border-border bg-card px-2 py-1.5 text-sm"
        >
          {LESSON_SCOPES.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
        <Button type="submit" size="sm" disabled={!lesson.trim() || addLesson.isPending}>
          Zapisz wniosek
        </Button>
      </form>
      {askOpen ? <ClientQuestionDialog jobId={job.job_id} onClose={() => setAskOpen(false)} /> : null}
    </article>
  );
}

function ClientQuestionDialog({ jobId, onClose }: { jobId: number; onClose: () => void }) {
  const { showSuccess, showError } = useToast();
  const query = useQuery({
    queryKey: ["insights", "lost-review", "client-question", jobId],
    queryFn: () => lostReviewApi.clientQuestion(jobId),
  });
  const text = query.data ? `${query.data.subject}\n\n${query.data.body}` : "";
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      showSuccess("Skopiowano. Wklej do maila ze swojej skrzynki.");
    } catch {
      showError("Nie udało się skopiować — zaznacz tekst i skopiuj ręcznie.");
    }
  };
  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? null : onClose())}
      title="Pytanie do hiring managera"
      description="Wysyłasz je ze swojej skrzynki. Odpowiedź klienta zaznacz potem jako „Klient powiedział”."
      size="lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Zamknij
          </Button>
          <Button type="button" onClick={() => void copy()} disabled={!query.isSuccess}>
            Kopiuj treść
          </Button>
        </div>
      }
    >
      {query.isPending ? <p className="text-sm text-muted-foreground">Przygotowuję treść…</p> : null}
      {query.isError ? (
        <p className="text-sm text-destructive">
          {apiErrorMessage(query.error, "Nie udało się przygotować pytania.")}
        </p>
      ) : null}
      {query.isSuccess ? (
        <div className="space-y-2 text-sm">
          <p>
            <span className="font-semibold">Temat:</span> {query.data.subject}
          </p>
          <pre className="whitespace-pre-wrap rounded-md border border-border bg-muted/40 p-3 font-sans text-sm">
            {query.data.body}
          </pre>
        </div>
      ) : null}
    </AppModal>
  );
}
