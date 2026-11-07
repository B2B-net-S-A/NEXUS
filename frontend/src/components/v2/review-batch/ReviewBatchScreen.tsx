"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ds/PageHeader";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  addMoreFromNexus,
  invalidateReviewBatch,
  useReviewBatchQueue,
  useReviewBatchStatus,
  type ReviewBatchStatus,
} from "@/lib/api/reviewBatch";

import { ReviewBatchCard } from "./ReviewBatchCard";

/**
 * Ekran „Porcja dnia” (makiety M5, M7, M9; decyzje Artura z 07.11.2026).
 * Rano system daje każdej rekrutacji z rekruterem do 20 osób i dzieli je
 * w zespole. Dopóki rekruter nie podejmie minimum decyzji, ręczne
 * wyszukiwanie zwraca 423. Kolejność narzuca serwer: rekrutacje na zmianę,
 * w każdej od najlepszej osoby.
 */

function progressLabel(status: ReviewBatchStatus): string {
  return `${Math.min(status.done_today, status.required)} / ${status.required}`;
}

function AddMore({ jobId, title }: { jobId: number; title: string }) {
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
              : `W puli nie ma już osób od 65%: ${title}.`,
          );
        } catch (error) {
          showError(apiErrorMessage(error, "Nie udało się dobrać kolejnych osób."));
        } finally {
          setBusy(false);
        }
      }}
    >
      Dodaj 20 kolejnych od Nexusa
    </Button>
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
  const next = queue.data?.items?.[0] ?? null;

  return (
    <div className="mx-auto max-w-3xl p-4 sm:p-6 space-y-4">
      <PageHeader
        title="Porcja dnia od Nexusa"
        density="compact"
        description={
          data.met
            ? "Minimum zrobione. Wyszukiwanie ręczne odblokowane do jutra, 7:00."
            : `Zdecyduj o ${data.required} osobach, zanim zaczniesz szukać ręcznie. Osobę spoza bazy dodasz zawsze.`
        }
        actions={
          <span
            className="rounded-full bg-primary/10 px-3 py-1 text-sm font-semibold text-primary tabular-nums"
            data-testid="review-batch-progress"
          >
            {progressLabel(data)}
            {data.required < data.minimum ? "" : " minimum"} · {data.pending} w porcji
          </span>
        }
      />

      {next ? (
        <ReviewBatchCard key={next.process_id} item={next} onDecided={onDecided} />
      ) : queue.isLoading ? (
        <div className="text-sm text-muted-foreground">Ładowanie osób…</div>
      ) : queue.isError ? (
        <div className="text-sm text-destructive" role="alert">
          {apiErrorMessage(queue.error, "Nie udało się wczytać osób z porcji.")}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground" data-testid="review-batch-empty">
          Porcja przejrzana. Nowa porcja przyjdzie jutro o 7:00.
        </p>
      )}

      {data.jobs.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Czeka na Ciebie</h2>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {data.jobs.map((job) => (
              <li key={job.job_id} className="flex items-center gap-3 px-3 py-2 text-sm">
                <Link href={`/jobs/${job.job_id}`} className="min-w-0 flex-1 truncate hover:underline">
                  {job.p0 ? <span className="mr-1 font-semibold text-destructive">P0</span> : null}
                  {job.title}
                </Link>
                <span className="tabular-nums text-muted-foreground">{job.pending}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {data.team_jobs.some((j) => j.pending === 0) ? (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Przejrzane do końca</h2>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {data.team_jobs
              .filter((j) => j.pending === 0)
              .map((job) => (
                <li key={job.job_id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
                  <Link href={`/jobs/${job.job_id}`} className="min-w-0 flex-1 truncate hover:underline">
                    {job.title}
                  </Link>
                  <AddMore jobId={job.job_id} title={job.title} />
                </li>
              ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
