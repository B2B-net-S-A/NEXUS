"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Briefcase, Clock, Loader2, Star } from "lucide-react";
import { phase3Api, CandidatePipelineRow } from "@/lib/api";
import { ChampionCard } from "./ChampionCard";
import type { EmploymentInfo } from "@/components/v2/CandidateHighlights";

interface Props {
  candidateId: number;
  employment?: EmploymentInfo;
}

const CATEGORY_COLORS: Record<string, string> = {
  internal: "bg-blue-100 text-blue-700 border-blue-300",
  external: "bg-amber-100 text-amber-700 border-amber-300",
  terminal: "bg-slate-100 text-slate-700 border-slate-300",
};

export function CandidatePipelinesWidget({ candidateId, employment }: Props) {
  const [rows, setRows] = useState<CandidatePipelineRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await phase3Api.candidatePipelines(candidateId);
        setRows(res.data.pipelines);
      } catch (e) {
        console.error("pipelines load failed:", e);
      } finally {
        setLoading(false);
      }
    })();
  }, [candidateId]);

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4 flex justify-center">
        <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
      </div>
    );
  }

  if (rows.length === 0) return null;

  const active = rows.filter((r) => !r.is_terminal);
  const closed = rows.filter((r) => r.is_terminal);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <h3 className="font-medium text-gray-900 dark:text-gray-100 mb-3 flex items-center gap-2">
        <Briefcase className="w-4 h-4 text-blue-500" />
        W jakich pipeline&apos;ach jest ten kandydat? ({rows.length})
      </h3>

      {active.length > 0 && (
        <>
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">
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
          <div className="text-xs uppercase tracking-wider text-gray-500 mb-1">
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
      className={`flex flex-col gap-2 rounded-md border border-gray-200 dark:border-gray-700 px-3 py-2 ${
        muted ? "opacity-70" : "bg-gray-50 dark:bg-gray-900/40"
      }`}
    >
      <div className="flex items-center gap-3">
        <Link
          href={`/jobs/${row.job_id}`}
          className="font-medium text-sm text-gray-800 dark:text-gray-100 hover:underline truncate flex-1 min-w-0"
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

        <span className="flex items-center gap-1 text-xs text-gray-500">
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
