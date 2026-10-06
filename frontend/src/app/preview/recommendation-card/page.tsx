"use client";

// Publiczny harness karty rekomendacji (0413): zwarta karta z doku osoby,
// cała karta z podglądem w starym formacie i plakietki na tablicy.
// Dane fikcyjne, ZERO zapytań — komponenty prezentacyjne dostają kartę
// propsem, „Zapisz” zmienia tylko stan strony.
// `?state=complete` — karta gotowa, `?state=empty` — karta pusta,
// `?state=readonly` — podgląd bez edycji, `?state=import` — karta z notatki
// (wybór źródła i przegląd propozycji, 0421), `?state=phrase` — „Ułóż
// w zdanie” w polach karty (zdania z gotowej listy, bez modelu).

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import type { PhraseController, PhraseSuggestionState } from "@/components/v2/screening/PhraseSuggestion";
import { RecommendationCardForm } from "@/components/v2/screening/RecommendationCardDialog";
import {
  type NoteSource,
  NoteSourceInput,
  NoteSourceTiles,
  RecommendationCardNoteReview,
} from "@/components/v2/screening/RecommendationCardNoteImport";
import {
  RecommendationCardQuestions,
  RecommendationCardStatus,
  RecommendationCardView,
} from "@/components/v2/screening/RecommendationCardView";
import type { NoteProposal, PhraseLanguage, RecommendationCard } from "@/lib/api/recommendationCards";
import { CARD_BADGE_TONE_CLASS } from "@/lib/board-card-badges";
import { boardCardBadge } from "@/lib/recommendation-card";
import { initialReviewState, selectedCount } from "@/lib/recommendation-card-note";

const LABELS = {
  rate: "Stawka",
  availability: "Dostępność",
  work_mode: "Tryb pracy",
  location: "Lokalizacja",
  nationality: "Narodowość",
  worked_at_client: "Czy pracował u Klienta",
  english: "Angielski",
  red_flags: "Red flags",
  recommendation: "Notatka",
  motivation: "Motywacja",
  client_manager: "Manager u Klienta",
};

const QUESTIONS: RecommendationCard["questions"] = [
  {
    number: 1,
    question: "Rozwiązanie rozwijane w Javie 17+ i Spring Boot",
    answer: "Panel administracyjny i integracje systemu kredytowego. Java 21, Spring Boot 3.",
    source: "sheet",
    question_id: "q1",
    deal_breaker: "nie pracował komercyjnie z Javą 17 lub nowszą",
    deal_breaker_hit: false,
  },
  {
    number: 2,
    question: "Komunikacja między usługami — synchroniczna czy przez kolejki",
    answer: "REST między usługami, Kafka do zdarzeń kredytowych.",
    source: "note",
  },
  {
    number: 3,
    question: "Chmura w projektach komercyjnych",
    answer: "Tylko kursy, bez projektu komercyjnego.",
    source: "sheet",
    question_id: "q3",
    deal_breaker: "brak komercyjnego projektu w chmurze",
    deal_breaker_hit: true,
  },
];

const LEGACY = [
  "Imię i nazwisko: Tomasz Wzorcowy",
  "Stawka: 135 zł/h",
  "Dostępność: 1 miesiąc",
  "Tryb pracy: hybrydowo, 2 dni w tygodniu, Łódź",
  "Lokalizacja: Łódź",
  "Narodowość: polska",
  "Czy pracował u Klienta: nie",
  "Angielski: C1",
  "Nazwa projektu: Senior Java Developer (ZOB-0001)",
  "Nazwa pliku CV:",
  "P1: Rozwiązanie rozwijane w Javie 17+ i Spring Boot",
  "Odpowiedź: Panel administracyjny i integracje systemu kredytowego.",
  "P2: Komunikacja między usługami — synchroniczna czy przez kolejki",
  "Odpowiedź: REST między usługami, Kafka do zdarzeń kredytowych.",
  "P3: Chmura w projektach komercyjnych",
  "Odpowiedź: Tylko kursy, bez projektu komercyjnego.",
  "Red flags:",
  "Notatka: Senior Java developer, dziewięć lat doświadczenia, ostatnie trzy w bankowości.",
  "Motywacja:",
].join("\n");

