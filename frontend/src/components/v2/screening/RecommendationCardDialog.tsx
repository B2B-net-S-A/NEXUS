"use client";

/**
 * Cała karta rekomendacji (0413, makieta „Cała karta rekomendacji”): wszystkie
 * pola, pytania z Profilu Championa z odpowiedziami i podgląd
 * w dotychczasowym formacie działu z „Kopiuj”.
 *
 * Od 0424 (07.10.2026) okno jest TYLKO DO ODCZYTU: pola karty, odpowiedzi
 * i stawkę wpisuje się w jednym formularzu screeningu („Edytuj w screeningu”
 * — panel osoby na zakładce „Screening”). `RecommendationCardFullView` jest
 * prezentacyjny (harness renderuje go bez zapytań).
 */

import Link from "next/link";
import { Copy, Loader2, PencilLine } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { type RecommendationCard, useRecommendationCard } from "@/lib/api/recommendationCards";
import { copyTextToClipboard } from "@/lib/clipboard";
import {
  CARD_FIELD_ORDER,
  cardFieldLabel,
  cardFieldSource,
  cardFieldValue,
} from "@/lib/recommendation-card";
import { cn } from "@/lib/utils";

import { RecommendationCardQuestions, RecommendationCardStatus } from "./RecommendationCardView";

/** Adres formularza screeningu osoby (panel osoby na zakładce „Screening”). */
export function screeningFormHref(jobId: number, candidateId: number): string {
  return `/jobs/${jobId}?candidate=${candidateId}&panel=screening`;
}

export interface RecommendationCardFullViewProps {
  card: RecommendationCard;
  onCopy: () => void;
}

export function RecommendationCardFullView({ card, onCopy }: RecommendationCardFullViewProps) {
  const missing = card.completeness.missing.map((key) => cardFieldLabel(card, key));
  return (
    <div className="grid gap-6 @3xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <div className="space-y-4">
        <dl className="grid gap-x-4 gap-y-2.5 @lg:grid-cols-2">
          {CARD_FIELD_ORDER.map((key) => {
            const field = card.fields[key];
            const value = cardFieldValue(key, field);
            const source = cardFieldSource(field);
            const hint = card.previous[key]?.raw ?? card.suggestions[key];
            return (
              <div key={key} className={cn("space-y-0.5", (key === "recommendation" || key === "motivation" || key === "red_flags") && "@lg:col-span-2")}>
                <dt className="text-xs font-medium text-muted-foreground">
                  {cardFieldLabel(card, key)}
                  {key === "red_flags" ? " — tylko dla zespołu" : ""}
                </dt>
                <dd
                  className={cn(
                    "whitespace-pre-line text-sm [overflow-wrap:anywhere]",
                    value ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  {value || (hint ? `brak — ostatnio: ${hint}` : "brak")}
                </dd>
                {source ? <dd className="text-[11px] text-muted-foreground">{source}</dd> : null}
              </div>
            );
          })}
        </dl>

        <RecommendationCardQuestions card={card} />

        <p className="text-xs text-muted-foreground">
          {missing.length ? `Brakuje: ${missing.join(", ")}.` : "Karta ma wszystkie pola."} Braki nie blokują
          ruchu karty.
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
  /** Bez „Edytuj w screeningu” (np. profil kandydata bez prawa zapisu). */
  readOnly?: boolean;
  /**
   * Formularz screeningu otwarty w tym samym panelu (Tablica). Bez niego
   * „Edytuj w screeningu” prowadzi linkiem do rekrutacji.
   */
  onEditInScreening?: () => void;
}

export function RecommendationCardDialog({
  open,
  onOpenChange,
  candidateId,
  jobId,
  candidateName,
  readOnly = false,
  onEditInScreening,
}: RecommendationCardDialogProps) {
  const { showError, showInfo } = useToast();
  const query = useRecommendationCard(candidateId, jobId, open);
  const card = query.data;

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
          {readOnly ? null : onEditInScreening ? (
            <Button onClick={onEditInScreening}>
              <PencilLine className="size-3.5" aria-hidden /> Edytuj w screeningu
            </Button>
          ) : (
            <Button asChild>
              <Link href={screeningFormHref(jobId, candidateId)}>
                <PencilLine className="size-3.5" aria-hidden /> Edytuj w screeningu
              </Link>
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
            <p className="text-xs text-muted-foreground">
              Kartę uzupełnia się w formularzu screeningu — tam są też odpowiedzi na pytania i stawka kandydata.
            </p>
            <RecommendationCardFullView card={card} onCopy={() => void copy()} />
          </div>
        ) : null}
      </div>
    </AppModal>
  );
}
