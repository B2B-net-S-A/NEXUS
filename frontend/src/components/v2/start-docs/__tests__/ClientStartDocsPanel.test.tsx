import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, put: mocks.put, post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.showError, showSuccess: vi.fn() }),
}));

import { ClientStartDocsPanel } from "../ClientStartDocsPanel";

// Dane fikcyjne — repo jest publiczne.
const MARK = { at: "2026-11-20T09:15:00+00:00", by_name: "Kamil Przykładowy" };
const NDA = {
  id: 1,
  name: "NDA",
  note: null,
  kind: "file",
  required: true,
  offset_days: -2,
  link_url: null,
  fill_from_agreement: false,
  template_name: null,
};

function renderPanel(canEdit = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientStartDocsPanel clientId={7} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

describe("ClientStartDocsPanel — „Klient nie wymaga dokumentów”", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.put.mockReset();
    mocks.showError.mockReset();
  });

  it("pusta lista: decyzja jednym przyciskiem, potem z kim i kiedy", async () => {
    mocks.get.mockResolvedValue({ data: { items: [], not_required: null } });
    mocks.put.mockResolvedValue({ data: { items: [], not_required: MARK } });
    renderPanel();
    expect(await screen.findByText("Ten klient nie ma jeszcze listy.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Klient nie wymaga dokumentów" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/start-documents/clients/7/not-required", {
        not_required: true,
      }),
    );
    expect(await screen.findByText(/Klient nie wymaga dokumentów do startu/)).toBeInTheDocument();
    expect(screen.getByText(/Kamil Przykładowy, 20\.11\.2026/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Klient nie wymaga dokumentów" })).toBeNull();
  });

  it("„Cofnij” zdejmuje decyzję", async () => {
    mocks.get.mockResolvedValue({ data: { items: [], not_required: MARK } });
    mocks.put.mockResolvedValue({ data: { items: [], not_required: null } });
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Cofnij" }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/start-documents/clients/7/not-required", {
        not_required: false,
      }),
    );
    expect(await screen.findByText("Ten klient nie ma jeszcze listy.")).toBeInTheDocument();
  });

  it("bez prawa edycji widać decyzję, ale nie ma przycisków", async () => {
    mocks.get.mockResolvedValue({ data: { items: [], not_required: MARK } });
    renderPanel(false);
    expect(await screen.findByText(/Klient nie wymaga dokumentów do startu/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cofnij" })).toBeNull();
  });

  it("lista z pozycjami nie pokazuje decyzji ani przycisku", async () => {
    mocks.get.mockResolvedValue({ data: { items: [NDA], not_required: null } });
    renderPanel();
    expect(await screen.findByText("NDA")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Klient nie wymaga dokumentów" })).toBeNull();
  });

  it("błąd zapisu decyzji idzie do komunikatu, nie znika po cichu", async () => {
    mocks.get.mockResolvedValue({ data: { items: [], not_required: null } });
    mocks.put.mockRejectedValue(
      Object.assign(new Error("x"), {
        isAxiosError: true,
        response: { status: 409, data: { detail: "Lista ma pozycje." } },
      }),
    );
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Klient nie wymaga dokumentów" }));
    await waitFor(() => expect(mocks.showError).toHaveBeenCalledWith("Lista ma pozycje."));
  });
});
