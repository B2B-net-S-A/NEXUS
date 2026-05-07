"use client";

import { useEffect, useState } from "react";
import { History, Loader2 } from "lucide-react";
import { matchHistoryApi, type MatchHistoryRow } from "@/lib/api";
import { ScoreBreakdownTooltip } from "./ScoreBreakdownTooltip";

interface Props {
  jobId: number;
  candidateId: number;
}

export function MatchHistoryWidget({ jobId, candidateId }: Props) {
  const [rows, setRows] = useState<MatchHistoryRow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancel = false;
    (async () => {
      setLoading(true);
      try {
        const r = await matchHistoryApi.list(jobId, candidateId, 10);
        if (!cancel) setRows(r.data);
      } catch (e) {
        console.error("match history load failed: ", e);
      } finally {
        if (!cancel) setLoading(false);
      }
    })();
    return () => {
      cancel = true;
    };
  }, [jobId, candidateId]);

  const fmt = (iso: string | null) => {
    if (!iso) return "";
    try {
      return new Date(iso).toLocaleString("pl-PL", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return iso;
    }
  };

  const scoreColor = (s: number) => {
    if (s >= 75) return "text-emerald-600";
    if (s >= 50) return "text-primary";
    if (s >= 25) return "text-amber-600";
    return "text-muted-foreground";
  };

  return (
    <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
      <h3 className="font-medium flex items-center gap-2 text-foreground dark:text-foreground mb-3">
        <History className="w-4 h-4 text-primary" />
        Historia match ({rows.length})
      </h3>

      {loading ? (
        <div className="flex justify-center py-4">
          <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Brak zapisanej historii. Uruchom rekomendację z detalu oferty.
        </p>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {rows.map(r => (
            <li
              key={r.id}
              className="flex items-center gap-3 border-t border-border dark:border-border first:border-t-0 pt-1.5"
            >
              <span className="text-xs text-muted-foreground w-32 flex-shrink-0">
                {fmt(r.created_at)}
              </span>
              <span className={`font-semibold ${scoreColor(r.total_score)}`}>
                {r.total_score}/100
              </span>
              {r.breakdown && <ScoreBreakdownTooltip breakdown={r.breakdown} compact />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