const PARTIAL: RecommendationCard = {
  candidate_id: 101,
  job_id: 201,
  exists: true,
  fields: {
    rate: { raw: "135 zł/h", value: 135, source: "note", note_id: 1 },
    availability: { raw: "1 miesiąc", source: "note", note_id: 1 },
    work_mode: { raw: "hybrydowo, 2 dni w tygodniu, Łódź", source: "note", note_id: 1 },
    location: { raw: "Łódź", source: "note", note_id: 1 },
    nationality: { raw: "polska", source: "note", note_id: 1 },
    worked_at_client: { raw: "nie", value: "no", source: "note", note_id: 1 },
    english: { raw: "C1", level: "C1", source: "manual", by_name: "Marta Testowa" },
    recommendation: {
      raw: "Senior Java developer, dziewięć lat doświadczenia, ostatnie trzy w bankowości.",
      source: "manual",
      by_name: "Marta Testowa",
    },
  },
  previous: {},
  suggestions: {},
  questions: QUESTIONS,
  completeness: { status: "partial", filled: 8, total: 10, missing: ["red_flags", "motivation"] },
  labels: LABELS,
  editable_fields: Object.keys(LABELS),
  legacy_text: LEGACY,
  updated_at: "2026-09-30T10:00:00Z",
};

const COMPLETE: RecommendationCard = {
  ...PARTIAL,
  fields: {
    ...PARTIAL.fields,
    red_flags: { raw: "brak", none: true, source: "manual", by_name: "Marta Testowa" },
    motivation: { raw: "Szuka projektu z Javą 21 i Kafką.", source: "note", note_id: 1 },
  },
  completeness: { status: "complete", filled: 10, total: 10, missing: [] },
};

const EMPTY: RecommendationCard = {
  ...PARTIAL,
  exists: false,
  fields: {},
  suggestions: { nationality: "polska" },
  questions: QUESTIONS.map((q) => ({ ...q, answer: "", source: null, deal_breaker_hit: false })),
  completeness: {
    status: "empty",
    filled: 0,
    total: 10,
    missing: Object.keys(LABELS).filter((key) => key !== "client_manager"),
  },
};

const BOARD = [
  { name: "Tomasz Wzorcowy", card: { status: "partial", missing: 2, answers: 2 }, attempts: 0 },
  { name: "Marek Fikcyjny", card: null, attempts: 3 },
  { name: "Anna Przykładowa", card: null, attempts: 0 },
  { name: "Piotr Testowy", card: { status: "complete", missing: 0, answers: 3 }, attempts: 0 },
] as const;

const PROPOSAL: NoteProposal = {
  fields: [
    {
      key: "rate",
      label: "Stawka",
      current: "150 zł/h",
      current_source: "note",
      proposed: "165 zł/h netto B2B",
      quote: "stawka 165 netto b2b, niżej nie zejdzie",
      origin: "note_ai",
      changed: true,
    },
    {
      key: "availability",
      label: "Dostępność",
      current: null,
      current_source: null,
      proposed: "1 miesiąc wypowiedzenia, start od listopada",
      quote: "wypow. miesiąc, start od listopada",
      origin: "note_ai",
      changed: true,
    },
    {
      key: "work_mode",
      label: "Tryb pracy",
      current: null,
      current_source: null,
      proposed: "Hybrydowo, do 2 dni w biurze w Warszawie",
      quote: "hybryda ok, max 2 dni w wawie",
      origin: "note_ai",
      changed: true,
    },
    {
      key: "location",
      label: "Lokalizacja",
      current: "Warszawa",
      current_source: "note",
      proposed: "Warszawa",
      quote: null,
      origin: "note_rule",
      changed: false,
    },
    {
      key: "nationality",
      label: "Narodowość",
      current: null,
      current_source: null,
      proposed: "polska",
      quote: null,
      origin: "note_rule",
      changed: true,
    },
    {
      key: "recommendation",
      label: "Dlaczego ten kandydat",
      current: null,
      current_source: null,
      proposed:
        "Kandydat ma 6 lat doświadczenia w Javie i Springu, z czego 4 lata w projektach bankowych (płatności).",
      quote: "6y java spring, 4 lata banki - płatności",
      origin: "note_ai",
      changed: true,
    },
  ],
  answers: [
    {
      question_id: "q1",
      number: 1,
      question: "Czy pracujesz z Kafką?",
      current: null,
      keywords: "kafka 3 lata prod, eventy płatności, consumer groups",
      sentence:
        "Kandydat od 3 lat pracuje z Kafką na produkcji przy zdarzeniach płatności, korzysta z consumer groups.",
      problem: null,
    },
    {
      question_id: "q2",
      number: 2,
      question: "Ile dni w biurze akceptujesz?",
      current: null,
      keywords: "max 2 dni w wawie",
      sentence: null,
      problem: "listopada",
    },
  ],
  available: true,
  message: null,
  language: "pl",
  rate_change_notifies: true,
  text: "notatka z rozmowy",
};

