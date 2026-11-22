import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SettlementExtra, SettlementExtrasBlock } from "@/lib/api/client-settlements";

import { ExtrasSection } from "../ExtrasSection";

const mocks = vi.hoisted(() => ({ post: vi.fn(), showSuccess: vi.fn(), showError: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { post: mocks.post, get: vi.fn(), put: vi.fn() } }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

const extra = (over: Partial<SettlementExtra>): SettlementExtra => ({
  id: 5,
  contract_id: 11,
  month: "2026-10",
  kind: "tech_check",
  kind_label: "Weryfikacja techniczna",
  amount: "200.00",
  description: "Weryfikacja techniczna",
  status: "pending",
  status_label: "Zgłoszony",
  source: "back_office",
  source_label: "back office",
  reported_by: "Osoba z opieki",
  decided_by: null,
  decided_at: null,
  decision_note: null,
  bill_to_client: false,
  bo_card_id: 3,
  counts_on_invoice: true,
  created_at: "2026-11-13T10:00:00+00:00",
  documents: [],
  ...over,
});

const block = (items: SettlementExtra[]): SettlementExtrasBlock => ({
  items,
  approved_total: "0.00",
  pending_total: "200.00",
  pending_count: items.filter((i) => i.status === "pending").length,
  kinds: [
    { key: "referral", label: "Premia za polecenie" },
    { key: "tech_check", label: "Weryfikacja techniczna" },
    { key: "travel", label: "Delegacja" },
    { key: "other", label: "Inny dodatek" },
  ],
});

function renderSection(b: SettlementExtrasBlock, canWrite = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ExtrasSection contractId={11} month="2026-10" block={b} canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

describe("ExtrasSection (Finanse → karta osoby)", () => {
  beforeEach(() => {
    mocks.post.mockReset().mockResolvedValue({ data: {} });
    mocks.showSuccess.mockReset();
  });

  it("zgłoszony dodatek: zatwierdzenie woła approve dla miesiąca", async () => {
    renderSection(block([extra({})]));
    expect(screen.getByText("Zgłoszony")).toBeInTheDocument();
    expect(screen.getByText(/back office: Osoba z opieki/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zatwierdź" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/finance/settlements/contract/11/extras/5/approve",
        { bill_to_client: null },
        { params: { month: "2026-10" } },
      ),
    );
  });

  it("odrzucenie tylko z powodem", async () => {
    renderSection(block([extra({})]));
    fireEvent.click(screen.getByRole("button", { name: "Odrzuć" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Brak zlecenia od rekrutera" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Odrzuć dodatek" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/finance/settlements/contract/11/extras/5/reject",
        { reason: "Brak zlecenia od rekrutera" },
        { params: { month: "2026-10" } },
      ),
    );
  });

  it("delegacja bez dokumentów dostaje uwagę, a koszty integracji nie są tu pokazane", () => {
    renderSection(
      block([
        extra({ id: 6, kind: "travel", kind_label: "Delegacja", description: "Kraków" }),
        extra({ id: 7, kind: "integration", kind_label: "Koszty integracji", counts_on_invoice: false }),
      ]),
    );
    expect(screen.getByText(/Delegacja bez dokumentów/)).toBeInTheDocument();
    expect(screen.queryByText("Koszty integracji")).not.toBeInTheDocument();
  });

  it("wpis Finansów: kwota z przecinkiem i znacznik faktury dla klienta", async () => {
    renderSection(block([]));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj dodatek" }));
    fireEvent.change(screen.getByLabelText("Rodzaj dodatku"), { target: { value: "referral" } });
    fireEvent.change(screen.getByLabelText("Kwota netto (zł)"), { target: { value: "1 000,50" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz i zatwierdź" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/contract/11/extras", {
        month: "2026-10",
        kind: "referral",
        amount: "1000.50",
        description: null,
        bill_to_client: true,
      }),
    );
  });

  it("bez prawa zapisu: bez przycisków", () => {
    renderSection(block([extra({})]), false);
    expect(screen.queryByRole("button", { name: "Zatwierdź" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj dodatek" })).not.toBeInTheDocument();
  });
});
