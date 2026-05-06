"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Briefcase, Sparkles } from "lucide-react";
import { marketplaceApi, MarketplaceMatch } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  candidateId: number;
}

function scoreColor(score: number): string {
  if (score >= 90) return "text-green-700 bg-green-100 border-green-200";
  if (score >= 80) return "text-primary bg-primary/15 border-primary/20";
  if (score >= 70) return "text-amber-700 bg-amber-100 border-amber-200";
  return "text-muted-foreground bg-muted border-border";
}

export function CandidateMatchesExpansion({ candidateId }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["marketplace-matches", candidateId],
    queryFn: () => marketplaceApi.matches(candidateId).then((r) => r.data),
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
        <Loader2 className="w-4 h-4 animate-spin" />
        Liczę top dopasowań…
      </div>
    );
  }

  if (error) {
    return (
      <p className="py-6 text-sm text-destructive">
        Błąd ładowania matchów.
      </p>
    );
  }

  const matches = data?.matches ?? [];
  if (matches.length === 0) {
    return (
      <div className="py-6 text-sm text-muted-foreground dark:text-muted-foreground flex items-center gap-2">
        <Sparkles className="w-4 h-4" />
        Brak aktualnych dopasowań dla tego kandydata.
      </div>
    );
  }

  return (
    <div className="py-3 space-y-2">
      <p className="text-xs text-muted-foreground dark:text-muted-foreground uppercase tracking-wide font-semibold px-2">
        Top {matches.length} aktualnych dopasowań
      </p>
      {matches.map((m: MarketplaceMatch) => (
        <Link
          key={m.job_id}
          href={`/jobs/${m.job_id}`}
          className="flex items-start gap-3 p-3 rounded-lg bg-card dark:bg-muted border border-border dark:border-border hover:border-teal-300 hover:shadow-sm transition-all"
        >
          <div className="w-8 h-8 rounded-lg bg-teal-50 text-teal-600 flex items-center justify-center flex-shrink-0">
            <Briefcase className="w-4 h-4" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm font-semibold text-foreground dark:text-foreground truncate">
                {m.title}
              </p>
              {m.seniority && (
                <span className="text-xs text-muted-foreground">
                  {m.seniority}
                </span>
              )}
            </div>
            {(m.matching_must.length > 0 || m.gap_must.length > 0) && (
              <div className="flex items-center gap-1 mt-1 flex-wrap">
                {m.matching_must.slice(0, 4).map((s) => (
                  <span
                    key={`m-${s}`}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-green-50 text-green-700 border border-green-100"
                  >
                    ✓ {s}
                  </span>
                ))}
                {m.gap_must.slice(0, 3).map((s) => (
                  <span
                    key={`g-${s}`}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-destructive/10 text-destructive border border-red-100"
                  >
                    × {s}
                  </span>
                ))}
              </div>
            )}
          </div>
          <span
            className={cn(
              "text-xs font-bold px-2 py-1 rounded-full border flex-shrink-0",
              scoreColor(m.total_score)
            )}
          >
            {Math.round(m.total_score)}/100
          </span>
        </Link>
      ))}
    </div>
  );
}
