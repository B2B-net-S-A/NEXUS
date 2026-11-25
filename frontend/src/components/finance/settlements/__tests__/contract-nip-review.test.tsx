import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContractNipReviewCard } from "../ContractNipReviewCard";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: vi.fn(), put: vi.fn() } }));

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContractNipReviewCard />
    </QueryClientProvider>,
  );
}

const item = {
  contract_id: 41,
  client_id: 3,
  client_name: "Bank Przykładowy",
  person: "Jan Testowy",
  partner_nip: "9980000000",
  partner_name: "Jan Testowy",
  partner_legal_name: null,
  generated_contract_id: 9,
  sellers: [{ name: "FUNDACJA PRZYKŁAD", invoices: 12 }],
  invoices: 12,
  reasons: [
    {
      key: "seller_without_person",
      label: "Faktury z tego NIP-u wystawia firma bez imienia i nazwiska osoby",
    },
  ],
};

describe("ContractNipReviewCard (umowy B2B z NIP-em innej firmy)", () => {
  beforeEach(() => {
    mocks.get.mockReset();
  });

  it("pokazuje liczbę i po rozwinięciu kontrakt z powodem i sprzedawcą", async () => {
    mocks.get.mockResolvedValue({ data: { items: [item] } });
    renderCard();
    const toggle = await screen.findByRole("button", { name: /Umowy B2B z NIP-em innej firmy: 1/ });
    expect(mocks.get).toHaveBeenCalledWith("/api/finance/settlements/contract-nip-review");
    fireEvent.click(toggle);
    expect(screen.getByRole("link", { name: "Jan Testowy" })).toHaveAttribute("href", "/contracts/41");
    expect(screen.getByText(/Sprzedawca w KSeF: FUNDACJA PRZYKŁAD \(12\)/)).toBeInTheDocument();
  });

  it("pusta lista — brak karty", async () => {
    mocks.get.mockResolvedValue({ data: { items: [] } });
    const { container } = renderCard();
    await vi.waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("awaria zapytania nie wygląda jak pusta lista", async () => {
    mocks.get.mockRejectedValue(new Error("500"));
    renderCard();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.queryByRole("button", { name: /Umowy B2B/ })).not.toBeInTheDocument();
  });
});
