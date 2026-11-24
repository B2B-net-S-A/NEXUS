import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScorecardV2 } from "./ScorecardV2";

const mocks = vi.hoisted(() => ({
  getScorecardSchema: vi.fn(),
  submitAnswers: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  phase3Api: {
    getScorecardSchema: mocks.getScorecardSchema,
    submitAnswers: mocks.submitAnswers,
  },
}));

function renderScorecard(onOpenChange = vi.fn(), onSaved = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ScorecardV2
        open
        onOpenChange={onOpenChange}
        candidateStageId={11}
        stageId={22}
        stageDefId={33}
        stageName="Rozmowa techniczna"
        onSaved={onSaved}
      />
    </QueryClientProvider>,
  );
  return { onOpenChange, onSaved };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.getScorecardSchema.mockResolvedValue({
    data: {
      stage_def_id: 33,
      stage_name: "Rozmowa techniczna",
      schema: {
        questions: [{ id: "q1", label: "Wrażenia z rozmowy", type: "text" }],
      },
    },
  });
});

describe("ScorecardV2 — nieudany zapis", () => {
  it("odmowa serwera pokazuje komunikat, okno i wpisane odpowiedzi zostają", async () => {
    mocks.submitAnswers.mockRejectedValue({
      response: { status: 409, data: { detail: "Etap kandydata został już zamknięty." } },
    });
    const user = userEvent.setup();
    const { onOpenChange, onSaved } = renderScorecard();

    const answer = await screen.findByPlaceholderText("Wpisz ocenę…");
    await user.type(answer, "Dobra komunikacja");
    await user.click(screen.getByRole("button", { name: /Zapisz scorecard/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Etap kandydata został już zamknięty.",
    );
    expect(mocks.submitAnswers).toHaveBeenCalledTimes(1);
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByPlaceholderText("Wpisz ocenę…")).toHaveValue("Dobra komunikacja");
  });

  it("błąd bez treści z serwera daje zdanie po polsku", async () => {
    mocks.submitAnswers.mockRejectedValue(new Error("Network Error"));
    const user = userEvent.setup();
    renderScorecard();

    await screen.findByPlaceholderText("Wpisz ocenę…");
    await user.click(screen.getByRole("button", { name: /Zapisz scorecard/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Nie udało się zapisać scorecardu\./,
    );
  });
});
