import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
const showSuccess = vi.fn();

vi.mock("@/lib/api", () => {
  const client = { post: (...a: unknown[]) => post(...a), get: vi.fn() };
  return { __esModule: true, default: client, api: client };
});
vi.mock("@/components/Toast", () => ({
  useOptionalToast: () => ({ showSuccess, showInfo: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/lib/requirement-rows-api", () => ({
  useWordCounts: (words: string[]) => Object.fromEntries(words.map((w) => [w, 23342])),
}));

import { ClientChangeDialog } from "@/components/champion/ClientChangeDialog";

const PROPOSAL = {
  status: "ready",
  note: "Klient dokłada Pythona.",
  message: null,
  profile_hash: "h".repeat(64),
  changes: [
    { id: "c1", op: "row_add", word: "Python", level: "must", quote: "Python is now a must" },
    { id: "c2", op: "row_remove", word: "SAFe", before: "nice", quote: "SAFe is out" },
    {
      id: "c3",
      op: "text_edit",
      field: "client.selling_points",
      label: "Co powiedzieć kandydatowi",
      before: "Metodologia pracy: SAFe",
      after: "Metodologia pracy: Kanban",
      quote: "moved to Kanban",
    },
  ],
  gaps: [
    {
      word: "Python",
      open_total: 40,
      missing: { before_screening: 16, after_screening: 1, at_client: 0 },
      people: [
        {
          process_id: 5,
          candidate_id: 9,
          name: "Osoba Przykładowa",
          stage: "after_screening",
          owner_user_id: 3,
        },
      ],
    },
  ],
};

function renderDialog(initialText?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <ClientChangeDialog jobId={7} open onOpenChange={onOpenChange} initialText={initialText} />
    </QueryClientProvider>,
  );
  return { onOpenChange };
}

describe("ClientChangeDialog", () => {
  beforeEach(() => {
    post.mockReset();
    showSuccess.mockReset();
  });

  it("proposes changes from pasted text and applies only the checked ones with the note", async () => {
    post.mockImplementation((url: string) =>
      url.endsWith("/apply")
        ? Promise.resolve({ data: { applied: 2, notified: 1, champion_profile: {} } })
        : Promise.resolve({ data: PROPOSAL }),
    );
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();

    expect(screen.getByTestId("client-change-propose")).toBeDisabled();
    await user.type(screen.getByTestId("client-change-text"), "Python is now a must, SAFe out");
    await user.click(screen.getByTestId("client-change-propose"));

    expect(await screen.findByText("Zmiana od klienta: 3 zmiany do sprawdzenia")).toBeInTheDocument();
    expect(post).toHaveBeenCalledWith("/api/jobs/7/champion-profile/client-change", {
      text: "Python is now a must, SAFe out",
    });
    expect(screen.getByText(/W bazie: 23\s342 osoby/)).toBeInTheDocument();
    expect(screen.getByText(/bez słowa „Python” w CV/)).toBeInTheDocument();
    // Różnica w polu tekstowym: SAFe → Kanban.
    expect(screen.getByText("Kanban").tagName).toBe("INS");

    await user.click(screen.getByRole("checkbox", { name: "Zastosuj zmianę c2" }));
    await user.click(screen.getByTestId("client-change-apply"));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    const [url, body] = post.mock.calls[1];
    expect(url).toBe("/api/jobs/7/champion-profile/client-change/apply");
    expect(body.changes.map((c: { id: string }) => c.id)).toEqual(["c1", "c3"]);
    expect(body).toMatchObject({
      note: "Klient dokłada Pythona.",
      notify_gaps: true,
      expected_profile_hash: "h".repeat(64),
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(showSuccess).toHaveBeenCalledWith(
      "Zapisano 2 zmiany, dzwonek „dopytaj” dostało 1 osoba.",
    );
  });

  it("lets the DL change the level and correct the text before saving", async () => {
    post.mockImplementation((url: string) =>
      url.endsWith("/apply")
        ? Promise.resolve({ data: { applied: 1, notified: 0, champion_profile: {} } })
        : Promise.resolve({ data: { ...PROPOSAL, changes: [PROPOSAL.changes[0]], gaps: [] } }),
    );
    const user = userEvent.setup();
    renderDialog("klient dorzuca pythona jako musi mieć");

    await screen.findByText("Zmiana od klienta: 1 zmiana do sprawdzenia");
    await user.selectOptions(screen.getByLabelText("Poziom: Python"), "nice");
    await user.click(screen.getByRole("button", { name: "Popraw" }));
    const field = screen.getByLabelText("Popraw tekst zmiany");
    await user.clear(field);
    await user.type(field, "Python 3");
    await user.click(screen.getByTestId("client-change-apply"));

    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1][1].changes[0]).toMatchObject({ word: "Python 3", level: "nice" });
    expect(post.mock.calls[1][1].notify_gaps).toBe(false);
  });

  it("shows the model failure and keeps the text for another try", async () => {
    post.mockResolvedValue({
      data: { status: "failed", changes: [], note: "", gaps: [], profile_hash: null,
        message: "Nie udało się przygotować zmian." },
    });
    const user = userEvent.setup();
    renderDialog();
    await user.type(screen.getByTestId("client-change-text"), "Python is now a must");
    await user.click(screen.getByTestId("client-change-propose"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się przygotować zmian.");
    expect(screen.getByTestId("client-change-text")).toHaveValue("Python is now a must");
  });

  it("on 409 conflict returns to the text with a message", async () => {
    post.mockImplementation((url: string) =>
      url.endsWith("/apply")
        ? Promise.reject({ response: { status: 409, data: {} } })
        : Promise.resolve({ data: PROPOSAL }),
    );
    const user = userEvent.setup();
    renderDialog("Python is now a must, SAFe out");
    await screen.findByText("Zmiana od klienta: 3 zmiany do sprawdzenia");
    await user.click(screen.getByTestId("client-change-apply"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ktoś zmienił Profil");
    expect(screen.getByTestId("client-change-text")).toBeInTheDocument();
  });
});
