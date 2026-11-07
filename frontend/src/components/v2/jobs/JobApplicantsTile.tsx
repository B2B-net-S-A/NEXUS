"use client";

/**
 * „Aplikacje” — wszyscy, którzy aplikowali na ogłoszenie tej rekrutacji
 * (07.11.2026, makiety https://claude.ai/artifact/JMTL5qwBym7Twd2dU1uYsb).
 *
 * „Nowi” pokazują głównie pasujących (aplikujący z brakiem „musi mieć” są
 * zwinięci), a tu jest pełna lista ze wszystkich kanałów: strona kariery,
 * przekierowanie i formularz portalu. Przy każdej osobie: gdzie jest teraz
 * w tej rekrutacji i do jakich innych otwartych rekrutacji ma propozycję.
 * Serwer: `GET /api/jobs/{id}/applicants` (`services/job_applicants.py`).
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { stageLabel } from "@/lib/cv-generator";

export interface JobApplicant {
  candidate_id: number;
  name: string | null;
  channel: string;
  applied_at: string | null;
  stage: string | null;
  in_job: boolean;
  also_fits: { job_id: number; title: string; score: number | null }[];
}

export const jobApplicantsKey = (jobId: number) => ["job-applicants", jobId] as const;

async function fetchApplicants(jobId: number, signal?: AbortSignal) {
  const { data } = await api.get<{ total: number; items: JobApplicant[] }>(
    `/api/jobs/${jobId}/applicants`,
    { signal },
  );
  return data;
}

type Filter = "in_job" | "all";

function dateLabel(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit" });
}

/** Sam wygląd listy — bez zapytań (test). */
export function JobApplicantsList({ items }: { items: readonly JobApplicant[] }) {
  const [filter, setFilter] = useState<Filter>("in_job");
  const inJob = useMemo(() => items.filter((i) => i.in_job), [items]);
  const shown = filter === "in_job" ? inJob : items;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filtr aplikujących">
        {(
          [
            ["in_job", `W tej rekrutacji · ${inJob.length}`],
            ["all", `Wszyscy · ${items.length}`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={filter === key}
            data-testid={`applicants-filter-${key}`}
            onClick={() => setFilter(key)}
            className={
              filter === key
                ? "rounded-full bg-primary px-2.5 py-0.5 text-xs font-semibold text-primary-foreground"
                : "rounded-full border border-border px-2.5 py-0.5 text-xs font-medium text-muted-foreground hover:text-foreground"
            }
          >
            {label}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {filter === "in_job"
            ? "Nikt z aplikujących nie jest teraz w tej rekrutacji — zobacz „Wszyscy”."
            : "Nikt jeszcze nie aplikował na ogłoszenie tej rekrutacji."}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm" data-testid="applicants-table">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-1.5 pr-3 font-medium">Osoba</th>
                <th className="py-1.5 pr-3 font-medium">Kanał · data</th>
                <th className="py-1.5 pr-3 font-medium">Gdzie jest teraz</th>
                <th className="py-1.5 font-medium">Pasuje też do</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((row) => (
                <tr key={row.candidate_id} className="border-t border-border align-top">
                  <td className="py-1.5 pr-3">
                    <Link href={`/candidates/${row.candidate_id}`} className="font-medium text-foreground hover:underline">
                      {row.name ?? `Osoba ${row.candidate_id}`}
                    </Link>
                  </td>
                  <td className="py-1.5 pr-3 text-muted-foreground">
                    {row.channel} · {dateLabel(row.applied_at)}
                  </td>
                  <td className="py-1.5 pr-3">
                    {row.in_job && row.stage ? stageLabel(row.stage) : (
                      <span className="text-muted-foreground">poza rekrutacją</span>
                    )}
                  </td>
                  <td className="py-1.5">
                    {row.also_fits.length === 0 ? (
                      <span className="text-muted-foreground">—</span>
                    ) : (
                      <span className="flex flex-wrap gap-1">
                        {row.also_fits.map((fit) => (
                          <Link
                            key={fit.job_id}
                            href={`/jobs/${fit.job_id}`}
                            data-testid="applicant-also-fits"
                            className="rounded bg-success-muted px-1.5 py-px text-[11px] font-medium text-success-muted-foreground hover:underline"
                          >
                            {fit.title}
                            {fit.score != null ? ` · ${Math.round(fit.score)}` : ""}
                          </Link>
                        ))}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function JobApplicantsTile({ jobId }: { jobId: number }) {
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: jobApplicantsKey(jobId),
    queryFn: ({ signal }) => fetchApplicants(jobId, signal),
    staleTime: 60_000,
  });
  // Bez aplikacji kafla nie ma — przy 1280 px nagłówek jest ciasny.
  if (query.isSuccess && query.data.total === 0) return null;
  const count = query.isSuccess ? query.data.total : query.isError ? "—" : "…";
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="source-tile-applicants"
        title="Wszyscy, którzy aplikowali na ogłoszenie tej rekrutacji (ostatnie 90 dni)"
        className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-primary/25 bg-card px-2.5 text-[13px] font-semibold text-foreground transition-colors hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9"
      >
        Aplikacje
        <span className="font-bold tabular-nums" data-testid="source-tile-applicants-count">
          {count}
        </span>
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Aplikacje z ogłoszenia</DialogTitle>
            <DialogDescription>
              Strona kariery, JustJoin.IT i inne portale, ostatnie 90 dni. W „Nowych” stoją głównie osoby z kompletem „musi mieć”.
            </DialogDescription>
          </DialogHeader>
          <DialogBody>
            {query.isError ? (
              <p className="text-sm text-destructive">
                {apiErrorMessage(query.error, "Nie udało się wczytać aplikacji. Spróbuj ponownie.")}
              </p>
            ) : query.isSuccess ? (
              <JobApplicantsList items={query.data.items} />
            ) : (
              <p className="text-sm text-muted-foreground">Wczytuję…</p>
            )}
          </DialogBody>
        </DialogContent>
      </Dialog>
    </>
  );
}
