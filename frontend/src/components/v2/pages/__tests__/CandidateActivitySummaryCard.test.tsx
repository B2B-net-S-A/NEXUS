import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CandidateActivitySummaryCard } from "../CandidateActivitySummaryCard";
import { activitySummaryApi } from "@/lib/api";

const showSuccess = vi.fn();
const showError = vi.fn();
const auth = vi.hoisted(() => ({
  user: {
    id: 101,
    role: "recruiter",
    roles: ["recruiter"],
  } as { id: number; role: string; roles: string[] },
}));

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

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (state: { user: typeof auth.user }) => unknown,
  ) => selector({ user: auth.user }),
}));

const mockedApi = vi.mocked(activitySummaryApi);

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function cardUi(queryClient: QueryClient, candidateId = 7) {
  return (
    <QueryClientProvider client={queryClient}>
      <CandidateActivitySummaryCard candidateId={candidateId} />
    </QueryClientProvider>
  );
}

function renderCard() {
  const queryClient = createQueryClient();
  return render(
    cardUi(queryClient),
  );
}

const summaryPayload = {
  candidate_id: 7,
  summary:
    "Kandydat był ostatnio wysyłany na projekt Senior Java Developer w Nordea.",
  model: "claude-sonnet-5",
  generated_at: "2026-07-29T10:00:00Z",
  source_version: "source-v1",
  current_source_version: "source-v1",
  is_stale: false,
  visibility_scope_hash: "abcdef1234567890",
  source_manifest: {
    content_policy_version: "candidate-summary-safe-v2",
    sources: [
      {
          name: "recruitments",
          included_items: 3,
          truncated_items: 0,
          redacted_financial_fragments: 0,
        redacted_instruction_fragments: 0,
      },
    ],
  },
  refreshed: null,
};

describe("CandidateActivitySummaryCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.user = {
      id: 101,
      role: "recruiter",
      roles: ["recruiter"],
    };
  });

  it("renders the cached summary with the update button", async () => {
    mockedApi.get.mockResolvedValue({ data: summaryPayload } as never);

    renderCard();

    expect(
      await screen.findByText(/Senior Java Developer w Nordea/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Aktualizuj$/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/claude-sonnet-5/)).toBeInTheDocument();
    expect(screen.getByText("Rekrutacje: 3")).toBeInTheDocument();
    expect(screen.getByText("Aktualne")).toBeInTheDocument();
    const generatedAt = screen.getByText(/^Wygenerowano /);
    expect(generatedAt).toHaveAttribute(
      "datetime",
      "2026-07-29T10:00:00Z",
    );
    expect(generatedAt.textContent).toMatch(/\d{1,2}:\d{2}/);
  });

  it("marks a redacted or truncated source manifest as partial", async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        ...summaryPayload,
        source_manifest: {
          ...summaryPayload.source_manifest,
          sources: [
            {
              ...summaryPayload.source_manifest.sources[0],
              truncated_items: 2,
            },
          ],
        },
      },
    } as never);

    renderCard();

    expect(await screen.findByText("Częściowe")).toBeInTheDocument();
    expect(screen.getByText(/Pominięto 2 elementów/i)).toBeInTheDocument();
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
      screen.queryByRole("button", { name: /^Aktualizuj$/ }),
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
      await screen.findByRole("button", { name: /^Aktualizuj$/ }),
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
      await screen.findByRole("button", { name: /^Aktualizuj$/ }),
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
    expect(await screen.findByRole("alert")).toHaveTextContent("Błąd serwera");
  });

  it("marks a cached summary as stale", async () => {
    mockedApi.get.mockResolvedValue({
      data: { ...summaryPayload, is_stale: true },
    } as never);

    renderCard();

    expect(await screen.findByText("Wymaga aktualizacji")).toBeInTheDocument();
  });

  it("fails closed when a summary still contains a financial amount", async () => {
    mockedApi.get.mockResolvedValue({
      data: {
        ...summaryPayload,
        summary: "Kandydat oczekuje 180 PLN/h i jest dostępny od zaraz.",
      },
    } as never);

    renderCard();

    expect(
      await screen.findByText(/nie przeszło kontroli bezpieczeństwa treści/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/180 PLN/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Wygeneruj bezpiecznie ponownie",
      }),
    ).toBeInTheDocument();
  });

  it.each([
    "Kandydat oczekuje €180 i jest dostępny od zaraz.",
    "Widełki stawki wynoszą 180–200.",
    "Budżet kandydata to 25k.",
  ])("fails closed for alternate amount notation: %s", async (summary) => {
    mockedApi.get.mockResolvedValue({
      data: { ...summaryPayload, summary },
    } as never);

    renderCard();

    expect(
      await screen.findByText(/nie przeszło kontroli bezpieczeństwa treści/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(summary)).not.toBeInTheDocument();
  });

  it("renders a distinct forbidden state", async () => {
    mockedApi.get.mockRejectedValue({ response: { status: 403 } });

    renderCard();

    expect(
      await screen.findByText(/Nie masz dostępu do podsumowania historii/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Wygeneruj podsumowanie/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps the refresh touch target at least 44px", async () => {
    mockedApi.get.mockResolvedValue({ data: summaryPayload } as never);

    renderCard();

    const refresh = await screen.findByRole("button", { name: "Aktualizuj" });
    expect(refresh.classList.contains("min-h-11")).toBe(true);
    expect(refresh.classList.contains("min-w-11")).toBe(true);
  });

  it("never renders the previous viewer's cached summary after a user switch", async () => {
    let resolveSecond:
      | ((value: { data: typeof summaryPayload }) => void)
      | undefined;
    const secondResponse = new Promise<{ data: typeof summaryPayload }>(
      (resolve) => {
        resolveSecond = resolve;
      },
    );
    mockedApi.get
      .mockResolvedValueOnce({
        data: {
          ...summaryPayload,
          summary: "Widoczne tylko dla pierwszego użytkownika.",
        },
      } as never)
      .mockReturnValueOnce(secondResponse as never);
    const queryClient = createQueryClient();
    const view = render(cardUi(queryClient));

    expect(
      await screen.findByText("Widoczne tylko dla pierwszego użytkownika."),
    ).toBeInTheDocument();

    auth.user = {
      id: 202,
      role: "sourcer",
      roles: ["sourcer"],
    };
    view.rerender(cardUi(queryClient));

    await waitFor(() => {
      expect(
        screen.queryByText("Widoczne tylko dla pierwszego użytkownika."),
      ).not.toBeInTheDocument();
    });
    expect(screen.getByText("Ładowanie podsumowania…")).toBeInTheDocument();

    resolveSecond?.({
      data: {
        ...summaryPayload,
        summary: "Podsumowanie drugiego użytkownika.",
        visibility_scope_hash: "scope-user-202",
      },
    });
    expect(
      await screen.findByText("Podsumowanie drugiego użytkownika."),
    ).toBeInTheDocument();
  });
});
