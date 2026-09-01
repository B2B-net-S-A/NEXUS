/**
 * Baner kampanii rekrutacyjnej (`/api/insights/campaigns/active`).
 *
 * Cztery reguły, których złamanie jest DEFEKTEM, nie kwestią gustu:
 *
 * 1. Brak kampanii → NIC. Ramka z „0 / 0" twierdziłaby, że kampania trwa
 *    i idzie fatalnie.
 * 2. Awaria ≠ pustka. Zniknięcie banera przy 500 czyta się jak „odwołali
 *    kampanię".
 * 3. `progress_pct` nie jest przycinane do 100 — przycięta jest wyłącznie
 *    SZEROKOŚĆ paska, bo tor ma stałą długość.
 * 4. `null` to „—", nigdy „0%": cel równy zeru nie daje procentu.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import { InsightsCampaignBanner } from "@/components/insights/sections/InsightsCampaignBanner";
import type { InsightsCampaign } from "@/lib/insights-campaign-api";

const ACTIVE_URL = "/api/insights/campaigns/active";

/** Kampania 1:1 z banerem DynaReportera: 49 placementów, 19 rezygnacji. */
const CAMPAIGN: InsightsCampaign = {
  id: 1,
  name: "Wakacyjna integracja, polećmy razem do ciepłych krajów!",
  emoji: "🏖️",
  start_date: "2026-07-01",
  end_date: "2026-09-30",
  target_net: 60,
  is_active: true,
  created_at: "2026-06-20T09:00:00+02:00",
  window: {
    kind: "custom",
    start: "2026-07-01T00:00:00+02:00",
    end: "2026-10-01T00:00:00+02:00",
    timezone: "Europe/Warsaw",
  },
  days_remaining: 30,
  has_started: true,
  placements: 49,
  resignations: 19,
  net: 30,
  progress_pct: 50.0,
  remaining_to_target: 30,
  placements_definition: "first_hired_per_candidate_job",
  placements_definition_note:
    "Placement = PIERWSZE wejście na etap „Zatrudniony” dla pary (kandydat, rekrutacja).",
  resignations_definition: "ended_engagement_by_effective_end_date",
  resignations_definition_note:
    "Rezygnacja = kontrakt, którego dzień faktycznego zakończenia wypada w oknie kampanii.",
  net_definition_note: "netto = placementy − rezygnacje",
};

function respond(value: unknown) {
  mocks.get.mockImplementation((url: string) => {
    if (url !== ACTIVE_URL) {
      return Promise.reject(new Error(`Nieoczekiwany URL w teście: ${url}`));
    }
    if (value instanceof Error) return Promise.reject(value);
    return Promise.resolve({ data: value });
  });
}

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderBanner() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <InsightsCampaignBanner />
    </QueryClientProvider>,
  );
}

describe("InsightsCampaignBanner", () => {
  beforeEach(() => {
    mocks.get.mockReset();
  });

  it("renderuje liczby kampanii tak, jak robił to DynaReporter", async () => {
    respond(CAMPAIGN);
    renderBanner();

    expect(await screen.findByText(/Wakacyjna integracja/)).toBeInTheDocument();
    expect(screen.getByText("30 / 60")).toBeInTheDocument();
    expect(screen.getByText("49")).toBeInTheDocument();
    expect(screen.getByText("19")).toBeInTheDocument();
    expect(screen.getByText(/Zostało 30 do celu/)).toBeInTheDocument();
    expect(screen.getByText("30 dni")).toBeInTheDocument();
    expect(
      screen.getByText("netto = placementy − rezygnacje"),
    ).toBeInTheDocument();
  });

  it("nie renderuje NICZEGO, gdy nie ma aktywnej kampanii", async () => {
    respond(null);
    const { container } = renderBanner();

    // Poczekaj aż zapytanie się rozstrzygnie, żeby test nie zdał na samym
    // stanie ładowania (który też nic nie renderuje).
    await vi.waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await vi.waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("awarię renderuje jako błąd sekcji, nie jako brak kampanii", async () => {
    respond(httpError(500));
    renderBanner();

    expect(
      await screen.findByText(/Kampania rekrutacyjna/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("brak uprawnień też jest komunikatem, nie pustką", async () => {
    respond(httpError(403));
    renderBanner();

    expect(
      await screen.findByText(/Kampania rekrutacyjna/),
    ).toBeInTheDocument();
  });

  it("nie przycina procentu do 100, ale przycina szerokość paska", async () => {
    respond({
      ...CAMPAIGN,
      placements: 40,
      resignations: 4,
      net: 36,
      target_net: 24,
      progress_pct: 150,
      remaining_to_target: -12,
    });
    const { container } = renderBanner();

    expect(await screen.findByText(/150%/)).toBeInTheDocument();
    expect(screen.getByText(/Cel przekroczony o 12/)).toBeInTheDocument();

    const fill = container.querySelector(
      '[role="progressbar"] > div',
    ) as HTMLElement | null;
    expect(fill).not.toBeNull();
    // Tor ma stałą długość — 150% szerokości nie istnieje w CSS. Liczba obok
    // niesie prawdę, pasek tylko ją ilustruje.
    expect(fill?.style.width).toBe("100%");
  });

  it("cel równy zeru daje myślnik, nie zero procent", async () => {
    respond({
      ...CAMPAIGN,
      target_net: 0,
      net: 5,
      progress_pct: null,
      remaining_to_target: -5,
    });
    const { container } = renderBanner();

    // `aria-valuetext` jest jednoznaczne: „—" znaczy „nie policzone".
    expect(await screen.findByText(/—/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuetext",
      "5 z 0 (—)",
    );
    expect(container.textContent).not.toMatch(/\d+%/);

    const fill = container.querySelector(
      '[role="progressbar"] > div',
    ) as HTMLElement | null;
    expect(fill?.style.width).toBe("0%");
  });

  it("wypisuje definicje liczników przysłane przez serwer", async () => {
    respond(CAMPAIGN);
    renderBanner();

    expect(
      await screen.findByText(new RegExp("PIERWSZE wejście na etap")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/dzień faktycznego zakończenia/),
    ).toBeInTheDocument();
  });
});
