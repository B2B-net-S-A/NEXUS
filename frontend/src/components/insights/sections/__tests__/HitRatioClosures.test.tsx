/**
 * „Zamknięcia i hit ratio” (21.10.2026): lista kontrolna wyłączeń z hit ratio
 * i zamknięć do przeglądu, „Zmień powód” z tego samego okna co rekrutacja.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ closures: vi.fn() }));

vi.mock("@/lib/insights-api", async (orig) => ({
  ...(await orig<typeof import("@/lib/insights-api")>()),
  insightsBoardApi: { hitRatioClosures: () => mocks.closures() },
}));
vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn() },
  extractErrorMsg: () => "Błąd",
  jobsApi: { changeCloseReason: vi.fn(), close: vi.fn(), list: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { HitRatioClosures } from "@/components/insights/sections/HitRatioClosures";

const ROW = {
  title: "Analityk",
  client_name: "Klient A",
  duplicate_of_job_id: null,
  closed_at: "2026-10-20T10:00:00+00:00",
  closed_by_name: "DL Przykładowy",
  delivery_lead_name: null,
};

function renderReport() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <HitRatioClosures />
    </QueryClientProvider>,
  );
}

describe("HitRatioClosures", () => {
  beforeEach(() => vi.clearAllMocks());

  it("pokazuje grupy, wyłączenia z uzasadnieniem i zamknięcia do przeglądu", async () => {
    mocks.closures.mockResolvedValue({
      since: "2026-10-11T22:00:00+00:00",
      counts: { won: 10, lost: 25, neutral: 1, unreviewed: 18 },
      hit_ratio: 18.9,
      neutral: [{ ...ROW, job_id: 1, close_reason: "duplicate", close_notes: "Ten sam request" }],
      unreviewed: [{ ...ROW, job_id: 2, close_reason: "other", close_notes: null }],
    });
    renderReport();
    expect(await screen.findByText("18,9%")).toBeInTheDocument();
    expect(screen.getByText("43")).toBeInTheDocument();
    expect(screen.getByText("w tym 18 do przejrzenia")).toBeInTheDocument();
    const neutral = screen.getByTestId("closures-neutral");
    expect(within(neutral).getByText("Duplikat albo założona przez pomyłkę")).toBeInTheDocument();
    expect(within(neutral).getByText("Ten sam request")).toBeInTheDocument();
    const unreviewed = screen.getByTestId("closures-unreviewed");
    expect(within(unreviewed).getByText("Inny (do przejrzenia)")).toBeInTheDocument();

    fireEvent.click(within(unreviewed).getByRole("button", { name: "Zmień powód" }));
    expect(await screen.findByRole("heading", { name: "Zmień powód zamknięcia" })).toBeInTheDocument();
  });

  it("awaria nie udaje pustej listy", async () => {
    mocks.closures.mockRejectedValue(Object.assign(new Error("HTTP 500"), { response: { status: 500 } }));
    renderReport();
    expect(await screen.findByText(/Zamknięcia i hit ratio/)).toBeInTheDocument();
    expect(screen.queryByText("Nic nie czeka na przegląd.")).not.toBeInTheDocument();
  });
});
