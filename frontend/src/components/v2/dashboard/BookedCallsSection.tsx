"use client";

/**
 * „Umówione telefony” w panelu „Czeka na Ciebie” (decyzja Artura 03.11.2026):
 * od najstarszego terminu, zaległe na górze. Osoba znika stąd sama po zapisie
 * screeningu albo po ruchu karty.
 */

import Link from "next/link";
import { useState } from "react";
import { PhoneCall } from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { ScreeningCallForm } from "@/components/v2/recruitment/ScreeningCallControl";
import type { BookedCallRow } from "@/lib/api/boardTasks";
import { countPl } from "@/lib/plural-pl";
import { callTone, callWhen, type CallTone } from "@/lib/screening-call";
import { cn } from "@/lib/utils";

const ROWS = 6;

const TONE_CLASS: Record<CallTone, string> = {
  overdue: "bg-destructive-muted text-destructive-muted-foreground",
  today: "bg-primary text-primary-foreground",
  later: "bg-primary/10 text-primary",
};

export function BookedCallsSection({ rows }: { rows: BookedCallRow[] }) {
  const [expanded, setExpanded] = useState(false);
  const [moving, setMoving] = useState<BookedCallRow | null>(null);
  if (rows.length === 0) return null;
  const now = new Date();
  const overdue = rows.filter((row) => callTone(row.start_time, now) === "overdue").length;
  const shown = expanded ? rows : rows.slice(0, ROWS);

  return (
    <section aria-label="Umówione telefony" className="min-w-0 lg:col-span-3">
      <header className="mb-1 flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-semibold">Umówione telefony</h3>
        <span className="rounded-full bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
          {rows.length}
        </span>
        {overdue > 0 ? (
          <span className="rounded-full bg-destructive/10 px-2 text-xs font-medium text-destructive">
            {countPl(overdue, "zaległy", "zaległe", "zaległych")}
          </span>
        ) : null}
      </header>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {shown.map((row) => {
          const tone = callTone(row.start_time, now);
          return (
            <li
              key={row.event_id}
              className="grid grid-cols-[minmax(0,1fr)] items-center gap-x-3 gap-y-1.5 px-3 py-2 md:grid-cols-[minmax(0,1fr)_auto]"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/jobs/${row.job_id}?candidate=${row.candidate_id}`}
                    className="truncate text-sm font-medium hover:underline"
                  >
                    {row.candidate_name}
                  </Link>
                  <span
                    className={cn(
                      "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium",
                      TONE_CLASS[tone],
                    )}
                  >
                    {callWhen(row.start_time, now)}
                  </span>
                </div>
                <p className="truncate text-xs text-muted-foreground">
                  {row.job_working_title || row.job_title}
                  {row.note ? ` · „${row.note}”` : ""}
                </p>
              </div>
              <div className="flex gap-1.5">
                <Link
                  href={`/jobs/${row.job_id}?candidate=${row.candidate_id}`}
                  className={buttonVariants({
                    size: "sm",
                    variant: tone === "later" ? "outline" : "primary",
                  })}
                  aria-label={`Otwórz panel: ${row.candidate_name}`}
                >
                  <PhoneCall className="h-3.5 w-3.5" aria-hidden /> Otwórz
                </Link>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setMoving(row)}
                  aria-label={`Przełóż telefon: ${row.candidate_name}`}
                >
                  Przełóż
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      {rows.length > ROWS ? (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? "Zwiń" : `Pokaż wszystkie (${rows.length})`}
        </button>
      ) : null}
      <Dialog open={moving != null} onOpenChange={(open) => !open && setMoving(null)}>
        <DialogContent className="max-w-md p-5">
          <DialogTitle className="text-base">{moving?.candidate_name}</DialogTitle>
          {moving ? (
            <ScreeningCallForm
              candidateId={moving.candidate_id}
              jobId={moving.job_id}
              call={{
                event_id: moving.event_id,
                start_time: moving.start_time,
                note: moving.note,
              }}
              onDone={() => setMoving(null)}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </section>
  );
}
