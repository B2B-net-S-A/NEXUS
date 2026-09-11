import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AxiosError, AxiosHeaders } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeleteClientDialog } from "./DeleteClientDialog";
import type { ClientDeletionCheck } from "@/lib/client-deletion";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  del: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { post: mocks.post, delete: mocks.del },
  extractErrorMsg: (error: unknown) =>
    (error as { response?: { data?: { detail?: string } } })?.response?.data
      ?.detail ?? "Błąd",
}));

function check(overrides: Partial<ClientDeletionCheck> = {}): ClientDeletionCheck {
  return {
    client_id: 7,
    client_name: "Firma Przykładowa",
    status: "active",
    mode: "purge",
    can_delete: true,
    blockers: [],
    history: [],
    history_sentence: null,
    confirmation_phrase: "0",
    ...overrides,
  };
}

function renderDialog(onDeleted = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <DeleteClientDialog
        clientId={7}
        clientName="Firma Przykładowa"
        open
        onOpenChange={vi.fn()}
        onDeleted={onDeleted}
      />
    </QueryClientProvider>,
  );
  return onDeleted;
}

describe("DeleteClientDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("ocenia klienta raz po otwarciu i wymaga wpisania „0”", async () => {
    mocks.post.mockResolvedValue({ data: check() });
    mocks.del.mockResolvedValue({
      data: {
        client_id: 7,
        client_name: "Firma Przykładowa",
        result: "purged",
        history: [],
        history_sentence: null,
      },
    });
    const onDeleted = renderDialog();
    const user = userEvent.setup();

    expect(
      await screen.findByLabelText(
        "Czy na pewno chcesz usunąć tego klienta? Wpisz 0, jak chcesz usunąć.",
      ),
    ).toBeInTheDocument();
    expect(mocks.post).toHaveBeenCalledTimes(1);
    expect(mocks.post).toHaveBeenCalledWith("/api/clients/7/deletion-check");
    expect(
      screen.getByText("Klient nie ma żadnych powiązanych danych — zostanie usunięty trwale."),
    ).toBeInTheDocument();

    const confirm = screen.getByRole("button", { name: "Usuń klienta" });
    expect(confirm).toBeDisabled();

    const input = screen.getByRole("textbox");
    await user.type(input, "1");
    expect(confirm).toBeDisabled();

    await user.clear(input);
    await user.type(input, "0");
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(mocks.del).toHaveBeenCalledWith("/api/clients/7", {
      params: { confirmation: "0" },
    });
  });

  it("przed potwierdzeniem pokazuje, co jest powiązane z klientem z historią", async () => {
    mocks.post.mockResolvedValue({
      data: check({
        mode: "archive",
        history: [
          { code: "archived_consultants", label: "archiwum konsultantów", count: 2 },
          { code: "orders", label: "poprzednie zamówienia", count: 3 },
        ],
        history_sentence:
          "U tego klienta występują: archiwum konsultantów, poprzednie zamówienia.",
      }),
    });
    renderDialog();

    expect(
      await screen.findByText(
        "U tego klienta występują: archiwum konsultantów, poprzednie zamówienia.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/pozostaną zachowane w systemie/)).toBeInTheDocument();
    expect(
      screen.getByLabelText(
        "Czy na pewno chcesz usunąć tego klienta? Wpisz 0, jak chcesz usunąć.",
      ),
    ).toBeInTheDocument();
  });

  it("przy blokadzie nie daje pola potwierdzenia i wymienia powody", async () => {
    mocks.post.mockResolvedValue({
      data: check({
        mode: "blocked",
        can_delete: false,
        blockers: [
          {
            code: "open_orders",
            label: "Otwarte zamówienia",
            count: 1,
            items: ["ZAM-1 — Jan Testowy"],
          },
        ],
      }),
    });
    renderDialog();

    expect(await screen.findByText("Otwarte zamówienia: 1")).toBeInTheDocument();
    expect(screen.getByText("ZAM-1 — Jan Testowy")).toBeInTheDocument();
    expect(screen.getByText(/odnotowana w Historii zdarzeń/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usuń klienta" })).not.toBeInTheDocument();
  });

  it("gdy w międzyczasie pojawiła się blokada, przełącza okno na blokadę", async () => {
    mocks.post.mockResolvedValue({ data: check() });
    const blocked = check({
      mode: "blocked",
      can_delete: false,
      blockers: [
        { code: "active_contractors", label: "Aktywni kontraktorzy", count: 1, items: [] },
      ],
    });
    mocks.del.mockRejectedValue(
      new AxiosError("Conflict", "ERR_BAD_REQUEST", undefined, undefined, {
        status: 409,
        statusText: "Conflict",
        headers: {},
        config: { headers: new AxiosHeaders() },
        data: { detail: "Usunięcie zablokowane", check: blocked },
      }),
    );
    const onDeleted = renderDialog();
    const user = userEvent.setup();

    await user.type(await screen.findByRole("textbox"), "0");
    await user.click(screen.getByRole("button", { name: "Usuń klienta" }));

    expect(await screen.findByText("Aktywni kontraktorzy: 1")).toBeInTheDocument();
    expect(onDeleted).not.toHaveBeenCalled();
  });
});
