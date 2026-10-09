"use client";

/**
 * „Screening” tylko do odczytu — jeden widok dla każdego ekranu (09.10.2026).
 *
 * Decyzja Artura 09.10.2026: nazwa „Karta rekomendacji” znika z ekranów. Dok
 * osoby, przegląd Delivery Leada, zakończony proces i profil kandydata
 * pokazują to samo w kolejności formularza: warunki → pytania i odpowiedzi →
 * ocena. Wcześniej te same dane stały w dwóch albo trzech blokach (arkusz,
 * karta, „Ocena rekrutera”).
 *
 * - `ScreeningSummaryView` — sam widok ze stanu formularza, bez zapytań
 *   (harnessy i ekrany, które stan już mają);
 * - `ScreeningLegacyText` — zwinięte „W starym formacie” z „Kopiuj”; tekst
 *   pobiera dopiero po rozwinięciu (`GET /api/recommendation-cards`);
 * - `ScreeningSummarySection` — widok z własnym zapytaniem, ładowaniem
 *   i błędem (panel osoby bez formularza, okno w profilu).
 */

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { AlertTriangle, ChevronRight, Copy, Loader2, Lock, PencilLine } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScreeningAnswersList } from "@/components/v2/screening/ScreeningAnswersList";
import { useRecommendationCard } from "@/lib/api/recommendationCards";
import { useScreeningFormState, type ScreeningFormState } from "@/lib/api/screeningForm";
import { copyTextToClipboard } from "@/lib/clipboard";
import { cardFieldSource, cardFieldValue } from "@/lib/recommendation-card";
import { SCREENING_FIT_LABEL, SCREENING_FIT_VARIANT } from "@/lib/screening-conversations";
import {
  cardAssessmentKeys,
  cardTermsKeys,
  formFieldLabel,
  formQuestions,
  formatFormRate,
} from "@/lib/screening-form";
import {
  screeningAnsweredLabel,
  screeningDealBreakerWarning,
  screeningFieldHint,
  screeningSummaryRows,
} from "@/lib/screening-summary";
import { cn, formatDate } from "@/lib/utils";

export interface ScreeningSummaryViewProps {
  state: ScreeningFormState;
  /** Komunikat „…tylko do odczytu” — tylko tam, gdzie widok zastępuje formularz. */
  showLockNote?: boolean;
  /** „Edytuj” otwiera formularz w tym samym panelu. */
  onEdit?: () => void;
  /** Link do formularza, gdy ekran nie ma go u siebie (przegląd DL, profil). */
  editHref?: string;
  /** Zwinięte „W starym formacie” (`ScreeningLegacyText`). */
  legacy?: ReactNode;
  className?: string;
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <h4 className="text-xs font-semibold text-muted-foreground">{children}</h4>;
}

export function ScreeningSummaryView({
  state,
  showLockNote = false,
  onEdit,
  editHref,
  legacy,
  className,
}: ScreeningSummaryViewProps) {
  const sheet = state.sheet;
  const rows = screeningSummaryRows(state);
  const warning = screeningDealBreakerWarning(rows);
  const answered = screeningAnsweredLabel(rows);
  const fields = state.card?.fields ?? {};
  const missing = (state.card?.completeness?.missing ?? []).map((key) => formFieldLabel(state, key));
  const assessmentKeys = cardAssessmentKeys(state);
  // Rekrutacja bez pytań w profilu: pytania pochodzą z samej notatki.
  const questionsTitle = formQuestions(state).length > 0 ? "Pytania z Profilu Championa" : "Pytania i odpowiedzi";
  const hasExtras =
    (sheet?.experience_checks ?? []).some((check) => check.status !== "unknown") ||
    Boolean(state.legacy_notes?.trim()) ||
    Boolean(sheet?.internal_note?.trim());

  const fieldRow = (key: string) => {
    const field = fields[key];
    const value = cardFieldValue(key, field);
    const hint = state.card ? screeningFieldHint(state.card, key) : null;
    return (
      <div key={key} className="grid grid-cols-[8.5rem_minmax(0,1fr)] items-start gap-x-2 text-xs">
        <dt className="text-muted-foreground">
          {formFieldLabel(state, key)}
          {key === "red_flags" ? " — tylko dla zespołu" : ""}
        </dt>
        <dd
          className={cn(
            "whitespace-pre-line [overflow-wrap:anywhere]",
            value ? "font-medium text-foreground" : "text-muted-foreground",
          )}
          title={cardFieldSource(field) ?? undefined}
        >
          {value || (hint ? `brak — ostatnio: ${hint}` : "brak")}
        </dd>
      </div>
    );
  };

  const rateText = state.rate ? formatFormRate(state.rate) : (state.rate_text?.trim() ?? "");

  return (
    <div className={cn("space-y-4 text-[13px]", className)} data-testid="screening-form-readonly">
      {showLockNote && state.read_only_message ? (
        <p role="note" className="flex items-start gap-2 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
          <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {state.read_only_message}
        </p>
      ) : null}

      <p
        className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground"
        data-testid="screening-summary-status"
      >
        {sheet ? (
          <Badge size="sm" variant={SCREENING_FIT_VARIANT[sheet.overall_fit]}>
            {SCREENING_FIT_LABEL[sheet.overall_fit]}
          </Badge>
        ) : null}
        {answered ? <span>Odpowiedzi: {answered}</span> : null}
        <span title={missing.length ? `Brakuje: ${missing.join(", ")}` : undefined}>
          {missing.length ? `Brakuje pól: ${missing.length}` : "Wszystkie pola wypełnione"}
        </span>
        {sheet?.answered_at ? <span>Wypełniono {formatDate(sheet.answered_at)}</span> : null}
      </p>

      {warning ? (
        <p
          role="note"
          data-testid="screening-summary-deal-breaker"
          className="flex items-start gap-1.5 rounded-md bg-warning-muted px-2 py-1.5 text-xs text-warning-muted-foreground"
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {warning}
        </p>
      ) : null}

      <div className="space-y-1.5">
        <SectionTitle>Warunki</SectionTitle>
        <dl className="space-y-1.5" data-testid="screening-form-readonly-terms">
          <div className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-x-2 text-xs">
            <dt className="text-muted-foreground">Stawka kandydata</dt>
            <dd className={cn(rateText ? "font-medium text-foreground" : "text-muted-foreground")}>
              {rateText || "brak"}
            </dd>
          </div>
          {cardTermsKeys(state).map(fieldRow)}
        </dl>
      </div>

      <div className="space-y-1.5">
        <SectionTitle>{questionsTitle}</SectionTitle>
        {rows.length > 0 || hasExtras ? (
          <ScreeningAnswersList
            answers={rows}
            experienceChecks={sheet?.experience_checks}
            notes={state.legacy_notes}
            internalNote={sheet?.internal_note}
          />
        ) : null}
        {rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">Ta rekrutacja nie ma pytań ani zapisanych odpowiedzi.</p>
        ) : null}
      </div>

      {assessmentKeys.length > 0 ? (
        <div className="space-y-1.5">
          <SectionTitle>Ocena</SectionTitle>
          <dl className="space-y-1.5" data-testid="screening-form-readonly-assessment">
            {assessmentKeys.map(fieldRow)}
          </dl>
        </div>
      ) : null}

      {onEdit || editHref ? (
        <div>
          {onEdit ? (
            <Button type="button" size="sm" variant="outline" onClick={onEdit}>
              <PencilLine className="size-3.5" aria-hidden /> Edytuj
            </Button>
          ) : editHref ? (
            <Button asChild size="sm" variant="outline">
              <Link href={editHref}>
                <PencilLine className="size-3.5" aria-hidden /> Edytuj w screeningu
              </Link>
            </Button>
          ) : null}
        </div>
      ) : null}

      {legacy}
    </div>
  );
}

