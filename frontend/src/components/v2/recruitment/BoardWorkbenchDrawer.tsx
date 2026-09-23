"use client";

/**
 * Warsztaty osoby otwierane z Tablicy (decyzja Artura 22.09.2026: tryb
 * „Tabela" znika, zostaje sama Tablica).
 *
 * Panel osoby na Tablicy (`PipelineCandidateDock`) jest krótki — makieta 3
 * mówi, że pełne warsztaty (CV do klienta ze stawką i linkiem, rozmowy
 * z werdyktem hiring managera, umowa) rozszerzają panel do 760 px. To jest
 * DOKŁADNIE szeroki tryb `PersonPanel` z dawnej Tabeli, więc nic nie jest
 * przepisywane: ten komponent składa wiersz osoby z kolumn tablicy
 * i otwiera `PersonPanel` od razu w szerokim widoku. Zamknięcie („Zwiń",
 * Esc) zamyka warsztat i wraca do Tablicy.
 */

import { useMemo } from "react";

import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";
import {
  usePipelineMove,
  type PipelineRejectionReasonOption,
} from "@/hooks/usePipelineMove";

import { PersonPanel, type KanbanQueryState, type WorkbenchContext } from "./PersonPanel";
import { buildProcessRows, type OffTemplateBucket } from "./person-rows";
import type { PersonPanelSection } from "./types";

export type BoardWorkbenchContext = Omit<
  WorkbenchContext,
  "kanbanQueryState" | "budgetHourly" | "jobTitle"
>;

export interface BoardWorkbenchDrawerProps {
  jobId: number;
  jobTitle?: string | null;
  columns: KanbanColumn[];
  offTemplate?: OffTemplateBucket | null;
  candidateId: number;
  section: PersonPanelSection;
  onSectionChange: (section: PersonPanelSection) => void;
  onClose: () => void;
  readOnly: boolean;
  canWriteClientRate: boolean;
  budgetHourly: number | null;
  rejectionReasons: PipelineRejectionReasonOption[];
  workbenchContext: BoardWorkbenchContext;
  kanbanQueryState: KanbanQueryState;
  /** Nordea: „CV wysłane" = „Wysłane do Cpro", bez przeglądu DL (Pipeline v4). */
  cproEnabled?: boolean;
}

const NO_SCORES = new Map<number, number>();

export function BoardWorkbenchDrawer({
  jobId,
  jobTitle,
  columns,
  offTemplate = null,
  candidateId,
  section,
  onSectionChange,
  onClose,
  readOnly,
  canWriteClientRate,
  budgetHourly,
  rejectionReasons,
  workbenchContext,
  kanbanQueryState,
  cproEnabled = false,
}: BoardWorkbenchDrawerProps) {
  const row = useMemo(
    () =>
      buildProcessRows(columns, {
        scores: NO_SCORES,
        slaDays: null,
        budgetHourly,
        offTemplate,
      }).find((r) => r.candidateId === candidateId) ?? null,
    [columns, budgetHourly, offTemplate, candidateId],
  );

  const move = usePipelineMove({
    jobId,
    job: { budgetHourly, rejectionReasons },
    columns,
    readOnly,
    canWriteClientRate,
    cproEnabled,
  });

  const context: WorkbenchContext = {
    ...workbenchContext,
    jobTitle: jobTitle ?? undefined,
    cproEnabled,
    budgetHourly,
    kanbanQueryState,
  };

  return (
    <>
      {row ? (
        <PersonPanel
          row={row}
          jobId={jobId}
          columns={columns}
          move={move}
          readOnly={readOnly}
          canWriteClientRate={canWriteClientRate}
          workbenchContext={context}
          section={section}
          onSectionChange={onSectionChange}
          wide
          onWideChange={(wide) => {
            if (!wide) onClose();
          }}
          onClose={onClose}
          // Wąska kolumna panelu nie ma tu miejsca — cała treść żyje
          // w nakładce szerokiego widoku (portal Radix).
          className="hidden"
        />
      ) : null}
      {move.dialogs}
    </>
  );
}
