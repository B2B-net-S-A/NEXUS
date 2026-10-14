"use client";

/**
 * „+1 rekrutacja” na karcie Tablicy (14.10.2026, makieta A2): ta sama osoba
 * czeka też w „Nowych”/„Screeningu” innej rekrutacji. Okienko wymienia te
 * rekrutacje i prowadzi do karty osoby w każdej z nich. Dane: `other_open_jobs`
 * z `GET /api/pipeline/kanban/{id}` (`services/also_fits.py`).
 */

import Link from "next/link";
import { Layers } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

import type { KanbanItem, OtherOpenJob } from "./kanban-shared";

const COLUMN_LABEL: Record<string, string> = { new: "Nowi", screening: "Screening" };

/** Kolumny, w których znacznik ma sens: tam robi się screening. */
const CHIP_COLUMNS = new Set(["new", "screening"]);

export function otherJobsChipLabel(count: number): string {
  return count === 1 ? "+1 rekrutacja" : count < 5 ? `+${count} rekrutacje` : `+${count} rekrutacji`;
}

export function showsOtherJobsChip(item: KanbanItem, boardKey: string | null): boolean {
  return Boolean(boardKey && CHIP_COLUMNS.has(boardKey) && item.other_open_jobs?.length);
}

export function OtherJobsChip({
  item,
  fullName,
  className,
}: {
  item: KanbanItem;
  fullName: string;
  className?: string;
}) {
  const jobs: OtherOpenJob[] = item.other_open_jobs ?? [];
  if (jobs.length === 0) return null;
  const firstName = fullName.split(" ")[0] || fullName;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="card-other-jobs-chip"
          onClick={(e) => e.stopPropagation()}
          className={cn(
            "inline-flex items-center gap-0.5 rounded bg-info-muted px-1 text-[10px] font-semibold text-info-muted-foreground hover:ring-1 hover:ring-current focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
          aria-label={`${otherJobsChipLabel(jobs.length)} — gdzie jeszcze czeka ${fullName}`}
        >
          <Layers className="h-2.5 w-2.5" aria-hidden="true" />
          {otherJobsChipLabel(jobs.length)}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-80 p-3 text-sm"
        // Okienko jest w portalu, ale zdarzenia Reacta idą do karty — klik
        // w treść nie może otwierać panelu osoby.
        onClick={(e) => e.stopPropagation()}
      >
        <p className="font-semibold text-foreground">
          {firstName} czeka też w {jobs.length === 1 ? "1 innej rekrutacji" : `${jobs.length} innych rekrutacjach`}
        </p>
        <ul className="mt-2 space-y-1.5">
          {jobs.map((job) => (
            <li key={job.job_id} className="rounded-md bg-muted/60 px-2.5 py-1.5">
              <p className="text-sm">
                <span className="font-semibold text-foreground">{job.title}</span>
                {job.client_name ? <span className="text-muted-foreground"> · {job.client_name}</span> : null}
              </p>
              <p className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>{COLUMN_LABEL[job.column] ?? job.column}</span>
                <Link
                  href={`/jobs/${job.job_id}?candidate=${item.candidate_id}`}
                  className="font-semibold text-primary hover:underline"
                >
                  Otwórz kartę
                </Link>
              </p>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
