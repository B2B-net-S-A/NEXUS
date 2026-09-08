/**
 * Klaster KPI jobbara (`lib/job-header-kpis.ts`).
 *
 * Testy na WARTOŚCIACH, nie na zrzucie ekranu: mapa „krok → trzy liczby" jest
 * całą treścią tego modułu, a jej regresje (zero zamiast „nie wiem", licznik
 * liczony z innego zbioru niż nazwa obiecuje) są niewidoczne w renderze.
 */

import { describe, expect, it } from "vitest";

import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import {
  STRONG_MATCH_SCORE,
  buildJobHeaderKpis,
  summarizeRanking,
} from "@/lib/job-header-kpis";

function item(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return { id: 1, candidate_id: 1, stage: "new", ...overrides };
}

function column(overrides: Partial<KanbanColumn> = {}): KanbanColumn {
  const items = overrides.items ?? [];
  return {
    stage: "new",
    category: "internal",
    count: items.length,
    ...overrides,
    items,
  };
}

/** Plansza z jedną osobą na każdym istotnym etapie. */
function board(): KanbanColumn[] {
  return [
    column({ stage: "new", items: [item(), item({ id: 2, days_in_stage: 9 })] }),
    column({ stage: "screening", items: [item({ id: 3 })] }),
    column({
      stage: "verified",
      items: [item({ id: 4, verification_status: "pending" })],
    }),
    column({
      stage: "cv_sent",
      category: "external",
      items: [item({ id: 5, stage: "cv_sent" })],
    }),
    column({
      stage: "acceptance",
      category: "external",
      items: [
        item({
          id: 6,
          stage: "acceptance",
          hm_veto: {
            hiring_manager_contact_id: 1,
            source_job_id: 2,
            rejected_at: "2026-09-01",
            rejection_reason_name: "Brak doświadczenia",
          },
        }),
      ],
    }),
    column({ stage: "new", name: "Umowa wysłana", items: [item({ id: 7 })] }),
    column({
      stage: "hired",
      category: "terminal",
      terminal_type: "hired",
      items: [item({ id: 8, stage: "hired" })],
    }),
    column({
      stage: "rejected",
      category: "terminal",
      terminal_type: "rejected",
      items: [item({ id: 9, stage: "rejected", days_in_stage: 90 })],
    }),
  ];
}

describe("summarizeRanking", () => {
  it("bez danych zwraca null, a nie zero — to inna wiadomość", () => {
    expect(summarizeRanking(undefined)).toBeNull();
    expect(summarizeRanking(null)).toBeNull();
    expect(summarizeRanking([])).toEqual({ total: 0, strong: 0 });
  });

  it("kandydat bez policzonego wyniku jest w rankingu, ale nie jest trafieniem", () => {
    const summary = summarizeRanking([
      { match_score: STRONG_MATCH_SCORE },
      { match_score: STRONG_MATCH_SCORE - 1 },
      { match_score: null },
      {},
    ]);
    expect(summary).toEqual({ total: 4, strong: 1 });
  });
});

describe("buildJobHeaderKpis — „nie wiem” to nie zero", () => {
  it("bez kanbana i bez rankingu wszystkie trzy liczby są nullem", () => {
    for (const tab of ["pipeline", "screening", "cv", "interviews", "contract", "champion"] as const) {
      const kpis = buildJobHeaderKpis({ tab, columns: null, ranking: null });
      expect(kpis).toHaveLength(3);
      expect(kpis.map((k) => k.value)).toEqual([null, null, null]);
    }
  });

  it("zawsze zwraca dokładnie trzy pozycje — klaster ma stałą szerokość", () => {
    const kpis = buildJobHeaderKpis({
      tab: "pipeline",
      columns: board(),
      ranking: null,
    });
    expect(kpis).toHaveLength(3);
  });
});

