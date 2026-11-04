/**
 * Raport „Propozycje AI” (30.09.2026): podsumowanie, powody, źródła,
 * rekrutacje; awaria nie udaje pustki, zmiana okna pyta o nowe dni.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import { ProposalOutcomesReport } from "@/components/insights/views/ProposalOutcomesReport";
import { decisionRate, type ProposalOutcomesResponse } from "@/lib/insights-proposals-api";

const counts = (proposed: number, added: number, dismissed: number, pending: number) => ({
  proposed,
  added,
  dismissed,
  pending,
  dismissed_by_reason: { too_expensive: dismissed > 0 ? 1 : 0, unknown: dismissed > 1 ? dismissed - 1 : 0 },
});

function body(over: Partial<ProposalOutcomesResponse> = {}): ProposalOutcomesResponse {
  return {
    days: 7,
    since: "2026-09-23T22:00:00+00:00",
    scope: "organization",
    reasons: [],
    totals: counts(10, 2, 3, 5),
    by_source: [{ source: "full_base", ...counts(8, 1, 2, 5) }, { source: "job_board", ...counts(3, 1, 1, 1) }],
    jobs: [{ job_id: 11, title: "Java Developer", ...counts(10, 2, 3, 5) }],
    ...over,
  };
}

const ENDPOINT = "/api/insights/proposals/outcomes";

function renderReport() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProposalOutcomesReport />
    </QueryClientProvider>,
  );
}

describe("ProposalOutcomesReport", () => {
  beforeEach(() => {
    // Blok, nie wyrażenie: funkcja zwrócona z `beforeEach` to hook sprzątający.
    mocks.get.mockReset();
  });

  it("pokazuje podsumowanie, powody, źródła i rekrutacje", async () => {
    mocks.get.mockResolvedValue({ data: body() });
    renderReport();
    expect(await screen.findByText("Czeka na decyzję")).toBeInTheDocument();
    expect(screen.getByText("Decyzję (dodanie albo pominięcie) ma 50% propozycji z ostatnich 7 dni.")).toBeInTheDocument();
    const reasons = within(screen.getByRole("region", { name: "Powody pominięcia" }));
    expect(reasons.getByText("Za drogi")).toBeInTheDocument();
    expect(reasons.getByText("Bez powodu (sprzed 30.09)")).toBeInTheDocument();
    expect(screen.getByText("Z portalu")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Java Developer" })).toHaveAttribute("href", "/jobs/11?tab=similar");
    expect(mocks.get).toHaveBeenCalledWith("/api/insights/proposals/outcomes", { params: { days: 7 } });
  });

  it("wygasłe propozycje (zamknięta rekrutacja) mają własną liczbę i kolumnę z wyjaśnieniem", async () => {
    mocks.get.mockResolvedValue({
      data: body({
        totals: { ...counts(10, 2, 3, 3), expired: 2 },
        by_source: [{ source: "full_base", ...counts(10, 2, 3, 3), expired: 2 }],
        jobs: [{ job_id: 11, title: "Java Developer", ...counts(10, 2, 3, 3), expired: 2 }],
      }),
    });
    renderReport();
    const summary = within(await screen.findByRole("region", { name: "Podsumowanie" }));
    expect(summary.getByText("Wygasło").nextElementSibling).toHaveTextContent("2");
    const headers = screen.getAllByRole("columnheader", { name: "Wygasłe" });
    expect(headers).toHaveLength(2);
    expect(headers[0]).toHaveAttribute(
      "title",
      "Rekrutacja zamknięta — propozycje bez decyzji wygasły",
    );
    const jobRow = screen.getByRole("link", { name: "Java Developer" }).closest("tr")!;
    expect(within(jobRow).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "Java Developer",
      "10",
      "2",
      "3",
      "3",
      "2",
    ]);
  });

  it("starszy serwer bez licznika wygasłych: kolumna pokazuje 0, bez kafla", async () => {
    mocks.get.mockResolvedValue({ data: body() });
    renderReport();
    const summary = within(await screen.findByRole("region", { name: "Podsumowanie" }));
    expect(summary.queryByText("Wygasło")).toBeNull();
    const jobRow = screen.getByRole("link", { name: "Java Developer" }).closest("tr")!;
    expect(within(jobRow).getAllByRole("cell").at(-1)).toHaveTextContent("0");
  });

  it("zmiana okna pyta o nowe dni", async () => {
    mocks.get.mockResolvedValue({ data: body() });
    renderReport();
    await screen.findByText("Czeka na decyzję");
    fireEvent.click(screen.getByRole("button", { name: "30 dni" }));
    await waitFor(() =>
      expect(mocks.get).toHaveBeenCalledWith("/api/insights/proposals/outcomes", { params: { days: 30 } }),
    );
  });

  it("awaria to błąd z ponowieniem, nie pusta lista", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url !== ENDPOINT) return Promise.reject(new Error(`Nieoczekiwany adres: ${url}`));
      return Promise.reject(Object.assign(new Error("HTTP 500"), { response: { status: 500 } }));
    });
    renderReport();
    expect((await screen.findAllByText(/Nie udało się pobrać/)).length).toBeGreaterThan(0);
    expect(screen.queryByText(/nie było nowych propozycji/)).not.toBeInTheDocument();
  });

  it("brak propozycji ma własne zdanie", async () => {
    mocks.get.mockResolvedValue({
      data: body({ scope: "delivery_lead", totals: counts(0, 0, 0, 0), by_source: [], jobs: [] }),
    });
    renderReport();
    expect(await screen.findByText(/nie było nowych propozycji w Twoich rekrutacjach/)).toBeInTheDocument();
  });

  it("procent decyzji: brak propozycji = null, nie 0%", () => {
    expect(decisionRate(counts(0, 0, 0, 0))).toBeNull();
    expect(decisionRate(counts(4, 1, 2, 1))).toBe(75);
  });
});
