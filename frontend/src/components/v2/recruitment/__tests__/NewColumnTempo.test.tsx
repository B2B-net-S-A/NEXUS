import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NewColumnTempo } from "@/components/v2/recruitment/NewColumnTempo";
import { newColumnTargetHint, type NewColumnTempoState } from "@/lib/api/reviewBatch";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  showError: vi.fn(),
  showSuccess: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ default: { post: mocks.post } }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.showError, showSuccess: mocks.showSuccess }),
}));

type Enabled = Extract<NewColumnTempoState, { enabled: true }>;

function tempo(overrides: Partial<Enabled> = {}): Enabled {
  return {
    enabled: true,
    tier: "moderate",
    target: 10,
    decisions: 4,
    waiting: 10,
    more_cards: 10,
    can_add_more: true,
    ...overrides,
  };
}

function renderIt(state: Enabled = tempo(), readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NewColumnTempo jobId={7} readOnly={readOnly} tempo={state} />
    </QueryClientProvider>,
  );
}

async function confirmAddMore() {
  fireEvent.click(await screen.findByTestId("new-column-add-more"));
  fireEvent.click(await screen.findByRole("button", { name: "Dodaj 10" }));
}

describe("NewColumnTempo", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("pokazuje cel i przycisk osobie z prawem edycji", async () => {
    renderIt();
    expect(await screen.findByTestId("new-column-target")).toHaveTextContent("cel 10");
    expect(screen.getByTestId("new-column-add-more")).toHaveTextContent("Dodaj 10 kolejnych");
  });

  it("bez prawa edycji zostaje sama plakietka", async () => {
    renderIt(tempo({ can_add_more: false }));
    await screen.findByTestId("new-column-target");
    expect(screen.queryByTestId("new-column-add-more")).toBeNull();
  });

  it("widok tylko do odczytu nie ma przycisku", async () => {
    renderIt(tempo(), true);
    await screen.findByTestId("new-column-target");
    expect(screen.queryByTestId("new-column-add-more")).toBeNull();
  });

  it("dodaje dopiero po potwierdzeniu", async () => {
    mocks.post.mockResolvedValue({ data: { added: 3 } });
    renderIt();
    fireEvent.click(await screen.findByTestId("new-column-add-more"));
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Dodaj 10" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/review-batch/jobs/7/more"));
    await waitFor(() => expect(mocks.showSuccess).toHaveBeenCalledWith("Dodano 3 osoby do „Nowych”."));
  });

  it("mówi, gdy w puli nikogo nie ma", async () => {
    mocks.post.mockResolvedValue({ data: { added: 0 } });
    renderIt();
    await confirmAddMore();
    await waitFor(() =>
      expect(mocks.showSuccess).toHaveBeenCalledWith("W puli nie ma już kolejnych osób dla tej rekrutacji."),
    );
  });

  it("pokazuje komunikat serwera przy odmowie", async () => {
    mocks.post.mockRejectedValue({ response: { status: 409, data: { detail: "Najpierw przejrzyj swoje osoby." } } });
    renderIt();
    await confirmAddMore();
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Najpierw przejrzyj swoje osoby."));
  });
});

describe("newColumnTargetHint", () => {
  it.each([
    [tempo({ tier: "quiet", target: 5, decisions: 0 }), "Cel 5: bez decyzji w 21 dni. Reszta przyciskiem."],
    [tempo({ tier: "moderate", target: 10, decisions: 1 }), "Cel 10: 1 decyzja w 21 dni. Reszta przyciskiem."],
    [tempo({ tier: "hot", target: 20, decisions: 12 }), "Cel 20: 12 decyzji w 21 dni. Dopełnia się po ruchu karty."],
    [tempo({ tier: "new", target: 20, decisions: 0 }), "Cel 20: rekrutacja do 14 dni. Dopełnia się po ruchu karty."],
    [tempo({ tier: "p0", target: 20, decisions: 0 }), "Cel 20: P0. Dopełnia się po ruchu karty."],
  ])("%#", (state, expected) => {
    expect(newColumnTargetHint(state)).toBe(expected);
  });
});
