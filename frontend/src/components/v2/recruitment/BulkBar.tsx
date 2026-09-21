"use client";

/**
 * Pasek akcji zbiorczych — stopka `VirtualTable`, widoczna tylko przy
 * zaznaczeniu.
 *
 * Każdy ruch etapu idzie przez `usePipelineMove` (`requestBulkMove`,
 * `requestReject`): to pętla POJEDYNCZYCH ruchów z tymi samymi oknami co
 * tablica, nigdy `/bulk-move` — tamta trasa nie ma okna „Przenieś mimo to"
 * i odrzuca całą paczkę przy pierwszym ostrzeżeniu.
 */

import { useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";

import { useToast } from "@/components/Toast";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { colId, columnLabel, type KanbanColumn } from "@/components/v2/pages/kanban-shared";
import type { PipelineMoveControls } from "@/hooks/usePipelineMove";
import { BulkCvDownloadError, downloadBulkCvs } from "@/lib/bulk-cv-download";
import { terminalOf } from "@/lib/kanban-terminal";
import { DEFAULT_FILTERS, encodeCompareHref } from "@/lib/url-filters";
import { cn } from "@/lib/utils";

import type { PersonRow, ProcessPersonRow, ProposalPersonRow } from "./types";

/** Porównanie kandydatów przyjmuje 2–3 osoby (limit ekranu `/candidates/compare`). */
export const COMPARE_MIN = 2;
export const COMPARE_MAX = 3;

export interface BulkBarProps {
  /** Zaznaczone wiersze (już zawężone do widocznych). */
  rows: PersonRow[];
  /** Kolumny szablonu — cele „Przenieś na etap…". */
  columns: KanbanColumn[];
  move: PipelineMoveControls;
  onClear: () => void;
  /** „Wyślij CV do klienta" — tylko gdy KAŻDA zaznaczona osoba jest zweryfikowana. */
  onBulkSendCv?: (rows: ProcessPersonRow[]) => void;
  /** Propozycje: „Dodaj do rekrutacji" i „Pomiń". */
  onAddProposals?: (rows: ProposalPersonRow[]) => void;
  onDismissProposals?: (rows: ProposalPersonRow[]) => void;
  /** Prawa strona paska („17 z 47"). */
  summary?: React.ReactNode;
}

const barButton =
  "inline-flex h-[30px] items-center gap-1 rounded-md border border-background/30 px-3 text-xs font-medium text-background transition-colors hover:bg-background/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-background disabled:cursor-not-allowed disabled:opacity-40";

/** Powód, dla którego „Wyślij CV do klienta" jest wyłączone — albo `null`. */
export function bulkSendCvBlockedReason(rows: ProcessPersonRow[]): string | null {
  if (rows.length === 0) return "Zaznacz osoby.";
  const outside = rows.filter((row) => row.group !== "verification").length;
  if (outside === 0) return null;
  return outside === rows.length
    ? "CV wysyłamy osobom na etapie „Zweryfikowani” — żadna z zaznaczonych na nim nie jest."
    : `CV wysyłamy osobom na etapie „Zweryfikowani” — ${outside} z zaznaczonych na nim nie jest.`;
}

export function BulkBar({
  rows,
  columns,
  move,
  onClear,
  onBulkSendCv,
  onAddProposals,
  onDismissProposals,
  summary,
}: BulkBarProps) {
  const { showSuccess, showError } = useToast();
  const [zipBusy, setZipBusy] = useState(false);

  if (rows.length === 0) return null;

  const processRows = rows.filter((row): row is ProcessPersonRow => row.kind === "process");
  const proposalRows = rows.filter((row): row is ProposalPersonRow => row.kind === "proposal");
  const isProposal = proposalRows.length > 0 && processRows.length === 0;
  const candidateIds = rows.map((row) => row.candidateId);

  const downloadZip = async () => {
    if (zipBusy) return;
    setZipBusy(true);
    try {
      const result = await downloadBulkCvs(candidateIds);
      showSuccess(
        result.skippedCount > 0
          ? `Pobrano CV: ${result.includedCount}. Bez pliku CV: ${result.skippedCount}.`
          : `Pobrano CV: ${result.includedCount}.`,
      );
    } catch (error) {
      showError(
        error instanceof BulkCvDownloadError
          ? error.message
          : "Nie udało się pobrać CV. Spróbuj ponownie.",
      );
    } finally {
      setZipBusy(false);
    }
  };

  const shell = (children: React.ReactNode) => (
    <div
      role="toolbar"
      aria-label="Akcje dla zaznaczonych osób"
      className="flex h-11 items-center gap-2.5 overflow-x-auto bg-foreground px-3.5 text-[13px] text-background"
    >
      <span className="shrink-0 font-semibold" aria-live="polite">
        Zaznaczono {rows.length}
      </span>
      {children}
      <span className="flex-1" />
      {summary ? <span className="shrink-0 text-xs text-background/70">{summary}</span> : null}
      <button type="button" className={cn(barButton, "border-transparent")} onClick={onClear}>
        Wyczyść
      </button>
    </div>
  );

  if (isProposal) {
    const compareDisabled = rows.length < COMPARE_MIN || rows.length > COMPARE_MAX;
    const compareTitle = compareDisabled
      ? `Porównanie przyjmuje od ${COMPARE_MIN} do ${COMPARE_MAX} osób.`
      : undefined;
    return shell(
      <>
        {onAddProposals ? (
          <button type="button" className={barButton} onClick={() => onAddProposals(proposalRows)}>
            Dodaj do rekrutacji
          </button>
        ) : null}
        {onDismissProposals ? (
          <button
            type="button"
            className={barButton}
            onClick={() => onDismissProposals(proposalRows)}
          >
            Pomiń
          </button>
        ) : null}
        {compareDisabled ? (
          <button type="button" className={barButton} disabled title={compareTitle}>
            Porównaj
          </button>
        ) : (
          <Link href={encodeCompareHref(DEFAULT_FILTERS, candidateIds)} className={barButton}>
            Porównaj
          </Link>
        )}
      </>,
    );
  }

  // „Zatrudniony" poza ruchem zbiorczym: zatrudnienie zakłada szkic kontraktu
  // i wymaga potwierdzenia per osoba. Odrzucenie ma własny przycisk z powodem.
  const moveTargets = columns.filter((col) => terminalOf(col) == null);
  const items = processRows.map((row) => row.item);
  const sendCvBlocked = bulkSendCvBlockedReason(processRows);

  return shell(
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button type="button" className={barButton} disabled={move.isMoving}>
            Przenieś na etap…
            <ChevronDown className="size-3.5" aria-hidden />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="max-h-72 overflow-y-auto">
          {moveTargets.map((col) => (
            <DropdownMenuItem
              key={colId(col)}
              // Okno ruchu (stawka, ostrzeżenie) otwiera się po zwrocie fokusu
              // przez Radix — w tym samym ticku zamknęłoby się samo.
              onSelect={() =>
                window.setTimeout(
                  () => void move.requestBulkMove(items, col, { onHandled: onClear }),
                  0,
                )
              }
            >
              {columnLabel(col)}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      {onBulkSendCv ? (
        <button
          type="button"
          className={barButton}
          disabled={sendCvBlocked != null || move.isMoving}
          title={sendCvBlocked ?? undefined}
          onClick={() => onBulkSendCv(processRows)}
        >
          Wyślij CV do klienta
        </button>
      ) : null}
      <button
        type="button"
        className={barButton}
        disabled={move.isMoving}
        onClick={() => move.requestReject(items)}
      >
        Odrzuć
      </button>
      <button type="button" className={barButton} disabled={zipBusy} onClick={() => void downloadZip()}>
        {zipBusy ? "Pobieranie…" : "CV (ZIP)"}
      </button>
    </>,
  );
}