describe("buildJobHeaderKpis — kroki", () => {
  it("Pipeline: w procesie · utknęli > 7 d (warn) · u klienta", () => {
    const kpis = buildJobHeaderKpis({
      tab: "pipeline",
      columns: board(),
      ranking: null,
    });
    // 2 nowych + 1 screening + 1 verified + 1 cv_sent + 1 acceptance + 1 umowa
    // = 7; kolumny terminalne (hired, rejected) są poza „w procesie".
    expect(kpis[0]).toMatchObject({ label: "w procesie", value: 7 });
    // Odrzucony stoi na etapie 90 dni i CELOWO się nie liczy — to nie jest
    // sprawa do załatwienia.
    expect(kpis[1]).toMatchObject({
      label: "utknęli > 7 d",
      value: 1,
      tone: "warn",
    });
    expect(kpis[2]).toMatchObject({ label: "u klienta", value: 2 });
  });

  it("Pipeline: zero „utknęli” zostaje neutralne, nie ostrzegawcze", () => {
    const kpis = buildJobHeaderKpis({
      tab: "pipeline",
      columns: [column({ stage: "new", items: [item()] })],
      ranking: null,
    });
    expect(kpis[1]).toMatchObject({ value: 0, tone: "neutral" });
  });

  it("Screening: w screeningu · czeka na akceptację (warn) · zweryfikowani", () => {
    const kpis = buildJobHeaderKpis({
      tab: "screening",
      columns: board(),
      ranking: null,
    });
    expect(kpis[0]).toMatchObject({ label: "w screeningu", value: 1 });
    expect(kpis[1]).toMatchObject({
      label: "czeka na akceptację",
      value: 1,
      tone: "warn",
    });
    expect(kpis[2]).toMatchObject({ label: "zweryfikowani", value: 1 });
  });

  it("Rozmowy: weto HM jest tonem złym, gdy jakiekolwiek jest", () => {
    const kpis = buildJobHeaderKpis({
      tab: "interviews",
      columns: board(),
      ranking: null,
    });
    expect(kpis[0]).toMatchObject({ label: "u klienta", value: 2 });
    expect(kpis[1]).toMatchObject({ label: "akceptacja", value: 1, tone: "ok" });
    expect(kpis[2]).toMatchObject({ label: "weto HM", value: 1, tone: "bad" });
  });

  it("Umowa: wysłana · zatrudnieni · na etapach umowy", () => {
    const kpis = buildJobHeaderKpis({
      tab: "contract",
      columns: board(),
      ranking: null,
    });
    expect(kpis[0]).toMatchObject({ label: "umowa wysłana", value: 1 });
    expect(kpis[1]).toMatchObject({ label: "zatrudnieni", value: 1, tone: "ok" });
    // „Umowa wysłana" + terminal `hired` = 2.
    expect(kpis[2]).toMatchObject({ label: "na etapach umowy", value: 2 });
  });

  it("kroki pozyskiwania czytają ranking, a Pozyskiwanie i Champion mają ten sam zestaw", () => {
    const ranking = { total: 98, strong: 7 };
    const champion = buildJobHeaderKpis({
      tab: "champion",
      columns: board(),
      ranking,
    });
    const sourcing = buildJobHeaderKpis({
      tab: "ai-matching",
      columns: board(),
      ranking,
    });
    expect(champion).toEqual(sourcing);
    expect(champion[0]).toMatchObject({ label: "w rankingu", value: 98 });
    expect(champion[1]).toMatchObject({ label: "≥ 75 pkt", value: 7 });
    expect(champion[2]).toMatchObject({ label: "w procesie", value: 7 });
  });

  it("CV: „do wysłania” i „CV u klienta” to rozłączne zbiory", () => {
    const kpis = buildJobHeaderKpis({
      tab: "cv",
      columns: board(),
      ranking: null,
    });
    expect(kpis[0]).toMatchObject({ label: "do wysłania", value: 1 });
    expect(kpis[1]).toMatchObject({ label: "CV u klienta", value: 1 });
    expect(kpis[2]).toMatchObject({ label: "u klienta", value: 2 });
  });
});
