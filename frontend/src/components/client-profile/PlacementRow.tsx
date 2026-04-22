"use client";

import Link from "next/link";
import type { HistoricalPlacementItem } from "@/types/client-profile";
import { formatDate, formatPLN } from "@/types/client-profile";
import { CONTRACT_TERMINATION_REASONS } from "@/lib/api";

const REASON_LABELS = Object.fromEntries(
  CONTRACT_TERMINATION_REASONS.map((r) => [r.value, r.label])
);

interface Props {
  placement: HistoricalPlacementItem;
  actions?: React.ReactNode;
}

export function PlacementRow({ placement, actions }: Props) {
  const c = placement.candidate;
  const initials = c.name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
  const end = placement.terminated_at || placement.end_date;
  const reasonLabel = placement.termination_reason
    ? REASON_LABELS[placement.termination_reason] ?? placement.termination_reason
    : null;

  return (
    <div className="group bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-4 hover:border-purple-300 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          {c.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={c.avatar_url}
              alt={c.name}
              className="w-9 h-9 rounded-full object-cover flex-shrink-0 opacity-75"
            />
          ) : (
            <div className="w-9 h-9 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center flex-shrink-0">
              <span className="text-xs font-semibold text-gray-500 dark:text-gray-300">{initials}</span>
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <Link
                href={`/candidates/${c.id}`}
                className="text-sm font-semibold text-gray-800 dark:text-gray-200 hover:text-purple-600 truncate"
              >
                {c.name}
              </Link>
              {placement.job_title && (
                <span className="text-xs text-gray-500 dark:text-gray-400">· {placement.job_title}</span>
              )}
            </div>
            <div className="flex flex-wrap gap-3 mt-1.5 text-xs text-gray-500 dark:text-gray-400">
              <span>
                {formatDate(placement.start_date)} → {formatDate(end)}
              </span>
              {placement.duration_months != null && (
                <span>{placement.duration_months} mc</span>
              )}
              {placement.total_revenue != null && (
                <span className="font-medium text-gray-700 dark:text-gray-200">
                  {formatPLN(placement.total_revenue)} przychodu
                </span>
              )}
              {reasonLabel && (
                <span className="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded">
                  {reasonLabel}
                </span>
              )}
            </div>
          </div>
        </div>

        {actions && <div className="flex items-center gap-1 flex-shrink-0">{actions}</div>}
      </div>
    </div>
  );
}
