/**
 * „Jakość prepów” (0370) — raport HoR z prepów w Teams.
 *
 * Pilnowane reguły:
 * 1. Tabela per prowadzący + linia „Rozmowy u klienta z dwoma prepami: X z Y”.
 * 2. Brak nagrań = „—”, nigdy „0%”.
 * 3. Pusta lista ma własny komunikat, awaria (403/500) nie udaje pustki.
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

import { PrepQualitySection } from "@/components/insights/chapters/PrepQualitySection";
import { formatTalkShare, type PrepQualityResponse } from "@/lib/api/prepQuality";

const ENDPOINT = "/api/interview-cycle/prep-quality";

function body(overrides: Partial<PrepQualityResponse> = {}): PrepQualityResponse {
  return {
    days: 90,
    rows: [
      {
        organizer: { id: 7, name: "Marta DL" },
        preps: 12,
        recorded: 10,
        unrecorded: 2,
        good: 6,
        ok: 3,
        weak: 1,
        avg_talk_share: 0.456,
      },
      {
        organizer: { id: 8, name: "Jan Rekruter" },
        preps: 3,
        recorded: 0,
        unrecorded: 3,
        good: 0,
        ok: 0,
        weak: 0,
        avg_talk_share: null,
      },
    ],
    interviews: 9,
    interviews_with_two_preps: 4,
    ...overrides,
  };
}

function respond(value: unknown) {
  mocks.get.mockImplementation((url: string) => {
    if (url !== ENDPOINT) return Promise.reject(new Error(`Nieoczekiwany adres: ${url}`));
    if (value instanceof Error) return Promise.reject(value);
    return Promise.resolve({ data: value });
  });
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PrepQualitySection />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
});

describe("formatTalkShare", () => {
  it("brak nagrań to „—”, nie 0%", () => {
    expect(formatTalkShare(null)).toBe("—");
    expect(formatTalkShare(0)).toBe("0%");
    expect(formatTalkShare(0.456)).toBe("46%");
  });
});

describe("PrepQualitySection", () => {
  it("rysuje tabelę per prowadzący i linię o dwóch prepach", async () => {
    respond(body());
    renderSection();

    const marta = await screen.findByTestId("prep-quality-row-7");
    const cells = within(marta).getAllByRole("cell");
    expect(cells[0]).toHaveTextContent("Marta DL");
    expect(cells[1]).toHaveTextContent("12");
    expect(cells[2]).toHaveTextContent("10");
    expect(cells[3]).toHaveTextContent("2");
    expect(cells[4]).toHaveTextContent("6 / 3 / 1");
    expect(cells[5]).toHaveTextContent("46%");

    const jan = screen.getByTestId("prep-quality-row-8");
    expect(within(jan).getAllByRole("cell")[5]).toHaveTextContent("—");

    expect(screen.getByText(/Rozmowy u klienta z dwoma prepami/)).toHaveTextContent("4 z 9");
    expect(mocks.get).toHaveBeenCalledWith(ENDPOINT, { params: { days: 90 } });
  });

  it("pusta lista ma własny komunikat", async () => {
    respond(body({ rows: [], interviews: 5, interviews_with_two_preps: 0 }));
    renderSection();

    expect(
      await screen.findByText("W tym okresie nie było prepów założonych z NEXUSA."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Rozmowy u klienta z dwoma prepami/)).toHaveTextContent("0 z 5");
  });

  it("403 to brak uprawnień, a nie pusta sekcja", async () => {
    respond(Object.assign(new Error("HTTP 403"), { response: { status: 403 } }));
    renderSection();

    expect(await screen.findByText(/nie ma dostępu/)).toBeInTheDocument();
    expect(screen.queryByText(/nie było prepów/)).not.toBeInTheDocument();
  });

  it("500 to awaria, a nie pusta sekcja", async () => {
    respond(Object.assign(new Error("HTTP 500"), { response: { status: 500 } }));
    renderSection();

    expect((await screen.findAllByText(/Nie udało się pobrać/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/nie było prepów/)).not.toBeInTheDocument();
  });
});
