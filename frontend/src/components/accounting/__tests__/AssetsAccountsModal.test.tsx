import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

const put = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: { get: vi.fn(), post: vi.fn(), put: (...a: unknown[]) => put(...a), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { AccountsModal } from "@/components/accounting/AssetForms";
import type { AssetsAccounts } from "@/lib/api/accounting-assets";

const ACCOUNTS: AssetsAccounts = {
  cost_account: "401",
  intake_account: "080",
  disposal_account: "761",
  cost_map: [
    ["070-3", "400-4"],
    ["075", "400-1"],
  ],
};

function renderModal(onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AccountsModal open accounts={ACCOUNTS} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

describe("Konta środków trwałych — mapa umorzeń", () => {
  it("zapisuje mapę umorzenie → amortyzacja, puste konto spoza mapy i pomija puste wiersze", async () => {
    put.mockResolvedValue({ data: ACCOUNTS });
    const user = userEvent.setup();
    const onClose = renderModal();

    expect(screen.getByLabelText("Konto umorzenia 1")).toHaveValue("070-3");
    expect(screen.getByLabelText("Konto amortyzacji 2")).toHaveValue("400-1");

    await user.click(screen.getByRole("button", { name: "Usuń pozycję mapy 2" }));
    await user.click(screen.getByRole("button", { name: "Dodaj umorzenie" }));
    await user.type(screen.getByLabelText("Konto umorzenia 2"), " 070-6 ");
    await user.type(screen.getByLabelText("Konto amortyzacji 2"), "400-7");
    await user.click(screen.getByRole("button", { name: "Dodaj umorzenie" }));
    await user.clear(screen.getByLabelText(/umorzeń spoza mapy/));
    await user.clear(screen.getByLabelText(/Przyjęcie i ulepszenie/));
    await user.type(screen.getByLabelText(/Przyjęcie i ulepszenie/), "085");
    await user.clear(screen.getByLabelText(/Likwidacja i sprzedaż/));
    await user.type(screen.getByLabelText(/Likwidacja i sprzedaż/), "761-2");
    await user.click(screen.getByRole("button", { name: "Zapisz konta" }));

    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect(put.mock.calls[0][1]).toEqual({
      cost_account: "",
      intake_account: "085",
      disposal_account: "761-2",
      cost_map: [
        ["070-3", "400-4"],
        ["070-6", "400-7"],
      ],
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("odmowę serwera pokazuje komunikatem i zostawia dialog otwarty", async () => {
    put.mockReset();
    put.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: "Mapa umorzeń: konta umorzenia 079 nie ma w planie kont." } },
    });
    const user = userEvent.setup();
    const onClose = renderModal();
    await user.click(screen.getByRole("button", { name: "Zapisz konta" }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(expect.stringContaining("079 nie ma w planie kont"), "error"),
    );
    expect(onClose).not.toHaveBeenCalled();
  });
});
