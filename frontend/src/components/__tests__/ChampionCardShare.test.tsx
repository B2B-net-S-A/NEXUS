import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const screeningMocks = vi.hoisted(() => ({
  getForStage: vi.fn(),
  createShareToken: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    screeningApi: {
      ...actual.screeningApi,
      getForStage: (...args: unknown[]) => screeningMocks.getForStage(...args),
      createShareToken: (...args: unknown[]) => screeningMocks.createShareToken(...args),
    },
  };
});

import { ChampionCard } from "@/components/ChampionCard";

function renderCard(employed: boolean) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ChampionCard
        stageId={5}
        employment={
          employed
            ? { state: "employed_at_client", client_name: "Klient Testowy" }
            : { state: "available" as never }
        }
      />
    </QueryClientProvider>,
  );
}

describe("ChampionCard — link share bez natywnego okna (R10-N15-8)", () => {
  let confirmSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    confirmSpy = vi.spyOn(window, "confirm");
    screeningMocks.getForStage.mockResolvedValue({
      data: {
        champion_profile: {
          screening_questions: [
            { id: "q1", question: "Pytanie?", ideal_answer: "", deal_breaker: "" },
          ],
        },
        screening_answers: {
          answers: [{ question_id: "q1", response: "Tak", deal_breaker_hit: false }],
          overall_fit: "fit",
          notes: "",
        },
      },
    });
    screeningMocks.createShareToken.mockResolvedValue({
      data: { share_url_suffix: "/share/champion/abc" },
    });
  });

  afterEach(() => {
    confirmSpy.mockRestore();
    vi.clearAllMocks();
  });

  it("u zatrudnionego pokazuje ostrzeżenie w karcie i tworzy link dopiero po potwierdzeniu", async () => {
    renderCard(true);
    fireEvent.click(await screen.findByTestId("share-champion-card"));

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(screeningMocks.createShareToken).not.toHaveBeenCalled();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Klient Testowy");

    fireEvent.click(within(alert).getByRole("button", { name: "Anuluj" }));
    expect(screeningMocks.createShareToken).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("share-champion-card"));
    fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Utwórz link" }));
    await waitFor(() => expect(screeningMocks.createShareToken).toHaveBeenCalledWith(5, 30));
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("bez zatrudnienia tworzy link od razu", async () => {
    renderCard(false);
    fireEvent.click(await screen.findByTestId("share-champion-card"));
    await waitFor(() => expect(screeningMocks.createShareToken).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
