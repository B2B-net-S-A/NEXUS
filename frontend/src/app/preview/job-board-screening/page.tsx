"use client";

// Publiczny harness „Odrzuceni przez AI” (0404): zwinięta lista na górze
// kolumny „Nowi” i plakietki przeglądu AI na kartach zgłoszeń z ogłoszenia.
// Dane fikcyjne, ZERO zapytań — lista idzie propsem do komponentu
// prezentacyjnego (`ScreenedOutList`), „Dodaj mimo to” tylko pokazuje stan.
// `?state=empty` — nikogo nie odrzucono (sekcja znika), `?state=error` —
// awaria odczytu z „Ponów”, `?state=closed` — lista zwinięta.

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  ScreenedOutList,
  type ScreenedOutState,
} from "@/components/v2/jobs/ScreenedOutSection";
import type { ScreenedOutItem } from "@/lib/api/applicationScreenings";
import { aiScreeningBadge, CARD_BADGE_TONE_CLASS } from "@/lib/board-card-badges";

const daysAgo = (d: number) => new Date(Date.now() - d * 86_400_000).toISOString();

const ITEMS: ScreenedOutItem[] = [
  {
    id: 1,
    candidate_id: 101,
    name: "Anna",
    lastname: "Przykładowa",
    applied_at: daysAgo(1),
    decided_at: daysAgo(1),
    status: "done",
    verdict: "not_fit",
    source: "justjoinit",
    must_found: 0,
    must_total: 3,
    reasons: [
      {
        text: "Doświadczenie dotyczy księgowości, nie programowania.",
        quote: "Samodzielna księgowa w biurze rachunkowym (2019–2025)",
      },
      {
        text: "CV nie wymienia żadnego języka programowania.",
        quote: "Umiejętności: Excel, Symfonia, Płatnik",
      },
    ],
  },
  {
    id: 2,
    candidate_id: 102,
    name: "Piotr",
    lastname: "Testowy",
    applied_at: daysAgo(2),
    decided_at: daysAgo(2),
    status: "done",
    verdict: "not_fit",
    source: "rocketjobs",
    must_found: 1,
    must_total: 4,
    reasons: [
      {
        text: "Praca w obsłudze klienta, bez roli technicznej.",
        quote: "Konsultant infolinii — Firma Przykładowa sp. z o.o.",
      },
    ],
  },
  {
    id: 3,
    candidate_id: 103,
    name: "Ewa",
    lastname: "Fikcyjna",
    applied_at: daysAgo(3),
    decided_at: null,
    status: "failed",
    verdict: "unclear",
    source: null,
    must_found: null,
    must_total: null,
    reasons: [
      { text: "Nie udało się ocenić ani dodać zgłoszenia automatycznie.", quote: null },
    ],
  },
];

const BADGE_CASES = [
  { who: "Marek Wzorcowy", meta: { verdict: "fits", assessed: true, must_found: 3, must_total: 3, overridden: false } },
  { who: "Ola Próbna", meta: { verdict: "unclear", assessed: true, must_found: 1, must_total: 3, overridden: false } },
  { who: "Jan Kandydacki", meta: { verdict: "unclear", assessed: false, must_found: 0, must_total: 3, overridden: false } },
  { who: "Anna Przykładowa", meta: { verdict: "not_fit", assessed: true, must_found: 0, must_total: 3, overridden: true } },
] as const;

function Harness() {
  const params = useSearchParams();
  const variant = params.get("state");
  const [addingId, setAddingId] = useState<number | null>(null);

  const state: ScreenedOutState =
    variant === "error"
      ? { kind: "error", onRetry: () => undefined }
      : variant === "empty"
        ? { kind: "list", total: 0, items: [] }
        : { kind: "list", total: 57, items: ITEMS };

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-4 py-6">
      <h1 className="text-lg font-semibold">Podgląd: zgłoszenia przeglądane przez AI</h1>
      <div className="grid gap-6 md:grid-cols-2">
        <section aria-label="Kolumna Nowi" className="rounded-lg border border-border bg-background">
          <div className="border-b border-border px-3 py-2 text-sm font-semibold">Nowi</div>
          <div className="space-y-1.5 p-2">
            <ScreenedOutList
              key={variant ?? "open"}
              state={state}
              readOnly={false}
              addingId={addingId}
              defaultOpen={variant !== "closed"}
              onAdd={(item) => setAddingId(item.id)}
            />
            {variant === "empty" ? (
              <p className="px-1 text-xs text-muted-foreground">
                Nikogo nie odrzucono — sekcji nie ma.
              </p>
            ) : null}
          </div>
        </section>
        <section aria-label="Plakietki kart" className="space-y-2">
          <h2 className="text-sm font-semibold">Karty zgłoszeń z ogłoszenia w „Nowi”</h2>
          {BADGE_CASES.map(({ who, meta }) => {
            const badge = aiScreeningBadge(meta);
            return (
              <div key={who} className="rounded-lg border border-border bg-card px-3 py-2 text-sm">
                <div className="font-medium">{who}</div>
                {badge ? (
                  <span
                    title={badge.title}
                    className={`mt-1 inline-block rounded px-1.5 text-[11px] font-semibold ${CARD_BADGE_TONE_CLASS[badge.tone]}`}
                  >
                    {badge.label}
                  </span>
                ) : null}
              </div>
            );
          })}
        </section>
      </div>
    </main>
  );
}

export default function JobBoardScreeningPreviewPage() {
  return (
    <Suspense fallback={null}>
      <Harness />
    </Suspense>
  );
}