// „Ułóż w zdanie” bez modelu: zdania z gotowej listy po kluczu pola.
const CANNED: Record<string, string> = {
  recommendation:
    "Kandydat ma 6 lat doświadczenia w Javie i Springu, w tym 4 lata w projektach bankowych.",
  motivation: "Obecny projekt kandydata się kończy; szuka dłuższego kontraktu.",
  red_flags: "Brak zastrzeżeń.",
};

function useFakePhrase(): PhraseController {
  const [language, setLanguage] = useState<PhraseLanguage>("pl");
  const [results, setResults] = useState<Record<string, PhraseSuggestionState>>({});
  return {
    language,
    setLanguage,
    results,
    isPending: () => false,
    request: async (items) =>
      setResults((prev) => ({
        ...prev,
        ...Object.fromEntries(
          items.map((item) => [
            item.key,
            {
              key: item.key,
              sentence: CANNED[item.key] ?? null,
              problem: CANNED[item.key] ? null : "maju",
              keywords: item.keywords,
            },
          ]),
        ),
      })),
    dismiss: (key) =>
      setResults((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      }),
  };
}

function ImportPreview() {
  const [source, setSource] = useState<NoteSource>("text");
  const [text, setText] = useState(
    "stawka 165 netto b2b, niżej nie zejdzie\nwypow. miesiąc, start od listopada\nhybryda ok, max 2 dni w wawie\nkafka 3 lata prod, eventy płatności, consumer groups",
  );
  const [review, setReview] = useState(() => initialReviewState(PROPOSAL));
  return (
    <>
      <section aria-labelledby="preview-import-source" className="space-y-2">
        <h2 id="preview-import-source" className="text-sm font-semibold">
          Karta z notatki — wybór źródła
        </h2>
        <div className="@container max-w-3xl space-y-3 rounded-lg border border-border bg-card p-4">
          <NoteSourceTiles value={source} onChange={setSource} />
          {source === "manual" ? (
            <p className="text-xs text-muted-foreground">Tu stoi dotychczasowy formularz karty.</p>
          ) : (
            <NoteSourceInput
              source={source}
              file={null}
              onFileChange={() => undefined}
              text={text}
              onTextChange={setText}
              fileError={null}
              onFileError={() => undefined}
              reading={false}
              onRead={() => undefined}
            />
          )}
        </div>
      </section>
      <section aria-labelledby="preview-import-review" className="space-y-2">
        <h2 id="preview-import-review" className="text-sm font-semibold">
          Przegląd propozycji — „Zastosuj zaznaczone ({selectedCount(review)})”
        </h2>
        <div className="@container max-w-3xl rounded-lg border border-border bg-card p-4">
          <RecommendationCardNoteReview
            proposal={PROPOSAL}
            state={review}
            onChange={setReview}
            sourceLabel="pliku notatka_wzorcowy.docx"
          />
        </div>
      </section>
    </>
  );
}

