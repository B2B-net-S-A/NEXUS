"use client";

import { useEffect, useRef, useState } from "react";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { cn, formatRelativeTime } from "@/lib/utils";
import {
  activeRecruitments,
  processCell,
  stageLabel,
  type CandidateRowRecruitment,
} from "@/components/v2/candidates/candidate-row-format";
import { JobNameLabel } from "@/components/v2/jobs/JobNameLabel";
import { candidateJobNames } from "@/lib/job-name-text";

const CLOSE_DELAY_MS = 150;

/**
 * Kolumna „W procesie”: w komórce skrót („2 procesy · CV wysłane”),
 * po najechaniu (albo kliknięciu / fokusie — dotyk i klawiatura) lista
 * rekrutacji, w których osoba bierze udział: numer u klienta i tytuł jak
 * w nagłówku rekrutacji, klient, etap i kiedy był ostatni ruch. Każda pozycja prowadzi do rekrutacji. Zamknięte
 * rekrutacje (etap końcowy) się nie liczą — tak samo jak skrót.
 */
export function CandidateProcessCell({
  candidateName,
  recruitments,
}: {
  candidateName: string;
  recruitments: readonly CandidateRowRecruitment[] | null | undefined;
}) {
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
  }, []);

  const cell = processCell(recruitments);
  const active = activeRecruitments(recruitments);
  if (!cell) return <span className="text-muted-foreground">—</span>;

  const show = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setOpen(true);
  };
  const hideSoon = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpen(false), CLOSE_DELAY_MS);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <button
          type="button"
          aria-expanded={open}
          aria-label={`W procesie: ${candidateName} — ${cell.text}`}
          onMouseEnter={show}
          onMouseLeave={hideSoon}
          onFocus={show}
          onClick={(e) => {
            e.stopPropagation();
            // Po najechaniu lista już jest otwarta — klik jej nie zamyka
            // (przełącznik zamykałby ją pod kursorem). Zamyka Esc / klik obok.
            show();
          }}
          className={cn(
            "max-w-full truncate rounded-sm text-left text-sm text-foreground underline decoration-dotted decoration-muted-foreground/60 underline-offset-4",
            "hover:text-primary focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
          )}
        >
          {cell.text}
        </button>
      </PopoverAnchor>
      <PopoverContent
        align="start"
        className="w-80 p-0"
        onMouseEnter={show}
        onMouseLeave={hideSoon}
        onOpenAutoFocus={(e) => e.preventDefault()}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-border px-3 py-2 text-xs font-semibold text-muted-foreground">
          Rekrutacje w toku ({active.length})
        </div>
        <ul className="max-h-72 overflow-y-auto py-1">
          {active.map((r) => (
            <li
              key={r.job_id}
              className="relative px-3 py-2 hover:bg-muted focus-within:bg-muted"
            >
              {/* Cały wiersz prowadzi do rekrutacji; numer u klienta kopiuje. */}
              <JobNameLabel
                job={candidateJobNames(r)}
                href={`/jobs/${r.job_id}`}
                stretched
                titleClassName="text-sm font-medium text-foreground"
              />
              <span className="block truncate text-xs text-muted-foreground">
                {[r.client_name, stageLabel(r.stage), r.moved_at ? formatRelativeTime(r.moved_at) : null]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
