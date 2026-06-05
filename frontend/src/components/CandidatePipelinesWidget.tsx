"use client";

import Link from "next/link";
import { Briefcase, Clock, Loader2, Star } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { phase3Api, CandidatePipelineRow } from "@/lib/api";
import { ChampionCard } from "./ChampionCard";
import type { EmploymentInfo } from "@/components/v2/CandidateHighlights";

interface Props {
  candidateId: number;
  employment?: EmploymentInfo;
}

// Współdzielony klucz cache — invalidowany m.in. po „Usuń z rekrutacji"
// (zakładka Rekrutacje), żeby panel po prawej był spójny z listą po lewej.
export const candidatePipelinesQueryKey = (candidateId: number) =>
  ["candidate-pipelines", candidateId] as const;

const CATEGORY_COLORS: Record<string, string> = {
  internal: "bg-primary/15 text-primary border-primary/30",
  external: "bg-amber-100 text-amber-700 border-amber-300",
  terminal: "bg-slate-100 text-slate-700 border-slate-300",
};

export function CandidatePipelinesWidget({ candidateId, employment }: Props) {
  const { data: rows = [], isLoading: loading } = useQuery<CandidatePipelineRow[]>({
    queryKey: candidatePipelinesQueryKey(candidateId),
    queryFn: () =>
      phase3Api.candidatePipelines(candidateId).then((r) => r.data.pipelines),
    enabled: Number.isFinite(candidateId),
  });

  if (loading) {
    return (
      <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4 flex justify-center">
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (rows.length === 0) return null;

  const active = rows.filter((r) => !r.is_terminal);
  const closed = rows.filter((r) => r.is_terminal);

  return (
    <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
      <h3 className="font-medium text-foreground dark:text-foreground mb-3 flex items-center gap-2">
        <Briefcase className="w-4 h-4 text-primary" />
        W jakich pipeline&apos;ach jest ten kandydat? ({rows.length})
      </h3>

      {active.length > 0 && (
        <>
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
            Aktywne ({active.length})
          </div>
          <ul className="space-y-1.5 mb-3">
            {active.map((p) => (
              <PipelineRow key={p.candidate_stage_id} row={p} employment={employment} />
            ))}
          </ul>
        </>
      )}
      {closed.length > 0 && (
        <>
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-1">
            Zamknięte ({closed.length})
          </div>
          <ul className="space-y-1.5">
            {closed.map((p) => (
              <PipelineRow key={p.candidate_stage_id} row={p} muted employment={employment} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function PipelineRow({
  row,
  muted,
  employment,
}: {
  row: CandidatePipelineRow;
  muted?: boolean;
  employment?: EmploymentInfo;
}) {
  // Show Champion card once the candidate advances to an external stage —
  // recruiter should have filled screening before moving into cv_sent+.
  const showChampion =
    row.stage_category === "external" || row.stage_category === "terminal";
  return (
    <li
      className={`flex flex-col gap-2 rounded-md border border-border dark:border-border px-3 py-2 ${
        muted ? "opacity-70" : "bg-muted dark:bg-card/40"
      }`}
    >
      <div className="flex items-center gap-3">
        <Link
          href={`/jobs/${row.job_id}`}
          className="font-medium text-sm text-foreground dark:text-foreground hover:underline truncate flex-1 min-w-0"
        >
          {row.job_title ?? `#${row.job_id}`}
        </Link>

        {row.stage_category && (
          <span
            className={`text-xs px-2 py-0.5 rounded-full border ${CATEGORY_COLORS[row.stage_category] || ""}`}
          >
            {row.stage_name}
          </span>
        )}

        {row.rating !== null && row.rating !== undefined && (
          <span className="flex items-center gap-0.5 text-xs text-amber-600">
            <Star className="w-3 h-3 fill-current" />
            {row.rating}/5
          </span>
        )}

        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          <Clock className="w-3 h-3" />
          {row.days_in_stage}d
        </span>
      </div>

      {showChampion && (
        <ChampionCard stageId={row.candidate_stage_id} employment={employment} />
      )}
    </li>
  );
}
