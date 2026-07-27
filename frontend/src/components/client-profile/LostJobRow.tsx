"use client";

import Link from "next/link";
import { XCircle, Users } from "lucide-react";
import type { LostJobItem } from "@/types/client-profile";
import { formatDate, JOB_CLOSE_REASONS } from "@/types/client-profile";

const REASON_LABELS = Object.fromEntries(
  JOB_CLOSE_REASONS.map((r) => [r.value, r.label])
);

interface Props {
  lost: LostJobItem;
  actions?: React.ReactNode;
}

export function LostJobRow({ lost, actions }: Props) {
  const reasonLabel = lost.close_reason
    ? REASON_LABELS[lost.close_reason] ?? lost.close_reason
    : "Nie określono";

  return (
    <div className="group bg-card dark:bg-muted border border-border dark:border-border rounded-xl p-4 hover:border-destructive/20 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <div className="w-9 h-9 bg-destructive/10 dark:bg-red-900/30 rounded-lg flex items-center justify-center shrink-0">
            <XCircle className="w-4 h-4 text-destructive dark:text-red-300" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <Link
                href={`/jobs/${lost.job_id}`}
                className="text-sm font-semibold text-foreground dark:text-muted-foreground hover:text-purple-600 truncate"
              >
                {lost.title}
              </Link>
              <span className="px-1.5 py-0.5 bg-destructive/10 dark:bg-red-900/30 text-destructive dark:text-red-300 rounded text-xs font-semibold">
                {reasonLabel}
              </span>
            </div>
            <div className="flex flex-wrap gap-3 mt-1.5 text-xs text-muted-foreground dark:text-muted-foreground">
              <span>zamknięta {formatDate(lost.closed_at)}</span>
              <span className="flex items-center gap-1">
                <Users className="w-3 h-3" />
                {lost.candidate_count_reached} w pipeline
              </span>
            </div>
            {lost.close_notes && (
              <p className="text-xs text-muted-foreground dark:text-muted-foreground italic mt-2 line-clamp-2">
                {lost.close_notes}
              </p>
            )}
          </div>
        </div>

        {actions && <div className="flex items-center gap-1 shrink-0">{actions}</div>}
      </div>
    </div>
  );
}
