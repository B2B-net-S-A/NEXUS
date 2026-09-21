/**
 * Wspólny kontrakt widoku „rekrutacja = jedna tabela" (wersja 3, 09.2026).
 *
 * Tabela osób, segment propozycji, panel osoby i okna wysuwane powstają
 * równolegle — ten plik jest jedynym miejscem, w którym uzgadniają kształt
 * danych. Zmiana tutaj = zmiana we wszystkich czterech.
 */

import type { ReactNode } from "react";

import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { PipelineGroupKey } from "@/lib/pipeline-flow";
import type { NextAction } from "@/lib/pipeline-next-action";

/**
 * Segment paska etapów — jednocześnie lejek i filtr tabeli.
 *
 * `group:<klucz>` zawęża do grupy etapów (`PipelineGroupKey`), `stage:<id>`
 * do pojedynczej kolumny szablonu (`stage_def_id`).
 */
export type RecruitmentSegment =
  | "proposals"
  | "shortlist"
  | "in-process"
  | "off-template"
  | "closed"
  | `group:${PipelineGroupKey}`
  | `stage:${number}`;

/** Sekcje panelu osoby — dawne osobne zakładki rekrutacji. */
export type PersonPanelSection =
  | "cv"
  | "screening"
  | "interviews"
  | "contract"
  | "match"
  | "notes";

/** Okna wysuwane otwierane z nagłówka rekrutacji albo z tabeli. */
export type RecruitmentSlideOver =
  | "order"
  | "questions"
  | "history-chat"
  | "manual-search";

/** Skąd pochodzi propozycja (kolumna „Źródło"; jedna osoba może mieć kilka). */
export type ProposalSource =
  | "full_base"
  | "new_cv"
  | "similar_projects"
  | "recommendation"
  | "marketplace";

export const PROPOSAL_SOURCE_LABEL: Record<ProposalSource, string> = {
  full_base: "Cała baza",
  new_cv: "Nowe CV",
  similar_projects: "Podobne projekty",
  recommendation: "Rekomendowani",
  marketplace: "Targ",
};

interface PersonRowBase {
  /** Klucz wiersza w tabeli — unikalny w obrębie segmentu. */
  key: string;
  candidateId: number;
  fullName: string;
  /** Stawka do pokazania (już sformatowana) albo `null` = „—". */
  rateLabel: string | null;
  availabilityLabel: string | null;
  /** Dopasowanie 0–100; `null` = nie policzono (NIGDY zero zastępcze). */
  fitScore: number | null;
  /** Kody ostrzeżeń (weto HM, ponad budżet, konflikt z klientem…). */
  warnings: string[];
}

/** Osoba w procesie — wiersz z tablicy kanbana. */
export interface ProcessPersonRow extends PersonRowBase {
  kind: "process";
  item: KanbanItem;
  column: KanbanColumn;
  group: PipelineGroupKey;
  stageLabel: string;
  nextAction: NextAction;
  daysInStage: number | null;
  recruiterId: number | null;
  recruiterName: string | null;
}

/** Propozycja z bazy — osoba spoza rekrutacji. */
export interface ProposalPersonRow extends PersonRowBase {
  kind: "proposal";
  sources: ProposalSource[];
  /** Jedno zdanie „dlaczego pasuje" albo `null`, gdy źródło go nie niesie. */
  reason: string | null;
  isNew: boolean;
  previouslyDismissed: boolean;
  /** Identyfikator przeglądu bazy, z którego pochodzi wynik (telemetria). */
  runId: string | null;
}

export type PersonRow = ProcessPersonRow | ProposalPersonRow;

/** Grupa wierszy przy dużych rekrutacjach („kto ma ruch"). */
export interface PersonRowGroup {
  key: string;
  label: string;
  rowKeys: string[];
  hint?: ReactNode;
}

/**
 * Kontrakt warsztatów (Screening, CV do klienta, Rozmowy, Umowa) w panelu.
 *
 * `layout="panel"` chowa kolejkę i nagłówek warsztatu — zostają szczegóły
 * JEDNEJ osoby wskazanej przez `focusCandidateId`. Osoba spoza kolejki tego
 * warsztatu dostaje krótki pusty stan, nie pusty ekran.
 */
export interface WorkbenchPanelProps {
  layout?: "full" | "panel";
  focusCandidateId?: number | null;
}
