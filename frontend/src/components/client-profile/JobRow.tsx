"use client";

import Link from "next/link";
import { AlertCircle, Briefcase, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import type { OpenJobItem } from "@/types/client-profile";
import { formatPLN } from "@/types/client-profile";

const PRIORITY_BADGE: Record<string, string> = {
  low: "bg-muted text-muted-foreground dark:bg-muted dark:text-muted-foreground",
  medium: "bg-primary/15 text-primary dark:bg-primary/30 dark:text-primary",
  high: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  urgent: "bg-destructive/15 text-destructive dark:bg-red-900/30 dark:text-red-300",
};

const PRIORITY_LABEL: Record<string, string> = {
  low: "Low",
  medium: "Med",
  high: "High",
  urgent: "Urgent",
};

interface Props {
  job: OpenJobItem;
  actions?: React.ReactNode;
}

export function JobRow({ job, actions }: Props) {
  const salary =
    job.salary_min && job.salary_max
      ? `${formatPLN(job.salary_min)} – ${formatPLN(job.salary_max)}`
      : job.salary_min
        ? `od ${formatPLN(job.salary_min)}`
        : null;

  const stale = job.days_open >= 30;

  return (
    <div className="group bg-card dark:bg-muted border border-border dark:border-border rounded-xl p-4 hover:border-purple-300 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          <div className="w-9 h-9 bg-purple-50 dark:bg-purple-900/30 rounded-lg flex items-center justify-center flex-shrink-0">
            <Briefcase className="w-4 h-4 text-purple-600 dark:text-purple-300" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <Link
                href={`/jobs/${job.id}`}
                className="text-sm font-semibold text-foreground dark:text-foreground hover:text-purple-600 truncate"
              >
                {job.title}
              </Link>
              <span className={cn("px-1.5 py-0.5 rounded text-xs font-semibold", PRIORITY_BADGE[job.priority])}>
                {PRIORITY_LABEL[job.priority]}
              </span>
              {job.seniority && (
                <span className="px-1.5 py-0.5 bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground rounded text-xs font-medium uppercase">
                  {job.seniority}
                </span>
              )}
              {stale && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 bg-destructive/10 dark:bg-red-900/30 text-destructive dark:text-red-300 rounded text-xs font-semibold">
                  <AlertCircle className="w-3 h-3" />
                  {job.days_open}d
                </span>
              )}
            </div>

            <div className="flex flex-wrap gap-3 mt-1.5 text-xs text-muted-foreground dark:text-muted-foreground">
              <span className="flex items-center gap-1">
                <Users className="w-3 h-3" />
                {job.candidate_count} {job.candidate_count === 1 ? "kandydat" : "kandydatów"} w pipeline
              </span>
              {salary && <span>{salary}</span>}
              {!stale && <span>otwarta {job.days_open}d</span>}
              {job.recruiter && <span>· {job.recruiter.name}</span>}
            </div>
          </div>
        </div>

        {actions && <div className="flex items-center gap-1 flex-shrink-0">{actions}</div>}
      </div>
    </div>
  );
}