function Harness() {
  const state = useSearchParams().get("state");
  const initial = state === "complete" ? COMPLETE : state === "empty" ? EMPTY : PARTIAL;
  const readOnly = state === "readonly";
  const [card, setCard] = useState(initial);
  const [draft, setDraft] = useState<Record<string, string>>(
    Object.fromEntries(card.editable_fields.map((key) => [key, String(card.fields[key]?.raw ?? "")])),
  );
  const [copied, setCopied] = useState(false);
  const fakePhrase = useFakePhrase();
  const [phrased, setPhrased] = useState<Record<string, string>>({});

  const save = (fields: Record<string, string | null>) =>
    setCard((prev) => {
      const next = { ...prev.fields };
      for (const [key, value] of Object.entries(fields)) {
        if (value) next[key] = { raw: value, source: "manual", by_name: "Marta Testowa" };
        else delete next[key];
      }
      const missing = prev.completeness.missing.filter((key) => !next[key]);
      return {
        ...prev,
        fields: next,
        completeness: {
          ...prev.completeness,
          missing,
          filled: prev.completeness.total - missing.length,
          status: missing.length ? "partial" : "complete",
        },
      };
    });

  // „Odpowiedź narusza deal-breaker” — w podglądzie zmienia tylko stan strony.
  const setDealBreakerHit = (questionId: string | number, hit: boolean) =>
    setCard((prev) => ({
      ...prev,
      questions: prev.questions.map((q) =>
        q.question_id === questionId ? { ...q, deal_breaker_hit: hit } : q,
      ),
    }));

  return (
    <main className="mx-auto max-w-6xl space-y-8 bg-background p-4 text-foreground md:p-8">
      <header className="space-y-1">
        <h1 className="text-lg font-semibold">Karta rekomendacji — podgląd</h1>
        <p className="text-sm text-muted-foreground">
          Tomasz Wzorcowy · Senior Java Developer · Screening. Dane fikcyjne, nic nie jest zapisywane.
        </p>
      </header>

      {state === "import" ? <ImportPreview /> : null}

      <section aria-labelledby="preview-board" className="space-y-2">
        <h2 id="preview-board" className="text-sm font-semibold">
          Plakietki na tablicy (kolumna Screening)
        </h2>
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {BOARD.map((row) => {
            const badge = boardCardBadge(row.card, row.attempts, "screening");
            return (
              <li key={row.name} className="rounded-lg border border-border bg-card p-3 text-sm">
                <p className="font-medium">{row.name}</p>
                {badge ? (
                  <span
                    className={`mt-1.5 inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${CARD_BADGE_TONE_CLASS[badge.tone]}`}
                    title={badge.title}
                  >
                    {badge.label}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-labelledby="preview-dock" className="space-y-2">
        <h2 id="preview-dock" className="flex items-center gap-2 text-sm font-semibold">
          Zwarta karta w panelu osoby <RecommendationCardStatus card={card} />
        </h2>
        <div className="max-w-[380px] rounded-lg border border-border bg-card p-3">
          <RecommendationCardView card={card} readOnly={readOnly} onSave={save} onOpenFull={() => undefined} />
        </div>
      </section>

      <section aria-labelledby="preview-deal-breaker" className="space-y-2">
        <h2 id="preview-deal-breaker" className="text-sm font-semibold">
          Pytania z „Odpada, gdy…” (przegląd Delivery Leada)
        </h2>
        <div className="max-w-xl rounded-lg border border-border bg-card p-3">
          <RecommendationCardQuestions
            card={card}
            editable={!readOnly}
            onDealBreakerHitChange={setDealBreakerHit}
          />
        </div>
      </section>

      <section aria-labelledby="preview-full" className="space-y-2">
        <h2 id="preview-full" className="text-sm font-semibold">
          Cała karta
        </h2>
        <div className="@container rounded-lg border border-border bg-card p-4">
          <RecommendationCardForm
            card={card}
            readOnly={readOnly}
            draft={draft}
            onDraftChange={(key, value) => setDraft((prev) => ({ ...prev, [key]: value }))}
            onCopy={() => setCopied(true)}
            phrase={state === "phrase" ? fakePhrase : undefined}
            phrasedKeys={new Set(Object.keys(phrased))}
            onUsePhrase={(key, sentence, keywords) => {
              setDraft((prev) => ({ ...prev, [key]: sentence }));
              setPhrased((prev) => ({ ...prev, [key]: keywords }));
            }}
          />
          {copied ? (
            <p role="status" className="mt-2 text-xs text-muted-foreground">
              Skopiowano kartę w starym formacie.
            </p>
          ) : null}
        </div>
      </section>
    </main>
  );
}

export default function RecommendationCardPreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
