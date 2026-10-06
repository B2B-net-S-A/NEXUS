"use client";

/**
 * Zwarta karta rekomendacji obok notatki (0413, makieta „Osoba w Screeningu”).
 *
 * Komponent prezentacyjny: dostaje kartę z serwera i zapisuje pojedyncze pole
 * przez `onSave`. Kompletność („brakuje N”) liczy serwer. Braki niczego nie
 * blokują — „Dopisz” otwiera pole w miejscu.
 */

import { useId, useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useSetDealBreakerHit,
  type RecommendationCard,
  type RecommendationCardQuestion,
} from "@/lib/api/recommendationCards";
import {
  answeredQuestions,
  dealBreakerWarning,
  CARD_FIELD_HINT,
  CARD_FIELD_ORDER,
  CARD_MULTILINE_FIELDS,
  cardFieldLabel,
  cardFieldSource,
  cardFieldValue,
  cardStatusLabel,
} from "@/lib/recommendation-card";
import { cn } from "@/lib/utils";
import { AnswerOriginBadge } from "./ScreeningAnswersList";

export interface RecommendationCardViewProps {
  card: RecommendationCard;
  readOnly?: boolean;
  saving?: boolean;
  onSave: (fields: Record<string, string | null>) => void;
  onOpenFull?: () => void;
}

export function RecommendationCardStatus({ card }: { card: RecommendationCard }) {
  const complete = card.completeness.status === "complete";
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[11px] font-medium",
        complete ? "bg-success/15 text-success" : "bg-warning/15 text-warning",
      )}
    >
      {cardStatusLabel(card)}
    </span>
  );
}

/** Pole wyboru „Odpowiedź narusza deal-breaker” — prezentacyjne. */
function DealBreakerHitCheckbox({
  question,
  pending,
  onChange,
}: {
  question: RecommendationCardQuestion;
  pending: boolean;
  onChange: (hit: boolean) => void;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="mt-1.5 inline-flex cursor-pointer items-center gap-2 text-[11px] text-foreground">
      <Checkbox
        id={id}
        checked={question.deal_breaker_hit === true}
        disabled={pending}
        onCheckedChange={(checked) => onChange(checked === true)}
      />
      Odpowiedź narusza deal-breaker
      {pending ? <Loader2 className="size-3 animate-spin text-muted-foreground" aria-hidden /> : null}
    </label>
  );
}

/** To samo pole z zapisem na serwerze (`POST /api/recommendation-cards/deal-breaker`).
 *  Osobny komponent, żeby podgląd tylko do odczytu nie potrzebował klienta zapytań. */
function ConnectedDealBreakerHit({
  card,
  question,
}: {
  card: RecommendationCard;
  question: RecommendationCardQuestion & { question_id: string | number };
}) {
  const { showError } = useToast();
  const mutation = useSetDealBreakerHit(card.candidate_id, card.job_id);
  return (
    <DealBreakerHitCheckbox
      question={question}
      pending={mutation.isPending}
      onChange={(hit) =>
        mutation.mutate(
          { questionId: question.question_id, hit },
          {
            onError: (err) =>
              showError(apiErrorMessage(err, "Nie udało się zapisać odpowiedzi. Spróbuj ponownie.")),
          },
        )
      }
    />
  );
}

export interface RecommendationCardQuestionsProps {
  card: RecommendationCard;
  /** Pokaż pole „Odpowiedź narusza deal-breaker” przy pytaniach z „Odpada, gdy…”. */
  editable?: boolean;
  /** Zapis trafienia bez serwera (harness). Bez niego pole zapisuje przez API. */
  onDealBreakerHitChange?: (questionId: string | number, hit: boolean) => void;
}

/** Pytania z Profilu Championa z odpowiedziami — arkusz screeningu, a gdy go
 *  nie ma, odpowiedzi z notatki (tylko do odczytu). Pod pytaniem z „Odpada,
 *  gdy…” treść warunku i — przy edycji — zaznaczenie trafienia, które daje
 *  ostrzeżenie w „Przesuń dalej”. */
