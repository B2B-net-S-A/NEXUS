"use client";

// „Obłożenie” w panelu „Czeka na Ciebie” (09.10.2026, prośba Head of
// Recruitment): ile rekrutacji P1 ma każda osoba (od 14.10.2026 tylko P1),
// tuż pod listami, przy których przydziela się ludzi („Propozycje automatu”,
// „Nowe rekrutacje P1 — kto prowadzi”). Te same dane i ta sama reguła co
// „Obłożenie” na pulpicie „Requesty i obłożenie” (`GET /api/request-board`,
// `LoadPeople`) — tu osoby stoją w kolumnach, bo panel jest nad kafelkami
// pulpitu.

import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState";
import { RequestPriorityChip } from "@/components/v2/jobs/RequestPriorityChip";
import {
  LOAD_SUBTITLE,
  LoadFootnote,
  LoadPeople,
} from "@/components/v2/request-board/LoadPanel";
import { useRequestBoard } from "@/lib/api/requestAllocation";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

export const TEAM_LOAD_TITLE = "Obłożenie";

export interface TeamLoadSectionProps {
  /** Panel „Czeka na Ciebie” nie ma zadań — sekcja stoi we własnej ramce. */
  standalone?: boolean;
}

export function TeamLoadSection({ standalone = false }: TeamLoadSectionProps) {
  const board = useRequestBoard();
  const load = board.data?.load;

  const section = (
    <section aria-label={TEAM_LOAD_TITLE} className={cn("min-w-0", !standalone && "lg:col-span-3")}>
      <header className="mb-1 flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-semibold">{TEAM_LOAD_TITLE}</h3>
        <RequestPriorityChip level="p1" className="self-center" />
        {load ? (
          <span className="text-xs tabular-nums text-muted-foreground">{load.length}</span>
        ) : null}
      </header>
      <p className="mb-2 text-xs text-muted-foreground">
        {LOAD_SUBTITLE} Kliknij osobę, żeby zobaczyć jej rekrutacje.
      </p>
      {load ? (
        <>
          <LoadPeople load={load} today={warsawToday()} columns />
          <LoadFootnote load={load} />
        </>
      ) : board.isError ? (
        // Awaria odczytu nie może wyglądać jak zespół bez requestów.
        <WidgetErrorBlock
          title="Nie udało się wczytać obłożenia."
          error={board.error}
          onRetry={() => void board.refetch()}
        />
      ) : (
        <p role="status" className="text-xs text-muted-foreground">
          Wczytuję obłożenie…
        </p>
      )}
    </section>
  );

  return standalone ? (
    <div className="rounded-xl border border-border bg-card p-4">{section}</div>
  ) : (
    section
  );
}
