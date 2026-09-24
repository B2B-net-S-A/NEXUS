"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  insightsTeamSignalsApi,
  insightsTeamSignalsQueryKeys,
} from "@/lib/insights-team-api";
import { SectionError } from "@/components/insights/sections/_shared";
import { PanelLoading } from "./ViewKit";

/** Raport „Rekrutacje bez ruchu": opublikowane, bez ruchu w pipeline od 14 dni. */
export function StaleJobsReport() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: insightsTeamSignalsQueryKeys.staleJobs(),
    queryFn: () => insightsTeamSignalsApi.staleJobs(),
  });
  if (isPending) return <PanelLoading />;
  if (isError || !data) {
    return (
      <SectionError
        label="Rekrutacje bez ruchu"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }
  if (data.items.length === 0) {
    return (
      <p className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
        Każda opublikowana rekrutacja miała ruch w ostatnich {data.days} dniach.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted-foreground">
        {data.total} opublikowanych rekrutacji bez żadnego ruchu w pipeline od{" "}
        {data.days} dni. Rekrutacja bez kandydatów liczy się od dnia otwarcia.
      </p>
      <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-xs">
        <table className="w-full min-w-[42rem] text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
              <th className="sticky left-0 bg-card px-4 py-2.5 text-left font-semibold">
                Rekrutacja
              </th>
              <th className="px-3 py-2.5 text-left font-semibold">Klient</th>
              <th className="px-3 py-2.5 text-left font-semibold">Prowadzi</th>
              <th className="px-3 py-2.5 text-right font-semibold">Dni bez ruchu</th>
              <th className="px-4 py-2.5 text-right font-semibold">Osób w procesie</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((job) => (
              <tr key={job.job_id} className="border-b border-border/60 last:border-b-0">
                <td className="sticky left-0 bg-card px-4 py-2.5">
                  <Link
                    href={`/jobs/${job.job_id}`}
                    className="font-medium text-primary hover:underline"
                  >
                    {job.title}
                  </Link>
                </td>
                <td className="px-3 py-2.5 text-foreground">{job.client_name ?? "—"}</td>
                <td className="px-3 py-2.5 text-foreground">
                  {job.recruiter_name ?? (
                    <span className="text-muted-foreground">nieprzypisana</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right font-semibold tabular-nums">
                  {job.days_without_move ?? "—"}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums">{job.people}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
