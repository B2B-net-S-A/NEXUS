"use client";

// „Prepy przed rozmową u klienta” (0370) — brak prepu, prep słaby albo bez
// nagrania; wiersz prowadzi do karty kandydata w kalendarzu. Nic nie blokuje —
// to przypomnienie, nie bramka.
//
// Ta sama lista w panelu „Czeka na Ciebie” i w kafelku „Do uzupełnienia”
// (23.10.2026, prośba Olafa): gdy kafelek stoi na pulpicie, prepy są tylko w nim.

import Link from "next/link";
import { useState } from "react";
import { AlertTriangle } from "lucide-react";

import { prepAttentionLabel, prepAttentionLink, type PrepAttentionRow } from "@/lib/api/boardTasks";
import { formatDayLabel, formatTime } from "@/lib/interview-cycle";

import { BOARD_TASKS_ROWS, Section } from "./BoardTasksSection";

function prepRowKey(row: PrepAttentionRow): string {
  return `${row.interview_event_id}-${row.prep_no}-${row.reason}`;
}

/** Pilny wiersz (rozmowa tuż-tuż) na czerwono, reszta na bursztynowo. */
function prepReasonClass(row: PrepAttentionRow): string {
  return row.urgent
    ? "bg-destructive/10 text-destructive"
    : "bg-warning-muted text-warning-muted-foreground";
}

export function PrepAttentionSection({ rows }: { rows: PrepAttentionRow[] }) {
  const [expanded, setExpanded] = useState(false);
  if (rows.length === 0) return null;
  const shown = expanded ? rows : rows.slice(0, BOARD_TASKS_ROWS);
  return (
    <Section
      title="Prepy przed rozmową u klienta"
      hint="Brak prepu, prep po rozmowie, słaby albo bez nagrania — nic nie blokuje, ale warto to nadrobić przed rozmową."
      count={rows.length}
      expanded={expanded}
      onToggle={() => setExpanded((prev) => !prev)}
    >
      {shown.map((row) => (
        <li
          key={prepRowKey(row)}
          className={`flex items-center gap-2 px-3 py-2 ${row.urgent ? "bg-destructive/5" : ""}`}
        >
          <div className="min-w-0 flex-1">
            <Link
              href={prepAttentionLink(row)}
              className="block truncate text-sm font-medium hover:underline"
            >
              {row.candidate_name}
            </Link>
            <p className="truncate text-xs text-muted-foreground">
              {row.job_title}
            </p>
            <p className="text-xs tabular-nums text-muted-foreground">
              Rozmowa u klienta: {formatDayLabel(row.interview_start)}, {formatTime(row.interview_start)}
            </p>
          </div>
          <span
            className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${prepReasonClass(row)}`}
          >
            {row.urgent && <AlertTriangle className="h-3 w-3" aria-hidden />}
            {prepAttentionLabel(row)}
            {row.urgent && <span className="sr-only"> — pilne</span>}
          </span>
        </li>
      ))}
    </Section>
  );
}
