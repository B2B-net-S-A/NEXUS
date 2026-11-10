import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ContractorInvoiceBlock } from "@/lib/api/client-settlements";

import { ContractorInvoiceSection } from "../SettlementCard";

const mocks = vi.hoisted(() => ({ post: vi.fn(), showSuccess: vi.fn(), showError: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { post: mocks.post, get: vi.fn(), put: vi.fn() } }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

const suggested: ContractorInvoiceBlock = {
  state: "nip_check",
  invoices: [
    {
      id: 7,
      ksef_number: "9980000000-20261103-ABCDEF000000-01",
      invoice_number: "FV 3/11/2026",
      issue_date: "2026-11-03",
      acquired_at: "2026-11-03T10:00:00+00:00",
      seller_name: "Jan Testowy Usługi IT",
      seller_nip: "9980000000",
      nip_state: "suggested",
      net_amount: "15000.00",
      gross_amount: "18450.00",
      due_date: "2026-11-17",
    },
  ],
  checks: [{ state: "warn", title: "NIP z KSeF do zatwierdzenia", detail: "Sprzedawca: Jan Testowy Usługi IT." }],
};

function renderSection(block: ContractorInvoiceBlock, canWrite = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContractorInvoiceSection block={block} canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

describe("ContractorInvoiceSection (Finanse, E4)", () => {
  beforeEach(() => {
    mocks.post.mockReset().mockResolvedValue({ data: {} });
  });

  it("podpowiedź NIP-u: zatwierdzenie po potwierdzeniu woła approve-nip", async () => {
    renderSection(suggested);
    expect(screen.getByText("NIP do zatwierdzenia")).toBeInTheDocument();
    expect(screen.getByText(/NIP 9980000000 nie jest zapisany przy tej osobie/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zatwierdź NIP" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Zatwierdź NIP" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/contractor-invoices/7/approve-nip"),
    );
    expect(mocks.showSuccess).toHaveBeenCalledWith("NIP zapisany.");
  });

  it("bez prawa zapisu nie ma przycisków decyzji", () => {
    renderSection(suggested, false);
    expect(screen.queryByRole("button", { name: "Zatwierdź NIP" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "To nie ta osoba" })).not.toBeInTheDocument();
  });

  it("inna kwota: stan i różnica z kontroli", () => {
    renderSection({
      state: "differs",
      invoices: [{ ...suggested.invoices[0], nip_state: "known", net_amount: "16000.00" }],
      checks: [
        { state: "fail", title: "Inna kwota niż wyliczenie z RCP", detail: "Faktura 16 000,00 zł netto, wyliczenie 15 000,00 zł, różnica 1 000,00 zł." },
      ],
    });
    expect(screen.getByText("Inna kwota")).toBeInTheDocument();
    expect(screen.getByText(/różnica 1 000,00 zł/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zatwierdź NIP" })).not.toBeInTheDocument();
  });
});
