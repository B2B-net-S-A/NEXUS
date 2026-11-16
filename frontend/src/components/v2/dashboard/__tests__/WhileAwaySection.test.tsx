import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WhileAwaySummary } from "@/lib/api/whileAway";

const state: { query: Record<string, unknown> } = { query: {} };
const markHandled = vi.fn(async (_id: number) => undefined);
const dismiss = vi.fn(async () => undefined);

vi.mock("@/lib/api/whileAway", () => ({
  WHILE_AWAY_QUERY_KEY: ["notifications", "while-away"],
  useWhileAway: () => state.query,
  markWhileAwayHandled: (id: number) => markHandled(id),
  dismissWhileAway: () => dismiss(),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showInfo: vi.fn(), showSuccess: vi.fn() }),
}));

import { WhileAwaySection, periodLabel } from "@/components/v2/dashboard/WhileAwaySection";

const SUMMARY: WhileAwaySummary = {
  since: "2026-11-10",
  until: "2026-11-13",
  substitute_names: ["Zastępca Testowy"],
  total: 5,
  actions: [
    {
      id: 11,
      title: "Rekrutacja zamknięta — daj znać 1 osobie",
      message: "Tester Manualny x5 · Klient A. Zamknięcie: Zastępca Testowy. Twoje osoby: Osoba A.",
      link: "/jobs/1",
      created_at: "2026-11-13T16:00:19Z",
      substitute_name: "Zastępca Testowy",
      seen_by_substitute: true,
      handled_at: null,
      handled_by_name: null,
    },
    {
      id: 12,
      title: "Rekrutacja zamknięta — daj znać 4 osobom",
      message: "Ops person · Klient B.",
      link: "/jobs/2",
      created_at: "2026-11-10T08:24:00Z",
      substitute_name: "Zastępca Testowy",
      seen_by_substitute: true,
      handled_at: "2026-11-16T09:00:00Z",
      handled_by_name: "Zastępca Testowy",
    },
  ],
  others: [
    { label: "Ruchy kandydatów", count: 2 },
    { label: "Nowe aplikacje", count: 1 },
  ],
};

function renderSection() {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <WhileAwaySection />
    </QueryClientProvider>,
  );
}

describe("WhileAwaySection", () => {
  beforeEach(() => {
    markHandled.mockClear();
    dismiss.mockClear();
  });

  it("nic nie rysuje, gdy z nieobecności nic nie zostało", () => {
    state.query = { isSuccess: true, isError: false, data: null };
    const { container } = renderSection();
    expect(container).toBeEmptyDOMElement();
  });

  it("awaria odczytu nie wygląda jak brak pracy z urlopu", () => {
    state.query = { isSuccess: false, isError: true, data: undefined };
    renderSection();
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać");
  });

  it("pokazuje zamknięcia, okres w kalendarzu firmy i resztę jako licznik", () => {
    state.query = { isSuccess: true, isError: false, data: SUMMARY };
    renderSection();
    expect(screen.getByText("Gdy Cię nie było · 10.11–13.11")).toBeInTheDocument();
    expect(screen.getByText("1 do załatwienia")).toBeInTheDocument();
    // 16:00 UTC = 17:00 w Warszawie (13.11 to jeszcze czas zimowy, UTC+1).
    expect(screen.getByText("13.11 17:00")).toBeInTheDocument();
    expect(screen.getByText("Załatwione · Zastępca Testowy")).toBeInTheDocument();
    expect(screen.getByText(/Pozostałe 3: Ruchy kandydatów 2, Nowe aplikacje 1/)).toBeInTheDocument();
  });

  it("„Załatwione” i „Zamknij podsumowanie” wołają API", async () => {
    state.query = { isSuccess: true, isError: false, data: SUMMARY };
    renderSection();
    fireEvent.click(screen.getByRole("button", { name: "Załatwione" }));
    await waitFor(() => expect(markHandled).toHaveBeenCalledWith(11));
    fireEvent.click(screen.getByRole("button", { name: "Zamknij podsumowanie" }));
    await waitFor(() => expect(dismiss).toHaveBeenCalledTimes(1));
  });

  it("jeden dzień nieobecności to jedna data", () => {
    expect(periodLabel({ since: "2026-11-13", until: "2026-11-13" })).toBe("13.11");
  });
});
