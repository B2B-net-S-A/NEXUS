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
  // Pliki rekrutacji: request klienta i załączniki (0428, 09.10.2026).
  | "files"
  | "history-chat"
  | "manual-search"
  // Panel „Podobne rekrutacje” — przepięcia jednym kliknięciem (25.09.2026).
  // Od 02.10.2026 to zakładka okna „Kandydaci do dodania”; adres zostaje
  // czytany (stare linki), stan strony zna już tylko `add`.
  | "similar"
  // Okno „Kandydaci do dodania” — cztery źródła, `?win=add&wintab=<źródło>`.
  | "add";

/** Źródła kandydatów: kafle nad Tablicą i zakładki okna (02.10.2026). */
export type CandidateSourceTab = "similar" | "postings" | "base" | "search";

export const CANDIDATE_SOURCE_TABS: readonly CandidateSourceTab[] = [
  "similar",
  "postings",
  "base",
  "search",
];

/** Skąd pochodzi propozycja (kolumna „Źródło"; jedna osoba może mieć kilka). */
export type ProposalSource =
  | "reassign"
  | "trainee"
  | "full_base"
  | "new_cv"
  | "similar_projects"
  | "recommendation"
  | "marketplace"
  // 30.09.2026: dopasowanie ze scrapera JJIT/RocketJobs (dawniej karta na Tablicy).
  | "job_board";

export const PROPOSAL_SOURCE_LABEL: Record<ProposalSource, string> = {
  // Pierwsze w słowniku = pierwsze w kolumnie „Źródło" i na liście filtrów.
  // Przepięcie (0341): osoba wysłana już do klienta przy podobnym requeście.
  reassign: "↻ Przepięcie",
  // Praktykant (0374) po rozmowie przekazał osobę do tej rekrutacji.
  trainee: "Od praktykanta",
  full_base: "Cała baza",
  new_cv: "Nowe CV",
  similar_projects: "Podobne projekty",
  recommendation: "Rekomendowani",
  marketplace: "Targ",
  job_board: "Z portalu (JJIT/RocketJobs)",
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
  /** Notatka praktykanta przy przekazaniu (0374) — tylko przy źródle `trainee`. */
  handoverNote?: string | null;
  /**
   * Punkty „znany zespołowi” (07.10.2026) — dodawane do dopasowania WYŁĄCZNIE
   * przy sortowaniu; `fitScore` zostaje bez nich.
   */
  historyPoints?: number;
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
  /**
   * Co pokazać w panelu, gdy osoba NIE stoi w kolejce warsztatu (np. jest już
   * na późniejszym etapie). Panel osoby podaje tu podgląd tylko do odczytu
   * (zapisany arkusz screeningu, wersje CV i linki) — bez tego warsztat
   * pokazuje krótki pusty stan.
   */
  panelFallback?: ReactNode;
}
