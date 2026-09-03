import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  forJob: vi.fn(),
  addCandidate: vi.fn(),
  showToast: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  requestHistoryApi: {
    forJob: (...args: unknown[]) => mocks.forJob(...args),
    addCandidate: (...args: unknown[]) => mocks.addCandidate(...args),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast }),
}));

vi.mock("@/components/AppShell", () => ({
  AddJobModal: () => <div role="dialog">Kopiowanie requestu</div>,
}));

import { RequestHistorySection } from "@/components/RequestHistorySection";

const RESPONSE = {
  closed: [
    {
      job_id: 12,
      title: "Senior Java Developer",
      status: "closed",
      is_in_progress: false,
      similarity: 0.95,
      similarity_source: "sql_same_client",
      champion_candidate_id: 42,
      champion_name: "Anna Nowak",
      champions_count: 1,
      candidates_count: 3,
      train_name: null,
      same_train: false,
      seniority: "senior",
      outcome: "filled",
      close_reason: null,
      tth_days: 20,
      fee_rate: null,
      fee_currency: null,
      rate_unit: null,
      tac_name: null,
      delivery_lead_name: null,
      closed_at: "2026-08-01T00:00:00Z",
    },
  ],
  in_progress: [],
};

function renderSection(readOnly: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RequestHistorySection jobId={7} clientId={3} readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

describe("RequestHistorySection read-only", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.forJob.mockResolvedValue({ data: RESPONSE });
    mocks.addCandidate.mockResolvedValue({ data: {} });
  });

  it("zachowuje historię i odczytowe filtry, ale ukrywa kopiowanie i dodanie championa", async () => {
    renderSection(true);

    expect(await screen.findByText("Senior Java Developer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Otwórz" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Skopiuj jako template" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Dodaj championa" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("request-history-cross-client"));
    await waitFor(() => expect(mocks.forJob).toHaveBeenCalledTimes(2));
    expect(mocks.addCandidate).not.toHaveBeenCalled();
  });

  it("pozostawia akcje dla użytkownika z zapisem", async () => {
    renderSection(false);

    expect(
      await screen.findByRole("button", { name: "Skopiuj jako template" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj championa" }));

    await waitFor(() =>
      expect(mocks.addCandidate).toHaveBeenCalledWith(7, {
        candidate_id: 42,
        source_job_id: 12,
      }),
    );
  });
});
