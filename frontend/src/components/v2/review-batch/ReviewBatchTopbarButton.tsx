"use client";

import Link from "next/link";
import { ListChecks } from "lucide-react";

import { useReviewBatchStatus } from "@/lib/api/reviewBatch";

/**
 * Licznik porcji dnia w pasku (makieta M5). Widać go tylko rekruterowi, który
 * nie zrobił jeszcze minimum — po minimum znika, żeby nie zajmował miejsca przy
 * 1280 px.
 */
export function ReviewBatchTopbarButton() {
  const { data } = useReviewBatchStatus();
  if (!data?.enabled || !data.applies || data.met) return null;
  const overdue = data.overdue_screenings ?? 0;
  const label =
    overdue > 0 && data.remaining === 0
      ? `Screeningi po terminie: ${overdue}`
      : `Porcja od Nexusa: ${Math.min(data.done_today, data.required)} z ${data.required} decyzji`;
  return (
    <Link
      href="/porcja"
      className="hit-area inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg bg-warning px-2.5 text-xs font-bold text-warning-foreground hover:bg-warning/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label={label}
      title={label}
      data-testid="review-batch-topbar"
      data-tour="review-batch.topbar"
    >
      <ListChecks className="h-3.5 w-3.5" aria-hidden="true" />
      <span className="tabular-nums">
        {Math.min(data.done_today, data.required)}/{data.required}
      </span>
    </Link>
  );
}
