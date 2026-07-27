"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import type { ActiveConsultantItem } from "@/types/client-profile";
import { daysToEndBadgeColor, formatDate, formatPLN } from "@/types/client-profile";

interface Props {
  consultant: ActiveConsultantItem;
  actions?: React.ReactNode;
}

export function ConsultantRow({ consultant, actions }: Props) {
  const c = consultant.candidate;
  const initials = c.name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();

  return (
    <div className="group bg-card dark:bg-muted border border-border dark:border-border rounded-xl p-4 hover:border-purple-300 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          {c.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={c.avatar_url}
              alt={c.name}
              className="w-9 h-9 rounded-full object-cover shrink-0"
            />
          ) : (
            <div className="w-9 h-9 bg-emerald-100 dark:bg-emerald-900/30 rounded-full flex items-center justify-center shrink-0">
              <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">{initials}</span>
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <Link
                href={`/candidates/${c.id}`}
                className="text-sm font-semibold text-foreground dark:text-foreground hover:text-purple-600 truncate"
              >
                {c.name}
              </Link>
              {c.competence_category && (
                <span className="px-1.5 py-0.5 bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground rounded text-xs">
                  {c.competence_category}
                </span>
              )}
              {consultant.days_to_end != null && (
                <span className={cn("px-1.5 py-0.5 rounded text-xs font-semibold", daysToEndBadgeColor(consultant.days_to_end))}>
                  {consultant.days_to_end < 0
                    ? `po terminie`
                    : `kończy się za ${consultant.days_to_end}d`}
                </span>
              )}
            </div>

            <div className="flex flex-wrap gap-3 mt-1.5 text-xs text-muted-foreground dark:text-muted-foreground">
              {consultant.job_title ? (
                consultant.job_id ? (
                  <Link href={`/jobs/${consultant.job_id}`} className="hover:text-purple-600">
                    {consultant.job_title}
                  </Link>
                ) : (
                  <span>{consultant.job_title}</span>
                )
              ) : (
                <span className="italic">brak powiązanej oferty</span>
              )}
              <span>
                {formatDate(consultant.start_date)}
                {consultant.end_date && ` → ${formatDate(consultant.end_date)}`}
              </span>
              {consultant.monthly_rate_client != null && (
                <span className="font-medium text-foreground dark:text-muted-foreground">
                  {formatPLN(consultant.monthly_rate_client)}/mc
                </span>
              )}
              {consultant.monthly_margin != null && (
                <span className="text-emerald-600 dark:text-emerald-400">
                  marża {formatPLN(consultant.monthly_margin)}
                </span>
              )}
            </div>
          </div>
        </div>

        {actions && <div className="flex items-center gap-1 shrink-0">{actions}</div>}
      </div>
    </div>
  );
}
