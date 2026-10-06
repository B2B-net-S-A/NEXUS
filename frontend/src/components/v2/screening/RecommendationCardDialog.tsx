"use client";

/**
 * Cała karta rekomendacji (0413, makieta „Cała karta rekomendacji”): wszystkie
 * pola do edycji, pytania z Profilu Championa z odpowiedziami i podgląd
 * w dotychczasowym formacie działu z „Kopiuj”.
 *
 * `RecommendationCardForm` jest prezentacyjny (harness renderuje go bez
 * zapytań); `RecommendationCardDialog` dokłada odczyt i zapis.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Copy, Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  type CardSaveInput,
  type NoteProposal,
  type RecommendationCard,
  recommendationCardsApi,
  useApplyNote,
  useRecommendationCard,
  useSaveRecommendationCard,
} from "@/lib/api/recommendationCards";
import { copyTextToClipboard } from "@/lib/clipboard";
import {
  CARD_FIELD_HINT,
  CARD_FIELD_ORDER,
  CARD_MULTILINE_FIELDS,
  CARD_PHRASABLE_FIELDS,
  cardChanges,
  cardFieldLabel,
  cardFieldSource,
} from "@/lib/recommendation-card";
import {
  type NoteReviewState,
  buildApplyInput,
  initialReviewState,
  selectedCount,
} from "@/lib/recommendation-card-note";

import {
  type PhraseController,
  PhraseButton,
  PhraseLanguageToggle,
  PhraseProposal,
  usePhraseSuggestions,
} from "./PhraseSuggestion";
import {
  type NoteSource,
  NoteSourceInput,
  NoteSourceTiles,
  RecommendationCardNoteReview,
} from "./RecommendationCardNoteImport";
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
  /** „Ułóż w zdanie” przy polach opisowych (D4) — bez niego przycisku nie ma. */
  phrase?: PhraseController;
  /** Przyjęte zdanie z haseł: pole dostaje zdanie, a hasła idą obok przy zapisie. */
  onUsePhrase?: (key: string, sentence: string, keywords: string) => void;
  /** Pola, w których stoi zdanie z haseł (podpis pod polem). */
  phrasedKeys?: ReadonlySet<string>;
}

