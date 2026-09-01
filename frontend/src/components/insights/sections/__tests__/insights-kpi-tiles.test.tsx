/**
 * Kafle podsumowania lejka + efektywność lejka (układ DynaReportera).
 *
 * Testy pilnują pięciu reguł, których złamanie jest DEFEKTEM, nie kwestią
 * gustu — każda z nich raz już wyszła na tej powierzchni:
 *
 * 1. **`null` ≠ `0`.** Brak liczby renderuje się jako „—”. Wielka „0" na
 *    kaflu podsumowania czyta się jak werdykt, a jest brakiem danych.
 * 2. **Procentów nie przycinamy do 100.** 120% znaczy, że licznik i mianownik
 *    pochodzą z różnych populacji — ma być widoczne, nie schowane.
 * 3. **Awaria ≠ pustka.** 403 i 500 renderują się jako awaria, nigdy jako
 *    „brak kamieni milowych" / „brak konwersji".
 * 4. **Etap nieodnotowywany jest OZNACZONY.** `mapped_from_traffit: false`
 *    przy zerze to brak ewidencji, nie obserwacja.
 * 5. **Ta sama metryka ma ten sam kolor.** Kafel „Weryfikacje" i konwersja
 *    „Weryfikacje → Rekomendacje" jadą z jednej mapy akcentów; rozjazd
 *    zrywa jedyny wizualny związek między liczbą a jej źródłem.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import {
  FUNNEL_STAGE_ACCENT,
  InsightsKpiTiles,
} from "@/components/insights/sections/InsightsKpiTiles";
import { RecruitmentConversions } from "@/components/insights/sections/RecruitmentConversions";
import type { InsightsPeriodParams } from "@/lib/insights-api";

const PERIOD: InsightsPeriodParams = { period: "month", offset: 0 };
const FUNNEL = "/api/insights/recruitment/funnel";

const WINDOW = {
  kind: "month" as const,
  start: "2026-08-01T00:00:00+02:00",
  end: "2026-09-01T00:00:00+02:00",
  timezone: "Europe/Warsaw",
};

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function respond(value: unknown) {
  mocks.get.mockImplementation((url: string) => {
    if (url !== FUNNEL) {
      return Promise.reject(new Error(`Nieoczekiwany URL w teście: ${url}`));
    }
    if (value instanceof Error) return Promise.reject(value);
    return Promise.resolve({ data: value });
  });
}

function renderSection(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

function stage(
  key: string,
  label: string,
  count: number,
  mapped = true,
  share: number | null = null,
) {
  return {
    stage: key,
    label,
    count,
    mapped_from_traffit: mapped,
    share_pct: share,
  };
}

const COVERAGE = {
  stage_moves_total: 0,
  stage_moves_manual: 0,
  manual_pct: null,
  unattributed_moves: 0,
  stages_not_mapped_from_traffit: [],
};

/** Cztery etapy KPI w kształcie, w jakim zwraca je backend. */
const STAGES = [
  stage("verified", "Zweryfikowany", 828),
  stage("cv_sent", "CV wysłane", 490),
  stage("interview", "Rozmowa", 100),
  stage("hired", "Zatrudniony", 21),
];

const CONVERSIONS = [
  {
    key: "verified_to_cv_sent",
    label: "Weryfikacje → Rekomendacje",
    numerator: 490,
    denominator: 828,
    pct: 59.2,
  },
  {
    key: "cv_sent_to_interview",
    label: "Rekomendacje → Rozmowy",
    numerator: 100,
    denominator: 490,
    pct: 20.4,
  },
  {
    key: "interview_to_hired",
    label: "Rozmowy → Zatrudnienia",
    numerator: 21,
    denominator: 100,
    pct: 21.0,
  },
  {
    key: "verified_to_hired",
    label: "Overall (Weryfikacja → Zatrudnienie)",
    numerator: 21,
    denominator: 828,
    pct: 2.5,
  },
];

function funnelPayload(overrides: Record<string, unknown> = {}) {
  return {
    period: WINDOW,
    stages: STAGES,
    conversions: CONVERSIONS,
    coverage: COVERAGE,
    ...overrides,
  };
}

/** Wartość kafla po jego nagłówku — kafle są nazwanymi grupami. */
function tile(headline: string) {
  return screen.getByRole("group", { name: headline });
}

beforeEach(() => {
  mocks.get.mockReset();
});

