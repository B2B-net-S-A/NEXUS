"use client";

// Publiczny harness karty rekomendacji (0413): zwarta karta z doku osoby,
// cała karta z podglądem w starym formacie i plakietki na tablicy.
// Dane fikcyjne, ZERO zapytań — komponenty prezentacyjne dostają kartę
// propsem, „Zapisz” zmienia tylko stan strony.
// `?state=complete` — karta gotowa, `?state=empty` — karta pusta,
// `?state=readonly` — podgląd bez edycji.

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { RecommendationCardForm } from "@/components/v2/screening/RecommendationCardDialog";
import {
  RecommendationCardQuestions,
  RecommendationCardStatus,
  RecommendationCardView,
} from "@/components/v2/screening/RecommendationCardView";
import type { RecommendationCard } from "@/lib/api/recommendationCards";
import { CARD_BADGE_TONE_CLASS } from "@/lib/board-card-badges";
import { boardCardBadge } from "@/lib/recommendation-card";

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

function Harness() {
  const state = useSearchParams().get("state");
  const initial = state === "complete" ? COMPLETE : state === "empty" ? EMPTY : PARTIAL;
  const readOnly = state === "readonly";
  const [card, setCard] = useState(initial);
  const [draft, setDraft] = useState<Record<string, string>>(
    Object.fromEntries(card.editable_fields.map((key) => [key, String(card.fields[key]?.raw ?? "")])),
  );
  const [copied, setCopied] = useState(false);

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