/**
 * Tekst w dotychczasowym formacie działu (do wklejenia w notatkę albo mail).
 * Zwinięty — zapytanie idzie dopiero po rozwinięciu.
 */
export function ScreeningLegacyText({ candidateId, jobId }: { candidateId: number; jobId: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-border" data-testid="screening-legacy-text">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-xs font-medium text-foreground"
      >
        <ChevronRight className={cn("size-3.5 shrink-0 transition-transform", open && "rotate-90")} aria-hidden />
        W starym formacie
      </button>
      {open ? <LegacyTextBody candidateId={candidateId} jobId={jobId} /> : null}
    </div>
  );
}

/** Treść po rozwinięciu — osobno, żeby zwinięty widok nie potrzebował zapytania ani powiadomień. */
function LegacyTextBody({ candidateId, jobId }: { candidateId: number; jobId: number }) {
  const { showError, showInfo } = useToast();
  const query = useRecommendationCard(candidateId, jobId);
  const text = query.data?.legacy_text ?? "";

  const copy = async () => {
    const copied = await copyTextToClipboard(text);
    if (copied) showInfo("Skopiowano tekst w starym formacie.");
    else showError("Nie udało się skopiować — zaznacz tekst i skopiuj ręcznie.");
  };

  return (
    <div className="space-y-2 border-t border-border p-2">
      {query.isLoading ? (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie…
        </p>
      ) : query.isError ? (
        <div className="space-y-2 text-xs">
          <p className="text-destructive">Nie udało się wczytać tekstu.</p>
          <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
            Ponów
          </Button>
        </div>
      ) : query.isSuccess ? (
        <>
          <Button type="button" size="sm" variant="outline" onClick={() => void copy()}>
            <Copy className="size-3.5" aria-hidden /> Kopiuj
          </Button>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted/40 p-3 text-[11px] leading-relaxed text-foreground">
            {text}
          </pre>
        </>
      ) : null}
    </div>
  );
}

export interface ScreeningSummarySectionProps {
  candidateId: number;
  jobId: number;
  enabled?: boolean;
  showLockNote?: boolean;
  onEdit?: () => void;
  editHref?: string;
  className?: string;
}

/** Widok „Screening” z własnym zapytaniem — awaria nie wygląda jak pusty screening. */
export function ScreeningSummarySection({
  candidateId,
  jobId,
  enabled = true,
  showLockNote = false,
  onEdit,
  editHref,
  className,
}: ScreeningSummarySectionProps) {
  const query = useScreeningFormState(candidateId, jobId, enabled);
  if (query.isLoading) {
    return (
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie screeningu…
      </p>
    );
  }
  if (query.isError) {
    return (
      <div className="space-y-2 text-xs">
        <p role="alert" className="text-destructive">
          Nie udało się wczytać screeningu.
        </p>
        <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
          Ponów
        </Button>
      </div>
    );
  }
  if (!query.data) return null;
  return (
    <ScreeningSummaryView
      state={query.data}
      showLockNote={showLockNote}
      onEdit={onEdit}
      editHref={editHref}
      className={className}
      legacy={<ScreeningLegacyText candidateId={candidateId} jobId={jobId} />}
    />
  );
}
