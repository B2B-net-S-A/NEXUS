"use client";

/**
 * Zwarta karta rekomendacji obok notatki (0413, makieta „Osoba w Screeningu”).
 *
 * Komponent prezentacyjny: dostaje kartę z serwera i zapisuje pojedyncze pole
 * przez `onSave`. Kompletność („brakuje N”) liczy serwer. Braki niczego nie
 * blokują — „Dopisz” otwiera pole w miejscu.
 */

import { useState } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { RecommendationCard } from "@/lib/api/recommendationCards";
import {
  answeredQuestions,
  CARD_FIELD_HINT,
  CARD_FIELD_ORDER,
  CARD_MULTILINE_FIELDS,
  cardFieldLabel,
  cardFieldSource,
  cardFieldValue,
  cardStatusLabel,
} from "@/lib/recommendation-card";
import { cn } from "@/lib/utils";

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

  const startEdit = (key: string) => {
    setEditing(key);
    setDraft(
      String(card.fields[key]?.raw ?? card.previous[key]?.raw ?? card.suggestions[key] ?? ""),
    );
  };
  const submit = (key: string) => {
    const value = draft.trim();
    if (value !== String(card.fields[key]?.raw ?? "").trim() || !card.fields[key]) {
      onSave({ [key]: value || null });
    }
    setEditing(null);
  };

  return (
    <div className="space-y-2" data-testid="recommendation-card">
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
