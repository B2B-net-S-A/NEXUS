"use client";

/**
 * „Wymagania do poprawy” w „Czeka na Ciebie” (13.10.2026, D4).
 *
 * Wiersze z `GET /api/board-tasks` (`requirement_fixes`): otwarte rekrutacje,
 * w których serwer proponuje rozdzielić wymagania na słowa do szukania
 * i rzeczy do sprawdzenia w rozmowie. Delivery Lead widzi swoje, Head of
 * Recruitment i admin — wszystkie. „Pokaż zmiany” otwiera porównanie
 * z „Zatwierdź / Odrzuć” (`RequirementProposalDialog`); bez słów do szukania
 * zatwierdzić się nie da, więc wiersz prowadzi do Profilu Championa.
 *
 * Wzór `PendingJobsSection`: lista nie liczy się do „Czeka na Ciebie” — obok
 * zadań stoi w panelu, a gdy nic nie czeka, sama, we własnej ramce.
 */

import Link from "next/link";
import { useState } from "react";

import {
  RequirementProposalDialog,
  championEditHref,
} from "@/components/champion/RequirementProposalDialog";
import { Button } from "@/components/ui/button";
import type { RequirementFixRow } from "@/lib/api/boardTasks";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";

export const REQUIREMENT_FIXES_TITLE = "Wymagania do poprawy";

/** Tyle rekrutacji widać, zanim trzeba kliknąć „Pokaż wszystkie”. */
export const REQUIREMENT_FIXES_ROWS = 6;

/** „3 słowa do szukania · 2 do rozmowy”. */
export function requirementFixCounts(row: Pick<RequirementFixRow, "rows" | "talk">): string {
  return `${countPl(row.rows, "słowo", "słowa", "słów")} do szukania · ${row.talk} do rozmowy`;
}

export interface RequirementFixesSectionProps {
  rows: RequirementFixRow[] | null | undefined;
  /** Panel „Czeka na Ciebie” nie ma nic do zrobienia — sekcja stoi sama. */
  standalone?: boolean;
  /** Admin i Head of Recruitment: jedna linia z „Rozwiń”, jak lista do
   *  dokończenia — porządki wszystkich rekrutacji to zaległość, nie praca na dziś. */
  collapsed?: boolean;
}

export function RequirementFixesSection({
  rows,
  standalone = false,
  collapsed = false,
}: RequirementFixesSectionProps) {
  const [expanded, setExpanded] = useState(false);
  const [opened, setOpened] = useState(false);
  const [dialogRow, setDialogRow] = useState<RequirementFixRow | null>(null);
  const items = rows ?? [];
  if (items.length === 0) return null;

  if (collapsed && !opened) {
    return (
      <section
        aria-label={REQUIREMENT_FIXES_TITLE}
        className={cn("min-w-0", !standalone && "lg:col-span-3")}
        data-testid="requirement-fixes-collapsed"
      >
        <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
          <span className="font-semibold">
            {REQUIREMENT_FIXES_TITLE} <span className="tabular-nums">({items.length})</span>
          </span>
          <button
            type="button"
            onClick={() => setOpened(true)}
            aria-expanded={false}
            className="text-xs font-medium text-primary hover:underline"
          >
            Rozwiń
          </button>
        </p>
      </section>
    );
  }

  const shown = expanded ? items : items.slice(0, REQUIREMENT_FIXES_ROWS);

  const section = (
    <section
      aria-label={REQUIREMENT_FIXES_TITLE}
      className={cn("@container/fixes min-w-0", !standalone && "lg:col-span-3")}
    >
      <header className="mb-1">
        {/* Liczba w nawiasie, bez plakietki zadania — lista nie liczy się
            do „Czeka na Ciebie”. */}
        <h3 className="text-sm font-semibold">
          {REQUIREMENT_FIXES_TITLE} <span className="tabular-nums">({items.length})</span>
        </h3>
      </header>
      <p className="mb-2 text-xs text-muted-foreground">
        System rozdzielił wymagania: słowa do szukania i rzeczy do sprawdzenia w rozmowie.
        Zatwierdź albo odrzuć.
      </p>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {shown.map((row) => (
          <li
            key={row.job_id}
            // Opis i przycisk obok siebie dopiero od 640 px sekcji.
            className="grid gap-x-4 gap-y-1.5 px-3 py-2.5 @min-[640px]/fixes:grid-cols-[minmax(0,1fr)_auto] @min-[640px]/fixes:items-center"
          >
            <div className="min-w-0">
              <Link
                href={`/jobs/${row.job_id}`}
                title={row.title}
                className="block max-w-full truncate text-sm font-medium hover:underline"
              >
                {row.title}
              </Link>
              {row.reasons.length > 0 ? (
                <p className="text-xs text-muted-foreground" data-testid="requirement-fix-reasons">
                  {row.reasons.map((reason) => reason.text).join(" · ")}
                </p>
              ) : null}
              <p className="text-xs tabular-nums text-muted-foreground" data-testid="requirement-fix-counts">
                {requirementFixCounts(row)}
              </p>
            </div>
            <div className="flex items-center gap-1.5 @min-[640px]/fixes:justify-end">
              {row.can_apply ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setDialogRow(row)}
                  aria-label={`Pokaż zmiany: ${row.title}`}
                >
                  Pokaż zmiany
                </Button>
              ) : (
                <Button asChild size="sm" variant="outline">
                  <Link href={championEditHref(row.job_id)} aria-label={`Uzupełnij: ${row.title}`}>
                    Uzupełnij
                  </Link>
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {items.length > REQUIREMENT_FIXES_ROWS ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? "Zwiń" : `Pokaż wszystkie (${items.length})`}
        </button>
      ) : null}
      {/* Okno montowane dopiero po kliknięciu — zamknięte nie pyta serwera. */}
      {dialogRow ? (
        <RequirementProposalDialog
          jobId={dialogRow.job_id}
          jobTitle={dialogRow.title}
          open
          onOpenChange={(next) => {
            if (!next) setDialogRow(null);
          }}
        />
      ) : null}
    </section>
  );

  return standalone ? (
    <div className="rounded-xl border border-border bg-card p-4">{section}</div>
  ) : (
    section
  );
}
