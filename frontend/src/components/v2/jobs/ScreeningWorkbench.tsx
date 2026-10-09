"use client";

/**
 * ScreeningWorkbench — sekcja „Screening” panelu osoby.
 *
 * Krok 05 programu „flow w języku C2” zebrał screening w jedno stanowisko
 * (kolejka, arkusz Championa, dok „Weryfikacja” ze stawką, kartą i notatkami).
 * Od 0424 (decyzje Artura D1–D10, 07.10.2026) to jeden formularz pary —
 * pytania z Profilu Championa, warunki kandydata (stawka i pola karty)
 * i ocena rekrutera — z podglądem obok (D3: „od razu z boku”). Od 09.10.2026
 * podgląd stoi w dużej LEWEJ strefie panelu osoby (`PersonPanelSide`), a ta
 * sekcja zajmuje prawą kolumnę; w wąskim oknie podgląd zostaje w miejscu,
 * pod przyciskiem „Pokaż CV i wymagania”:
 * - osoba w „Nowych” bez zapisanego formularza: profil przed telefonem
 *   (`BeforeCallProfile`) i CV obok; „Zacznij screening” otwiera formularz,
 * - „Screening” i dalsze etapy: formularz i wymagania obok; od „CV wysłane”
 *   formularz dalej da się poprawić (D8) z banerem, co ta zmiana znaczy,
 * - proces zakończony: zapisany arkusz, karta tylko do odczytu i historia.
 *
 * Gospodarz zostaje tu (plakietki, Prep-kit, „Baza pytań”, formularz,
 * podgląd). Zakładki doku „Stawka i decyzja” / „Karta” / „Notatki” i układ
 * „full” z kolejką zniknęły — kolejką jest kolumna „Nowi” na Tablicy, stawka
 * i karta są polami formularza, a notatki zostają w panelu osoby.
 *
 * Podgląd (`CandidatePreviewPane`, pdf.js i `docx-preview`) ładuje się za
 * `next/dynamic` — pilnuje tego `heavy-bundle-boundaries.test.ts`.
 */

import { useMemo, useState, type ComponentProps } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronLeft, ExternalLink, HelpCircle, PanelRight, Sparkles, UserX } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import type { JobDetailTab } from "@/components/v2/jobs/JobDetailCompactHeader";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { PersonPanelSide, usePersonPanelSideActive } from "@/components/v2/person/PersonPanelSide";
import type { WorkbenchPanelProps } from "@/components/v2/recruitment/types";
import { BeforeCallProfile } from "@/components/v2/screening-form/BeforeCallProfile";
import { ScreeningFormHistory } from "@/components/v2/screening-form/ScreeningFormHistory";
import { ScreeningFullForm } from "@/components/v2/screening-form/ScreeningFullForm";
import { RecommendationCardSection } from "@/components/v2/screening/RecommendationCardSection";
import { interviewQuestionsApi } from "@/lib/api";
import { useScreeningFormState } from "@/lib/api/screeningForm";
import { placeStage } from "@/lib/board-stages";
import { terminalOf } from "@/lib/kanban-terminal";
import { VERIFIED_STAGE, findStageColumn, isNewColumn, itemFullName } from "@/lib/pipeline-flow";
import { isOverHourlyBudget } from "@/lib/rate-to-hourly";
import { AFTER_CV_SENT_COLUMNS, hasSheetContent } from "@/lib/screening-form";
import { encodeJobBackRef } from "@/lib/url-filters";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

function PreviewLoading() {
  return <Skeleton className="h-64 w-full rounded-xl" />;
}

const CandidatePreviewPane = dynamic(
  () =>
    import("@/components/v2/screening-form/CandidatePreviewPane").then(
      (m) => m.CandidatePreviewPane,
    ),
  { ssr: false, loading: PreviewLoading },
);

type PreviewProps = ComponentProps<typeof CandidatePreviewPane>;
type PreviewTab = NonNullable<PreviewProps["tab"]>;

/** Proces zakończony albo rekrutacja zamknięta — formularz jest już historią. */
const ENDED_REASONS: ReadonlySet<string> = new Set(["process_closed", "process_voided", "job_closed"]);

export interface ScreeningWorkbenchProps extends Omit<WorkbenchPanelProps, "layout"> {
  jobId: number;
  /** Budżet PLN/h rekrutacji (`effective_budget_hourly`) — porównanie stawki. */
  jobBudgetHourly: number | null;
  columns: KanbanColumn[];
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  isSuccess: boolean;
  onRetry: () => void;
  /** Odśwież kanban po udanym ruchu (strona trzyma klucz zapytania). */
  onMoved: () => void;
  readOnly: boolean;
  onTabChange: (tab: JobDetailTab) => void;
  /** „Biorę — 12 h” z profilu przed telefonem — ta sama blokada co karta. */
  onTake?: (item: KanbanItem) => void;
  /** Harness `/preview/screening-form`: bajty CV z plików statycznych, bez API. */
  previewLoaders?: Pick<PreviewProps, "loadDocumentBlob" | "loadOriginalBlob">;
}

