"use client";

/**
 * Cała karta rekomendacji (0413, makieta „Cała karta rekomendacji”): wszystkie
 * pola do edycji, pytania z Profilu Championa z odpowiedziami i podgląd
 * w dotychczasowym formacie działu z „Kopiuj”.
 *
 * `RecommendationCardForm` jest prezentacyjny (harness renderuje go bez
 * zapytań); `RecommendationCardDialog` dokłada odczyt i zapis.
 */

import { useEffect, useMemo, useState } from "react";
import { Copy, Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  type RecommendationCard,
  useRecommendationCard,
  useSaveRecommendationCard,
} from "@/lib/api/recommendationCards";
import { copyTextToClipboard } from "@/lib/clipboard";
import {
  CARD_FIELD_HINT,
  CARD_FIELD_ORDER,
  CARD_MULTILINE_FIELDS,
  cardChanges,
  cardFieldLabel,
  cardFieldSource,
} from "@/lib/recommendation-card";

import { RecommendationCardQuestions, RecommendationCardStatus } from "./RecommendationCardView";

function initialDraft(card: RecommendationCard): Record<string, string> {
  return Object.fromEntries(
    card.editable_fields.map((key) => [key, String(card.fields[key]?.raw ?? "")]),
  );
}

export interface RecommendationCardFormProps {
  card: RecommendationCard;
  readOnly?: boolean;
  draft: Record<string, string>;
  onDraftChange: (key: string, value: string) => void;
  onCopy: () => void;
}

export function RecommendationCardForm({
  card,
  readOnly = false,
  draft,
  onDraftChange,
  onCopy,
}: RecommendationCardFormProps) {
  const missing = card.completeness.missing.map((key) => cardFieldLabel(card, key));
  return (
    <div className="grid gap-6 @3xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div className="space-y-4">
        <div className="grid gap-3 @lg:grid-cols-2">
          {CARD_FIELD_ORDER.filter((key) => !CARD_MULTILINE_FIELDS.has(key)).map((key) => {
            const id = `full-card-${key}`;
            const hint = card.previous[key]?.raw ?? card.suggestions[key];
            const source = cardFieldSource(card.fields[key]);
            return (
              <div key={key} className="space-y-1">
                <label htmlFor={id} className="text-xs font-medium text-foreground">
                  {cardFieldLabel(card, key)}
                </label>
                <Input
                  id={id}
                  value={draft[key] ?? ""}
                  disabled={readOnly}
                  placeholder={hint ? `ostatnio: ${hint}` : CARD_FIELD_HINT[key]}
                  onChange={(event) => onDraftChange(key, event.target.value)}
                />
                {source ? <p className="text-[11px] text-muted-foreground">{source}</p> : null}
              </div>
            );
          })}
        </div>

        <RecommendationCardQuestions card={card} />

        {CARD_FIELD_ORDER.filter((key) => CARD_MULTILINE_FIELDS.has(key)).map((key) => {
          const id = `full-card-${key}`;
          return (
            <div key={key} className="space-y-1">
              <label htmlFor={id} className="text-xs font-medium text-foreground">
                {cardFieldLabel(card, key)}
                {key === "red_flags" ? " — tylko dla zespołu" : ""}
              </label>
              <Textarea
                id={id}
                rows={key === "recommendation" ? 5 : 3}
                value={draft[key] ?? ""}
                disabled={readOnly}
                placeholder={CARD_FIELD_HINT[key]}
                onChange={(event) => onDraftChange(key, event.target.value)}
              />
            </div>
          );
        })}

        <p className="text-xs text-muted-foreground">
          {missing.length ? `Brakuje: ${missing.join(", ")}.` : "Karta ma wszystkie pola."} Braki
          nie blokują ruchu karty.
        </p>
      </div>

      <aside aria-labelledby="full-card-legacy" className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h3 id="full-card-legacy" className="text-xs font-semibold text-foreground">
            W starym formacie
          </h3>
          <Button type="button" size="sm" variant="outline" onClick={onCopy}>
            <Copy className="size-3.5" aria-hidden /> Kopiuj
          </Button>
        </div>
        <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted/40 p-3 text-[11px] leading-relaxed text-foreground">
          {card.legacy_text}
        </pre>
        <p className="text-[11px] text-muted-foreground">
          Podgląd pokazuje zapisaną kartę — po zmianie pól zapisz, żeby go odświeżyć.
        </p>
      </aside>
    </div>
  );
}

export interface RecommendationCardDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  jobId: number;
  candidateName: string;
  readOnly?: boolean;
}

export function RecommendationCardDialog({
  open,
  onOpenChange,
  candidateId,
  jobId,
  candidateName,
  readOnly = false,
}: RecommendationCardDialogProps) {
  const { showSuccess, showError, showInfo } = useToast();
  const query = useRecommendationCard(candidateId, jobId, open);
  const save = useSaveRecommendationCard(candidateId, jobId);
  const card = query.data;
  const [draft, setDraft] = useState<Record<string, string>>({});

  // Nowa wersja karty z serwera (otwarcie okna, zapis) zastępuje formularz.
  const version = card ? `${card.candidate_id}:${card.job_id}:${card.updated_at ?? ""}` : null;
  useEffect(() => {
    if (card) setDraft(initialDraft(card));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tylko zmiana wersji karty
  }, [version]);

  const changes = useMemo(() => (card ? cardChanges(card, draft) : {}), [card, draft]);
  const dirty = Object.keys(changes).length > 0;

  const submit = () => {
    if (!dirty || save.isPending) return;
    save.mutate(changes, {
      // Okno znika po zapisie: sam komunikat w rogu ekranu bywał przeoczony
      // i nie było wiadomo, czy karta się zapisała (zgłoszenie 04.10.2026).
      onSuccess: () => {
        showSuccess("Karta rekomendacji zapisana.");
        onOpenChange(false);
      },
      onError: (err) => showError(apiErrorMessage(err, "Nie udało się zapisać karty. Spróbuj ponownie.")),
    });
  };
  const copy = async () => {
    if (!card) return;
    const copied = await copyTextToClipboard(card.legacy_text);
    if (copied) showInfo("Skopiowano kartę w starym formacie.");
    else showError("Nie udało się skopiować — zaznacz tekst i skopiuj ręcznie.");
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title="Karta rekomendacji"
      description={candidateName}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
          {readOnly ? null : (
            <Button onClick={submit} disabled={!dirty || save.isPending}>
              {save.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
              Zapisz kartę
            </Button>
          )}
        </>
      }
    >
      <div className="@container">
        {query.isLoading ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytywanie karty…
          </p>
        ) : query.isError ? (
          <div className="space-y-2 text-xs">
            <p className="text-destructive">Nie udało się wczytać karty.</p>
            <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
              Ponów
            </Button>
          </div>
        ) : card ? (
          <div className="space-y-3">
            <RecommendationCardStatus card={card} />
            <RecommendationCardForm
              card={card}
              readOnly={readOnly}
              draft={draft}
              onDraftChange={(key, value) => setDraft((prev) => ({ ...prev, [key]: value }))}
              onCopy={() => void copy()}
            />
          </div>
        ) : null}
      </div>
    </AppModal>
  );
}