describe("InsightsKpiTiles", () => {
  it("renderuje cztery liczby DR i podpisuje je etapem z serwera", async () => {
    respond(funnelPayload());
    renderSection(<InsightsKpiTiles period={PERIOD} />);

    expect(await screen.findByText("828")).toBeInTheDocument();
    expect(within(tile("Weryfikacje")).getByText("828")).toBeInTheDocument();
    expect(within(tile("Rekomendacje")).getByText("490")).toBeInTheDocument();
    expect(within(tile("Interviews")).getByText("100")).toBeInTheDocument();
    expect(within(tile("Placements")).getByText("21")).toBeInTheDocument();

    // Podpis mówi, co ta liczba zlicza — nagłówek („Rekomendacje") jest
    // żargonem zespołu, a nie definicją.
    expect(
      within(tile("Rekomendacje")).getByText(/Pierwsze wejście na etap/),
    ).toHaveTextContent("CV wysłane");
  });

  it("etap nieodnotowywany pokazuje „—” i gwiazdkę, nigdy twarde zero", async () => {
    respond(
      funnelPayload({
        stages: [
          STAGES[0],
          STAGES[1],
          STAGES[2],
          // Zero przy etapie, którego import z Traffita nie zna, to brak
          // ewidencji — nie „nikogo nie zatrudniliśmy".
          stage("hired", "Zatrudniony", 0, false),
        ],
      }),
    );
    renderSection(<InsightsKpiTiles period={PERIOD} />);

    const placements = await screen.findByRole("group", {
      name: /Placements/,
    });
    expect(within(placements).getByText("—")).toBeInTheDocument();
    expect(within(placements).queryByText("0")).not.toBeInTheDocument();
    expect(
      within(placements).getByText(/Nie odnotowujemy tego etapu/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/import z\s+Traffita go nie przenosi/),
    ).toBeInTheDocument();
  });

  it("etap, którego serwer nie zwrócił, to „—”, a nie podstawione zero", async () => {
    respond(
      funnelPayload({ stages: STAGES.filter((s) => s.stage !== "interview") }),
    );
    renderSection(<InsightsKpiTiles period={PERIOD} />);

    const interviews = await screen.findByRole("group", { name: "Interviews" });
    expect(within(interviews).getByText("—")).toBeInTheDocument();
    expect(within(interviews).queryByText("0")).not.toBeInTheDocument();
    expect(
      within(interviews).getByText(/Serwer nie zwrócił tego etapu/),
    ).toBeInTheDocument();
  });

  it("500 renderuje awarię, nie „brak kamieni milowych”", async () => {
    respond(httpError(500));
    renderSection(<InsightsKpiTiles period={PERIOD} />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByText(/Nie udało się pobrać danych sekcji/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Brak kamieni milowych/)).not.toBeInTheDocument();
  });

  it("403 mówi o uprawnieniach i nie sugeruje, że danych nie ma", async () => {
    respond(httpError(403));
    renderSection(<InsightsKpiTiles period={PERIOD} />);

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.getByText(/Dane NIE są puste/)).toBeInTheDocument();
    expect(screen.queryByText(/Brak kamieni milowych/)).not.toBeInTheDocument();
  });

  it("sukces z pustą listą etapów to pusty stan, a nie cztery myślniki", async () => {
    respond(funnelPayload({ stages: [] }));
    renderSection(<InsightsKpiTiles period={PERIOD} />);

    expect(
      await screen.findByText(/Brak kamieni milowych/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Placements" })).toBeNull();
  });
});

describe("RecruitmentConversions", () => {
  it("renderuje cztery konwersje z mianownikiem pod procentem", async () => {
    respond(funnelPayload());
    renderSection(<RecruitmentConversions period={PERIOD} />);

    expect(await screen.findByText("59.2%")).toBeInTheDocument();
    const row = screen.getByRole("group", {
      name: "Weryfikacje → Rekomendacje",
    });
    expect(within(row).getByText("490 z 828")).toBeInTheDocument();
    expect(screen.getByText("2.5%")).toBeInTheDocument();
  });

  it("zerowy mianownik to „—”, nigdy „0%”", async () => {
    respond(
      funnelPayload({
        conversions: [
          {
            key: "verified_to_cv_sent",
            label: "Weryfikacje → Rekomendacje",
            numerator: 0,
            denominator: 0,
            pct: null,
          },
        ],
      }),
    );
    renderSection(<RecruitmentConversions period={PERIOD} />);

    const row = await screen.findByRole("group", {
      name: "Weryfikacje → Rekomendacje",
    });
    expect(within(row).getByText("—")).toBeInTheDocument();
    expect(within(row).queryByText("0.0%")).not.toBeInTheDocument();
    expect(within(row).queryByText("0%")).not.toBeInTheDocument();
    expect(
      within(row).getByText("Brak mianownika w tym oknie"),
    ).toBeInTheDocument();
  });

  it("nie przycina wyniku powyżej 100%", async () => {
    respond(
      funnelPayload({
        conversions: [
          {
            key: "interview_to_hired",
            label: "Rozmowy → Zatrudnienia",
            numerator: 12,
            denominator: 10,
            pct: 120.5,
          },
        ],
      }),
    );
    renderSection(<RecruitmentConversions period={PERIOD} />);

    expect(await screen.findByText("120.5%")).toBeInTheDocument();
    expect(screen.queryByText("100.0%")).not.toBeInTheDocument();
    expect(screen.queryByText("100%")).not.toBeInTheDocument();
  });

  it("konwersja świeci kolorem etapu, od którego się zaczyna", async () => {
    respond(funnelPayload());
    renderSection(<RecruitmentConversions period={PERIOD} />);

    const fromVerified = await screen.findByRole("group", {
      name: "Weryfikacje → Rekomendacje",
    });
    // Ten sam akcent, którym kafel „Weryfikacje" jest podpisany wyżej —
    // asercja idzie po eksportowanej mapie, żeby duplikat literału nie
    // przeszedł niezauważony przy zmianie palety.
    expect(fromVerified.className).toContain(
      FUNNEL_STAGE_ACCENT.verified.border,
    );

    const fromCvSent = screen.getByRole("group", {
      name: "Rekomendacje → Rozmowy",
    });
    expect(fromCvSent.className).toContain(FUNNEL_STAGE_ACCENT.cv_sent.border);
  });

  it("500 renderuje awarię, nie „brak konwersji”", async () => {
    respond(httpError(500));
    renderSection(<RecruitmentConversions period={PERIOD} />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/Brak konwersji/)).not.toBeInTheDocument();
  });

  it("sukces z zerem konwersji ma własny pusty stan", async () => {
    respond(funnelPayload({ conversions: [] }));
    renderSection(<RecruitmentConversions period={PERIOD} />);

    expect(
      await screen.findByText(/Brak konwersji do policzenia/),
    ).toBeInTheDocument();
  });
});