export function ScreeningWorkbench({
  jobId,
  jobBudgetHourly,
  columns,
  isLoading,
  isError,
  error,
  isSuccess,
  onRetry,
  onMoved,
  readOnly,
  onTabChange,
  onTake,
  previewLoaders,
  focusCandidateId = null,
  panelFallback,
}: ScreeningWorkbenchProps) {
  const found = useMemo(() => {
    if (focusCandidateId == null) return null;
    for (const col of columns) {
      const item = col.items.find((i) => i.candidate_id === focusCandidateId);
      if (item) return { item, col };
    }
    return null;
  }, [columns, focusCandidateId]);
  const verifiedCol = useMemo(() => findStageColumn(columns, VERIFIED_STAGE), [columns]);
  const rejectedCol = useMemo(() => columns.find((c) => terminalOf(c) === "rejected") ?? null, [columns]);

  const candidateId = found?.item.candidate_id ?? -1;
  const formQuery = useScreeningFormState(candidateId, jobId, found != null);
  const state = formQuery.data;

  // Pytania przypięte do rekrutacji (zakładka „Baza pytań”).
  const pinnedQuery = useQuery({
    queryKey: ["job-questions", jobId],
    queryFn: () => interviewQuestionsApi.listForJob(jobId).then((r) => r.data),
    staleTime: 60_000,
  });

  const [started, setStarted] = useState(false);
  // Formularz raz otwarty zostaje zamontowany — powrót do profilu przed
  // telefonem nie gubi wpisanych odpowiedzi.
  const [formMounted, setFormMounted] = useState(false);
  const [previewTab, setPreviewTab] = useState<PreviewTab | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  // Od 1024 px szerokości okna podgląd stoi w lewej strefie panelu osoby.
  const previewInSide = usePersonPanelSideActive();

  const viewState = resolveViewState({ isLoading, isError, error, isSuccess });
  if (viewState === "loading") return <Skeleton className="h-64 w-full rounded-xl" />;
  if (viewState === "forbidden" || viewState === "not_found" || viewState === "error") {
    return (
      <QueryStateNotice
        state={viewState}
        className="rounded-xl"
        description={
          viewState === "forbidden"
            ? "Twoja rola nie ma dostępu do pipeline'u tej rekrutacji — to nie znaczy, że nikt nie czeka na screening."
            : undefined
        }
        onRetry={onRetry}
      />
    );
  }

  if (!found) {
    if (panelFallback != null) return <>{panelFallback}</>;
    return (
      <p className="rounded-lg border border-dashed border-border bg-muted/20 px-3 py-4 text-center text-xs text-muted-foreground">
        Tej osoby nie ma dziś na Tablicy tej rekrutacji.
      </p>
    );
  }

  const { item, col } = found;
  const name = itemFullName(item);
  const entry = isNewColumn(col);
  const inNew = entry && placeStage(col).column === "new";
  // Stan jeszcze się nie wczytał (albo odczyt padł) = traktujemy jak pusty:
  // profil przed telefonem nie potrzebuje formularza, a „Zacznij screening” i tak go otworzy.
  const formIsEmpty = state == null || (state.version === 0 && !hasSheetContent(state));
  const ended =
    state != null && !state.editable && state.read_only_reason != null && ENDED_REASONS.has(state.read_only_reason);
  // „Nowi” bez zapisanego formularza: najpierw profil przed telefonem.
  const showBeforeCall = inNew && formIsEmpty && !started;
  const tab: PreviewTab = previewTab ?? (showBeforeCall ? "cv" : "requirements");

  const forward =
    entry && verifiedCol && !readOnly
      ? { stage: VERIFIED_STAGE, stageDefId: verifiedCol.stage_def_id ?? null, label: "Zweryfikowany" }
      : null;
  const reject =
    entry && rejectedCol && !readOnly
      ? {
          stage: rejectedCol.stage,
          stageDefId: rejectedCol.stage_def_id ?? null,
          previousStage: col.stage,
          previousCategory: col.category === "external" ? ("external" as const) : ("internal" as const),
        }
      : null;
  const afterCvSent = state?.board_column != null && AFTER_CV_SENT_COLUMNS.has(state.board_column);

  const startScreening = () => {
    setStarted(true);
    setFormMounted(true);
    setPreviewTab("requirements");
  };

  const badges = (
    <>
      {isOverHourlyBudget(item, jobBudgetHourly) ? (
        <Badge
          variant="warning"
          size="sm"
          title="Stawka kandydata przekracza budżet PLN/h rekrutacji — informacja, nic nie blokuje."
        >
          <HelpCircle className="h-2.5 w-2.5" /> Ponad budżet
        </Badge>
      ) : null}
      {item.hm_veto ? (
        <Badge variant="danger" size="sm" title={`Powód: ${item.hm_veto.rejection_reason_name}`}>
          <UserX className="h-2.5 w-2.5" /> Weto HM
        </Badge>
      ) : null}
    </>
  );

  let left;
  if (formQuery.isLoading && !showBeforeCall) {
    left = <Skeleton className="h-64 w-full rounded-xl" />;
  } else if (ended && state) {
    left = (
      <div className="space-y-4" data-testid="screening-ended">
        {panelFallback}
        <section aria-label="Karta rekomendacji" className="space-y-2">
          <h3 className="text-xs font-semibold text-muted-foreground">Karta rekomendacji</h3>
          <RecommendationCardSection candidateId={item.candidate_id} jobId={jobId} candidateName={name} readOnly />
        </section>
        {state.versions_count > 0 ? (
          <ScreeningFormHistory
            candidateId={item.candidate_id}
            jobId={jobId}
            currentVersion={state.version}
            stateToken={state.state_token}
            canRestore={false}
          />
        ) : null}
      </div>
    );
  } else {
    left = (
      <>
        {inNew && (showBeforeCall || formMounted) ? (
          <div hidden={!showBeforeCall}>
            <BeforeCallProfile
              item={item}
              jobId={jobId}
              readOnly={readOnly}
              onTake={onTake ? () => onTake(item) : undefined}
              onStartScreening={startScreening}
            />
          </div>
        ) : null}
        {!showBeforeCall || formMounted ? (
          <div hidden={showBeforeCall} className="space-y-2">
            {inNew && formIsEmpty ? (
              <button
                type="button"
                onClick={() => setStarted(false)}
                className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden /> Profil przed telefonem
              </button>
            ) : null}
            <ScreeningFullForm
              candidateId={item.candidate_id}
              jobId={jobId}
              candidateName={name}
              jobBudgetHourly={jobBudgetHourly}
              forward={forward}
              reject={reject}
              readOnly={readOnly}
              onMoved={onMoved}
              onOpenChampion={() => onTabChange("champion")}
              banner={
                afterCvSent ? (
                  <p
                    role="note"
                    data-testid="screening-after-cv-sent"
                    className="rounded-md border border-info/30 bg-info-muted px-3 py-2 text-xs text-info-muted-foreground"
                  >
                    CV tej osoby poszło już do klienta. Zmiana w formularzu poprawia to, co widzi Delivery Lead,
                    i trafi do następnego CV firmowego — klient nie dostaje jej automatycznie.
                  </p>
                ) : null
              }
            />
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className="@container min-w-0 space-y-3" data-testid="screening-workbench">
      <div className="flex flex-wrap items-center gap-1.5">
        {badges}
        <Link
          href={`/jobs/${jobId}/prep/${item.candidate_id}`}
          title="Prep-kit: pytania AI z podobnych rekrutacji"
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
        >
          <Sparkles className="h-3.5 w-3.5 text-primary" /> Prep-kit
        </Link>
        <Button size="sm" variant="outline" onClick={() => onTabChange("questions")}>
          <BookOpen className="h-3.5 w-3.5" /> Baza pytań
          {pinnedQuery.isSuccess ? ` · przypięte: ${pinnedQuery.data?.length ?? 0}` : ""}
        </Button>
        <Link
          href={`/candidates/${item.candidate_id}?${encodeJobBackRef(jobId).toString()}`}
          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border px-3 text-xs text-foreground hover:bg-muted"
        >
          <ExternalLink className="h-3.5 w-3.5" /> Pełny profil
        </Link>
        {!previewInSide ? (
          <Button
            size="sm"
            variant="outline"
            aria-expanded={previewOpen}
            onClick={() => setPreviewOpen((open) => !open)}
          >
            <PanelRight className="h-3.5 w-3.5" aria-hidden /> {previewOpen ? "Schowaj podgląd" : "Pokaż CV i wymagania"}
          </Button>
        ) : null}
      </div>

      {/* Podgląd: w szerokim oknie w lewej strefie panelu (portal), w wąskim
          w miejscu, nad formularzem, po kliknięciu „Pokaż CV i wymagania”. */}
      <PersonPanelSide
        inline={(content) => (
          <div
            className={cn("min-w-0", previewOpen ? "flex h-[70dvh] flex-col" : "hidden")}
            data-testid="screening-preview-column"
          >
            {content}
          </div>
        )}
      >
        <CandidatePreviewPane
          candidateId={item.candidate_id}
          jobId={jobId}
          stageId={state?.stage_id ?? item.id}
          tab={tab}
          onTabChange={setPreviewTab}
          budgetHourly={jobBudgetHourly}
          className="flex-1"
          {...previewLoaders}
        />
      </PersonPanelSide>

      <div className="min-w-0">{left}</div>
    </div>
  );
}
