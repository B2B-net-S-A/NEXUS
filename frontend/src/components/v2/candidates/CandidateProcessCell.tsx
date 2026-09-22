"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { cn, formatRelativeTime } from "@/lib/utils";
import {
  activeRecruitments,
  processCell,
  stageLabel,
  type CandidateRowAvailabilitySource,
  type CandidateRowRecruitment,
} from "@/components/v2/candidates/candidate-row-format";

const CLOSE_DELAY_MS = 150;

/**
 * Kolumna „W procesie”: w komórce skrót („2 procesy · CV wysłane”),
 * po najechaniu (albo kliknięciu / fokusie — dotyk i klawiatura) lista
 * rekrutacji, w których osoba bierze udział: tytuł, klient, etap i kiedy
 * był ostatni ruch. Każda pozycja prowadzi do rekrutacji. Zamknięte
 * rekrutacje (etap końcowy) się nie liczą — tak samo jak skrót.
 */
export function CandidateProcessCell({
  candidateName,
  employment,
  recruitments,
}: {
  candidateName: string;
  employment: CandidateRowAvailabilitySource["employment"];
  recruitments: readonly CandidateRowRecruitment[] | null | undefined;
}) {
  const [open, setOpen] = useState(false);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
  }, []);

  const cell = processCell(employment, recruitments);
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
            "max-w-full truncate rounded-sm text-left text-sm underline decoration-dotted decoration-muted-foreground/60 underline-offset-4",
            "hover:text-primary focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
            cell.tone === "employed" ? "font-medium text-warning-muted-foreground" : "text-foreground",
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
          {active.length > 0
            ? `Rekrutacje w toku (${active.length})`
            : "Brak rekrutacji w toku"}
        </div>
        {cell.tone === "employed" && (
          <p className="border-b border-border px-3 py-2 text-sm font-medium text-warning-muted-foreground">
            {cell.text}
          </p>
        )}
        {active.length > 0 && (
          <ul className="max-h-72 overflow-y-auto py-1">
            {active.map((r) => (
              <li key={r.job_id}>
                <Link
                  href={`/jobs/${r.job_id}`}
                  className="block px-3 py-2 hover:bg-muted focus-visible:bg-muted focus-visible:outline-hidden"
                >
                  <span className="block truncate text-sm font-medium text-foreground">{r.job_title}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {[r.client_name, stageLabel(r.stage), r.moved_at ? formatRelativeTime(r.moved_at) : null]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </PopoverContent>
    </Popover>
  );
}