export function RecommendationCardForm({
  card,
  readOnly = false,
  draft,
  onDraftChange,
  onCopy,
  phrase,
  onUsePhrase,
  phrasedKeys,
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

        <RecommendationCardQuestions card={card} editable={!readOnly} />

        {CARD_FIELD_ORDER.filter((key) => CARD_MULTILINE_FIELDS.has(key)).map((key) => {
          const id = `full-card-${key}`;
          const value = draft[key] ?? "";
          const suggestion = phrase?.results[key];
          const source = phrasedKeys?.has(key)
            ? "zdanie z haseł — zapisz kartę"
            : cardFieldSource(card.fields[key]);
          const canPhrase = phrase != null && !readOnly && CARD_PHRASABLE_FIELDS.has(key);
          return (
            <div key={key} className="space-y-1">
              <label htmlFor={id} className="text-xs font-medium text-foreground">
                {cardFieldLabel(card, key)}
                {key === "red_flags" ? " — tylko dla zespołu" : ""}
              </label>
              <Textarea
                id={id}
                rows={key === "recommendation" ? 5 : 3}
                value={value}
                disabled={readOnly}
                placeholder={CARD_FIELD_HINT[key]}
                onChange={(event) => onDraftChange(key, event.target.value)}
              />
              {source ? <p className="text-[11px] text-muted-foreground">{source}</p> : null}
              {canPhrase && !suggestion ? (
                <PhraseButton
                  disabled={!value.trim()}
                  pending={phrase.isPending(key)}
                  onClick={() =>
                    void phrase.request([{ key, keywords: value, question: cardFieldLabel(card, key) }])
                  }
                />
              ) : null}
              {canPhrase && suggestion ? (
                <PhraseProposal
                  suggestion={suggestion}
                  onUse={(sentence) => {
                    onUsePhrase?.(key, sentence, suggestion.keywords);
                    phrase.dismiss(key);
                  }}
                  onEdit={(sentence) => {
                    onUsePhrase?.(key, sentence, suggestion.keywords);
                    phrase.dismiss(key);
                    document.getElementById(id)?.focus();
                  }}
                  onKeep={() => phrase.dismiss(key)}
                />
              ) : null}
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
  /** Arkusz screeningu w warsztacie ma niezapisane odpowiedzi — odczyt notatki
   *  nadpisałby je po zapisie, więc czeka na „Zapisz screening”. */
  screeningDirty?: boolean;
}

type DialogStep = "edit" | "review";

export function RecommendationCardDialog({
  open,
  onOpenChange,
  candidateId,
  jobId,
  candidateName,
  readOnly = false,
  screeningDirty = false,
}: RecommendationCardDialogProps) {
  const { showSuccess, showError, showInfo } = useToast();
  const query = useRecommendationCard(candidateId, jobId, open);
  const save = useSaveRecommendationCard(candidateId, jobId);
  const apply = useApplyNote(candidateId, jobId);
  const card = query.data;
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [phrased, setPhrased] = useState<Record<string, string>>({});
  const [source, setSource] = useState<NoteSource>("manual");
  const [noteFile, setNoteFile] = useState<File | null>(null);
  const [noteText, setNoteText] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);
  const [step, setStep] = useState<DialogStep>("edit");
  const [proposal, setProposal] = useState<NoteProposal | null>(null);
  const [review, setReview] = useState<NoteReviewState>({ fields: {}, answers: {} });
  const assist = Boolean(card?.assist_enabled) && !readOnly;
  const phrase = usePhraseSuggestions({
    candidateId,
    jobId,
    defaultLanguage: card?.phrase_language,
  });

  // Nowa wersja karty z serwera (otwarcie okna, zapis) zastępuje formularz.
  const version = card ? `${card.candidate_id}:${card.job_id}:${card.updated_at ?? ""}` : null;
  useEffect(() => {
    if (card) setDraft(initialDraft(card));
    setPhrased({});
    // eslint-disable-next-line react-hooks/exhaustive-deps -- tylko zmiana wersji karty
  }, [version]);

  const resetNote = () => {
    setStep("edit");
    setProposal(null);
    setSource("manual");
    setNoteFile(null);
    setNoteText("");
    setFileError(null);
  };
  // Zamknięte okno albo inna osoba — następnym razem od formularza.
  useEffect(() => {
    if (!open) resetNote();
  }, [open, candidateId, jobId]);

  const changes = useMemo(() => (card ? cardChanges(card, draft) : {}), [card, draft]);
  const dirty = Object.keys(changes).length > 0;

  // Odczyt trwa do minuty: wynik liczy się tylko dla osoby i otwartego okna,
  // dla których ruszył — inaczej propozycja osoby A trafiłaby do karty osoby B
  // (okno nie jest montowane od nowa przy zmianie osoby w kolejce).
  const scopeRef = useRef("");
  scopeRef.current = open ? `${candidateId}:${jobId}` : "";
  const read = useMutation({
    mutationFn: async () => {
      const scope = `${candidateId}:${jobId}`;
      const result =
        source === "file" && noteFile
          ? await recommendationCardsApi.readNoteFile(candidateId, jobId, noteFile)
          : await recommendationCardsApi.readNote(candidateId, jobId, noteText);
      return { scope, result };
    },
    onSuccess: ({ scope, result }) => {
      if (scope !== scopeRef.current) return;
      setProposal(result);
      setReview(initialReviewState(result));
      setStep("review");
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się odczytać notatki. Spróbuj ponownie.")),
  });

  const blockedReason = screeningDirty
    ? "Masz niezapisane odpowiedzi w arkuszu screeningu — zapisz je przed odczytem notatki."
    : dirty
      ? "Masz niezapisane zmiany w karcie — zapisz je albo cofnij przed odczytem notatki."
      : null;
  const sourceName = source === "file" && noteFile ? noteFile.name : null;
  const chosen = selectedCount(review);

  const applySelected = () => {
    if (!proposal || apply.isPending) return;
    apply.mutate(buildApplyInput(proposal, review, sourceName), {
      onSuccess: () => {
        showSuccess("Karta uzupełniona z notatki.");
        resetNote();
      },
      onError: (err) => showError(apiErrorMessage(err, "Nie udało się zapisać karty. Spróbuj ponownie.")),
    });
  };

  const submit = () => {
    if (!dirty || save.isPending) return;
    const origins: NonNullable<CardSaveInput["origins"]> = {};
    for (const [key, keywords] of Object.entries(phrased)) {
      if (changes[key]) origins[key] = { origin: "phrased", keywords };
    }
    save.mutate({ fields: changes, origins }, {
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
        step === "review" && proposal ? (
          <>
            <Button variant="outline" onClick={() => setStep("edit")} disabled={apply.isPending}>
              Wróć
            </Button>
            <Button onClick={applySelected} disabled={chosen === 0 || apply.isPending}>
              {apply.isPending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
              Zastosuj zaznaczone ({chosen})
            </Button>
          </>
        ) : (
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
        )
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
        ) : card && step === "review" && proposal ? (
          <RecommendationCardNoteReview
            proposal={proposal}
            state={review}
            onChange={setReview}
            sourceLabel={sourceName ? `pliku ${sourceName}` : "wklejonego tekstu"}
          />
        ) : card ? (
          <div className="space-y-3">
            <RecommendationCardStatus card={card} />
            {assist ? (
              <NoteSourceTiles value={source} onChange={setSource} disabled={read.isPending} />
            ) : null}
            {assist && source !== "manual" ? (
              <NoteSourceInput
                source={source}
                file={noteFile}
                onFileChange={setNoteFile}
                text={noteText}
                onTextChange={setNoteText}
                fileError={fileError}
                onFileError={setFileError}
                reading={read.isPending}
                blockedReason={blockedReason}
                onRead={() => read.mutate()}
              />
            ) : (
              <>
                {assist ? (
                  <div className="flex items-center justify-end gap-2 text-[11px] text-muted-foreground">
                    Język zdań
                    <PhraseLanguageToggle
                      idPrefix="card-phrase-language"
                      value={phrase.language}
                      onChange={phrase.setLanguage}
                    />
                  </div>
                ) : null}
                <RecommendationCardForm
                  card={card}
                  readOnly={readOnly}
                  draft={draft}
                  onDraftChange={(key, value) => {
                    setDraft((prev) => ({ ...prev, [key]: value }));
                    // Wyczyszczone pole nie jest już zdaniem z haseł.
                    if (!value.trim()) {
                      setPhrased((prev) => {
                        if (!(key in prev)) return prev;
                        const next = { ...prev };
                        delete next[key];
                        return next;
                      });
                    }
                  }}
                  onCopy={() => void copy()}
                  phrase={assist ? phrase : undefined}
                  phrasedKeys={new Set(Object.keys(phrased))}
                  onUsePhrase={(key, sentence, keywords) => {
                    setDraft((prev) => ({ ...prev, [key]: sentence }));
                    setPhrased((prev) => ({ ...prev, [key]: keywords }));
                  }}
                />
              </>
            )}
          </div>
        ) : null}
      </div>
    </AppModal>
  );
}
