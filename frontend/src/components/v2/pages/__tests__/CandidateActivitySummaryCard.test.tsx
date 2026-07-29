import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CandidateActivitySummaryCard } from "../CandidateActivitySummaryCard";
import { activitySummaryApi } from "@/lib/api";

const showSuccess = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api", () => ({
  activitySummaryApi: {
    get: vi.fn(),
    refresh: vi.fn(),
  },
  extractErrorMsg: () => "Błąd serwera",
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));

const mockedApi = vi.mocked(activitySummaryApi);

function renderCard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CandidateActivitySummaryCard candidateId={7} />
    </QueryClientProvider>,
  );
}

const summaryPayload = {
  candidate_id: 7,
  summary:
    "Kandydat był ostatnio wysyłany na projekt Senior Java Developer w Nordea.",
  model: "claude-sonnet-5",
  generated_at: "2026-07-29T10:00:00Z",
  refreshed: null,
};

describe("CandidateActivitySummaryCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the cached summary with the update button", async () => {
    mockedApi.get.mockResolvedValue({ data: summaryPayload } as never);

    renderCard();

    expect(
      await screen.findByText(/Senior Java Developer w Nordea/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Aktualizuj notatkę/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/claude-sonnet-5/)).toBeInTheDocument();
  });

  it("shows the empty state with a generate button when no summary exists", async () => {
    mockedApi.get.mockResolvedValue({
      data: { ...summaryPayload, summary: null, model: null, generated_at: null },
    } as never);

    renderCard();

    expect(
      await screen.findByRole("button", { name: /Wygeneruj podsumowanie/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Aktualizuj notatkę/ }),
    ).not.toBeInTheDocument();
  });

  it("refreshes the note and toasts success", async () => {
    mockedApi.get.mockResolvedValue({ data: summaryPayload } as never);
    mockedApi.refresh.mockResolvedValue({
      data: {
        ...summaryPayload,
        summary: "Zaktualizowana notatka o kandydacie.",
        refreshed: true,
      },
    } as never);

    renderCard();
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", { name: /Aktualizuj notatkę/ }),
    );

    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith("Podsumowanie zaktualizowane"),
    );
    expect(mockedApi.refresh).toHaveBeenCalledWith(7);
    expect(
      screen.getByText("Zaktualizowana notatka o kandydacie."),
    ).toBeInTheDocument();
  });

  it("toasts 'up to date' when the history did not change", async () => {
    mockedApi.get.mockResolvedValue({ data: summaryPayload } as never);
    mockedApi.refresh.mockResolvedValue({
      data: { ...summaryPayload, refreshed: false },
    } as never);

    renderCard();
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", { name: /Aktualizuj notatkę/ }),
    );

    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith(
        "Podsumowanie jest aktualne — brak nowych danych",
      ),
    );
  });

  it("toasts an error when the refresh fails", async () => {
    mockedApi.get.mockResolvedValue({
      data: { ...summaryPayload, summary: null },
    } as never);
    mockedApi.refresh.mockRejectedValue(new Error("boom"));

    renderCard();
    const user = userEvent.setup();

    await user.click(
      await screen.findByRole("button", { name: /Wygeneruj podsumowanie/ }),
    );

    await waitFor(() => expect(showError).toHaveBeenCalledWith("Błąd serwera"));
  });
});