export function RecommendationCardQuestions({
  card,
  editable = false,
  onDealBreakerHitChange,
}: RecommendationCardQuestionsProps) {
  if (!card.questions.length) return null;
  return (
    <section aria-label="Pytania z Profilu Championa" className="space-y-2">
      <h3 className="text-xs font-semibold text-foreground">Pytania z Profilu Championa</h3>
      <ol className="space-y-2">
        {card.questions.map((item) => {
          const dealBreaker = item.deal_breaker?.trim() || null;
          const questionId = item.question_id ?? null;
          // Trafienie zapisuje się w arkuszu screeningu, a odpowiedzi z notatek
          // do arkusza nie trafiają — pole stoi tylko przy odpowiedzi z arkusza.
          const canMark =
            editable && dealBreaker != null && questionId != null && item.source === "sheet";
          return (
            <li
              key={item.number}
              data-deal-breaker-hit={item.deal_breaker_hit ? "true" : undefined}
              className="rounded-md border border-border p-2.5 text-xs"
            >
              <p className="font-medium text-foreground">
                {item.number}. {item.question || "pytanie bez treści"}
              </p>
              <p
                className={
                  item.answer
                    ? "mt-1 whitespace-pre-line text-foreground"
                    : "mt-1 text-muted-foreground"
                }
              >
                {item.answer || "brak odpowiedzi"}
              </p>
              {item.source === "note" ? (
                <p className="mt-1 text-[11px] text-muted-foreground">odpowiedź z notatki</p>
              ) : item.origin ? (
                <p className="mt-1">
                  <AnswerOriginBadge origin={item.origin} keywords={item.keywords} />
                </p>
              ) : null}
              {dealBreaker ? (
                <p className="mt-1 text-[11px] text-destructive">Odpada, gdy: {dealBreaker}</p>
              ) : null}
              {canMark ? (
                onDealBreakerHitChange ? (
                  <DealBreakerHitCheckbox
                    question={item}
                    pending={false}
                    onChange={(hit) => onDealBreakerHitChange(questionId, hit)}
                  />
                ) : (
                  <ConnectedDealBreakerHit card={card} question={{ ...item, question_id: questionId }} />
                )
              ) : item.deal_breaker_hit ? (
                <p className="mt-1 text-[11px] font-medium text-destructive">
                  Odpowiedź narusza deal-breaker
                </p>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function RecommendationCardView({
  card,
  readOnly = false,
  saving = false,
  onSave,
  onOpenFull,
}: RecommendationCardViewProps) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const questions = answeredQuestions(card);
  const dealBreaker = dealBreakerWarning(card);

  const startEdit = (key: string) => {
    setEditing(key);
    setDraft(
      String(card.fields[key]?.raw ?? card.previous[key]?.raw ?? card.suggestions[key] ?? ""),
    );
  };
  const submit = (key: string) => {
    const value = draft.trim();
    const current = card.fields[key];
    // Puste pole zdejmuje tylko wartość wpisaną w NEXUSIE — wartości z notatki
    // nie da się stąd usunąć (zmienia ją poprawka notatki albo wpisanie innej).
    const changed = value
      ? value !== String(current?.raw ?? "").trim() || !current
      : current?.source === "manual";
    if (changed) onSave({ [key]: value || null });
    setEditing(null);
  };

  return (
    <div className="space-y-2" data-testid="recommendation-card">
      {dealBreaker ? (
        <p
          role="note"
          className="flex items-start gap-1.5 rounded-md bg-warning-muted px-2 py-1.5 text-xs text-warning-muted-foreground"
        >
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {dealBreaker}
        </p>
      ) : null}
      <dl className="space-y-1.5">
        {CARD_FIELD_ORDER.map((key) => {
          const field = card.fields[key];
          const value = cardFieldValue(key, field);
          const label = cardFieldLabel(card, key);
          const hint = card.previous[key]?.raw ?? card.suggestions[key];
          const multiline = CARD_MULTILINE_FIELDS.has(key);
          const inputId = `card-field-${key}`;
          return (
            <div key={key} className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-start gap-x-2 text-xs">
              <dt className="pt-0.5 text-muted-foreground">
                {editing === key ? <label htmlFor={inputId}>{label}</label> : label}
              </dt>
              <dd className="min-w-0">
                {editing === key ? (
                  <form
                    className="space-y-1.5"
                    onSubmit={(event) => {
                      event.preventDefault();
                      submit(key);
                    }}
                  >
                    {multiline ? (
                      <Textarea
                        id={inputId}
                        value={draft}
                        rows={3}
                        autoFocus
                        placeholder={CARD_FIELD_HINT[key]}
                        onChange={(event) => setDraft(event.target.value)}
                      />
                    ) : (
                      <Input
                        id={inputId}
                        value={draft}
                        autoFocus
                        placeholder={CARD_FIELD_HINT[key]}
                        onChange={(event) => setDraft(event.target.value)}
                      />
                    )}
                    <div className="flex gap-1.5">
                      <Button type="submit" size="sm" disabled={saving}>
                        Zapisz
                      </Button>
                      <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(null)}>
                        Anuluj
                      </Button>
                    </div>
                  </form>
                ) : (
                  <div className="flex items-start gap-2">
                    <span
                      className={cn(
                        "min-w-0 flex-1 whitespace-pre-line break-words",
                        value ? "font-medium text-foreground" : "text-muted-foreground",
                      )}
                      title={cardFieldSource(field) ?? undefined}
                    >
                      {value || (hint ? `brak — ostatnio: ${hint}` : "brak")}
                    </span>
                    {readOnly ? null : (
                      <button
                        type="button"
                        className="hit-area shrink-0 text-[11px] font-medium text-primary hover:underline"
                        aria-label={`${value ? "Zmień" : "Dopisz"}: ${label}`}
                        onClick={() => startEdit(key)}
                      >
                        {value ? "Zmień" : "Dopisz"}
                      </button>
                    )}
                  </div>
                )}
              </dd>
            </div>
          );
        })}
        {questions ? (
          <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-x-2 text-xs">
            <dt className="text-muted-foreground">Pytania</dt>
            <dd className="font-medium text-foreground">{questions}</dd>
          </div>
        ) : null}
      </dl>
      <div className="flex items-center gap-2">
        {onOpenFull ? (
          <Button type="button" size="sm" variant="outline" onClick={onOpenFull}>
            Otwórz całą kartę
          </Button>
        ) : null}
        {saving ? (
          <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden /> Zapisywanie…
          </span>
        ) : null}
      </div>
    </div>
  );
}
