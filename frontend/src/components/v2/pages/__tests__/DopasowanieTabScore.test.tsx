import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();

vi.mock("@/lib/api", () => ({
  matchScoringApi: {
    get: (...args: unknown[]) => get(...args),
    feedback: vi.fn(),
  },
  extractErrorMsg: () => "",
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));

import { DopasowanieTab } from "@/components/v2/pages/DopasowanieTab";

const justification = {
  candidate_id: 3,
  job_id: 9,
  job_title: "Java",
  summary: "Mocne dopasowanie.",
  pros: [],
  watchouts: [],
  model: "m",
  rating: null,
  rating_comment: null,
  generated_at: null,
};

function renderTab() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <DopasowanieTab candidateId={3} recruitments={[{ job_id: 9, job_title: "Java" }]} />
    </QueryClientProvider>,
  );
}

describe("DopasowanieTab score ring", () => {
  beforeEach(() => get.mockReset());

  it("shows the canonical number it receives", async () => {
    get.mockResolvedValue({
      data: { ...justification, score: 64, score_measurement: "measured" },
    });
    renderTab();
    expect(await screen.findByLabelText("Dopasowanie 64 na 100")).toBeInTheDocument();
  });

  it("an unmeasured pair shows 'ocena niepełna', never a 0", async () => {
    get.mockResolvedValue({
      data: { ...justification, score: null, score_measurement: "missing_index" },
    });
    renderTab();
    expect(
      await screen.findByRole("img", {
        name: "Dopasowanie: ocena niepełna — kandydat nie ma jeszcze wektora w indeksie",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Dopasowanie 0 na 100/)).not.toBeInTheDocument();
    expect(screen.getByText("Mocne dopasowanie.")).toBeInTheDocument();
  });
});
