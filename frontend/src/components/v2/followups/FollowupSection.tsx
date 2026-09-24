"use client";

/**
 * „Follow-up z kandydatami” w panelu „Czeka na Ciebie” (0371) — makieta A.
 *
 * Tylko osoby, do których dzwonisz TY (termin do końca jutra). Na dole jedna
 * zwinięta linijka o Twoich kandydatach, z którymi follow-up robi ktoś inny —
 * żebyś wiedział(a), że ktoś już się tym zajmuje, zamiast dzwonić drugi raz.
 */

import Link from "next/link";
import { useState } from "react";
import { PhoneCall } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { FollowupRow } from "@/lib/api/candidateFollowups";
import {
  followupDueLabel,
  lastContactLabel,
  processChipLabel,
  shortPersonName,
} from "@/lib/candidate-followup";
import { countPl } from "@/lib/plural-pl";

import { CandidateFollowupDialog, FollowupDuePill } from "./CandidateFollowupDialog";

const ROWS = 6;

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");
}

export interface FollowupSectionProps {
  rows: FollowupRow[];
  others: FollowupRow[];
}

export function FollowupSection({ rows, others }: FollowupSectionProps) {
  const [expanded, setExpanded] = useState(false);
  const [openFor, setOpenFor] = useState<number | null>(null);
  if (rows.length === 0) return null;
  const overdue = rows.filter((r) => r.state === "overdue").length;
  const shown = expanded ? rows : rows.slice(0, ROWS);

  return (
    <section aria-label="Follow-up z kandydatami" className="min-w-0 lg:col-span-3">
      <header className="mb-1 flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-semibold">Follow-up z kandydatami</h3>
        <span className="rounded-full bg-primary/10 px-1.5 text-xs font-semibold tabular-nums text-primary">
          {rows.length}
        </span>
        {overdue > 0 && (
          <span className="rounded-full bg-destructive/10 px-2 text-xs font-medium text-destructive">
            {countPl(overdue, "zaległy", "zaległe", "zaległych")}
          </span>
        )}
      </header>
      <p className="mb-2 text-xs text-muted-foreground">
        Klient milczy od 14 dni i nikt z nami nie rozmawiał z kandydatem. Jeden telefon — o
        wszystkich jego procesach.
      </p>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {shown.map((row) => (
          <li
            key={row.candidate_id}
            className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2 px-3 py-2.5 md:grid-cols-[auto_minmax(0,1fr)_auto]"
          >
            <span
              aria-hidden
              className="grid h-8 w-8 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
            >
              {initials(row.candidate_name)}
            </span>
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  href={`/candidates/${row.candidate_id}`}
                  className="truncate text-sm font-medium hover:underline"
                >
                  {row.candidate_name}
                </Link>
                <FollowupDuePill row={row} />
                {row.processes.length > 1 && (
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {countPl(row.processes.length, "proces", "procesy", "procesów")}
                  </span>
                )}
                {row.pending === "no_answer" && row.no_answer_count > 0 && (
                  <span className="rounded-full bg-warning-muted px-2 py-0.5 text-xs text-warning-muted-foreground">
                    nie odebrał {row.no_answer_count}×
                  </span>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {row.processes.map((p) => (
                  <Link
                    key={p.job_id}
                    href={`/jobs/${p.job_id}?candidate=${row.candidate_id}`}
                    className="rounded-md border border-border px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted"
                  >
                    {processChipLabel(p)}
                  </Link>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                {lastContactLabel(row)}
                {row.phone ? (
                  <>
                    {" · "}
                    <span className="select-all font-mono text-foreground">{row.phone}</span>
                  </>
                ) : null}
              </p>
            </div>
            <div className="col-span-2 flex justify-start md:col-span-1 md:justify-end">
              <Button
                size="sm"
                variant={row.state === "overdue" || row.state === "today" ? "primary" : "outline"}
                onClick={() => setOpenFor(row.candidate_id)}
                aria-label={`Zapisz wynik telefonu: ${row.candidate_name}`}
              >
                <PhoneCall className="h-3.5 w-3.5" />
                Zapisz wynik telefonu
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {rows.length > ROWS && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? "Zwiń" : `Pokaż wszystkie (${rows.length})`}
        </button>
      )}
      {others.length > 0 && (
        <details className="mt-2 text-xs text-muted-foreground">
          <summary className="cursor-pointer">
            Z {countPl(others.length, "Twoim kandydatem", "Twoimi kandydatami", "Twoimi kandydatami")}{" "}
            follow-up robi ktoś inny
          </summary>
          <ul className="mt-1.5 space-y-1 pl-4">
            {others.map((row) => (
              <li key={row.candidate_id}>
                <Link href={`/candidates/${row.candidate_id}`} className="hover:underline">
                  {row.candidate_name}
                </Link>
                : dzwoni {shortPersonName(row.caller_name) || "ktoś z zespołu"}, termin{" "}
                {followupDueLabel(row)}
              </li>
            ))}
          </ul>
        </details>
      )}
      <CandidateFollowupDialog
        candidateId={openFor}
        open={openFor !== null}
        onOpenChange={(open) => {
          if (!open) setOpenFor(null);
        }}
      />
    </section>
  );
}
