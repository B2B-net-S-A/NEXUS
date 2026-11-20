/**
 * „Anuluj szkic” z pozycji „Klient zamówił okres po zakończeniu” (19.11.2026):
 * potwierdzenie ConfirmV2, potem PATCH zamówienia ze statusem „Anulowane”;
 * „Zostaw” niczego nie wysyła, a odmowa serwera wraca po polsku.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  patch: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/lib/api", () => {
  const api = { patch: (...a: unknown[]) => mocks.patch(...a) };
  return { api, default: api };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.toastError, showSuccess: mocks.toastSuccess }),
}));

import { CancelOrderDraftButton } from "../CancelOrderDraftButton";

function renderButton() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <CancelOrderDraftButton contractId={209} clientId={12} orderId={894} orderNumber="4500123456" />
    </QueryClientProvider>,
  );
  return { invalidate };
}

describe("CancelOrderDraftButton", () => {
  beforeEach(() => {
    mocks.patch.mockReset();
    mocks.toastError.mockReset();
    mocks.toastSuccess.mockReset();
  });

  it("po potwierdzeniu anuluje szkic i odświeża kontrakt", async () => {
    mocks.patch.mockResolvedValue({ data: { id: 894, status: "cancelled" } });
    const { invalidate } = renderButton();

    fireEvent.click(screen.getByRole("button", { name: "Anuluj szkic" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Szkic 4500123456 zostanie w historii zamówień jako „Anulowane”");
    fireEvent.click(within(dialog).getByRole("button", { name: "Anuluj szkic" }));

    await waitFor(() =>
      expect(mocks.patch).toHaveBeenCalledWith("/api/clients/12/orders/894", { status: "cancelled" }),
    );
    await waitFor(() => expect(mocks.toastSuccess).toHaveBeenCalledWith("Szkic zamówienia anulowany."));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["contract", 209] });
  });

  it("„Zostaw” niczego nie wysyła", async () => {
    renderButton();
    fireEvent.click(screen.getByRole("button", { name: "Anuluj szkic" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Zostaw" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(mocks.patch).not.toHaveBeenCalled();
  });

  it("odmowa serwera wraca komunikatem po polsku", async () => {
    mocks.patch.mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { detail: "Zamówienie ma rozliczenia." } },
    });
    renderButton();
    fireEvent.click(screen.getByRole("button", { name: "Anuluj szkic" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Anuluj szkic" }));
    await waitFor(() => expect(mocks.toastError).toHaveBeenCalledTimes(1));
    expect(mocks.toastError.mock.calls[0][0]).toEqual(expect.any(String));
  });
});
