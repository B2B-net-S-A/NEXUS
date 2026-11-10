import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientInvoiceMonth, ClientInvoiceRow } from "@/lib/api/client-settlements";

import { ClientInvoiceView, positionsText } from "../ClientInvoiceView";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: vi.fn(), put: vi.fn() } }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));

const ready: ClientInvoiceRow = {
  contract_id: 1,
  person: "Jan Testowy",
  order_number: "ZAM_1",
  kind: "actual",
  state: "ready",
  positions: [
    { name: "Usługi; ZAM_1", unit: "MD", quantity: "17", unit_price: "1100.00", net: "18700.00", kind: "base" },
    { name: "Usługi; ZAM_1_nadgodziny", unit: "MD", quantity: "4.75", unit_price: "1320.00", net: "6270.00", kind: "overtime" },
  ],
  net: "24970.00",
  cost: "22700.00",
  margin: "2270.00",
  margin_pct: "9.1",
  template: true,
  ksef_number: null,
  invoice_number: null,
};

function renderView(data: ClientInvoiceMonth) {
  mocks.get.mockResolvedValue({ data });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientInvoiceView clientId={7} month="2026-10" />
    </QueryClientProvider>,
  );
}

describe("Do faktury dla klienta (E5.1)", () => {
  beforeEach(() => mocks.get.mockReset());

  it("kopiuje tylko pozycje do wystawienia, z przecinkiem dziesiętnym i tabulatorami", () => {
    const issued = { ...ready, contract_id: 2, state: "issued" as const };
    expect(positionsText([ready, issued])).toBe(
      "Usługi; ZAM_1\t17\tMD\t1100,00\t18700,00\nUsługi; ZAM_1_nadgodziny\t4,75\tMD\t1320,00\t6270,00",
    );
  });

  it("pokazuje pozycje, marżę i ostrzeżenie przy nazwie zastępczej", async () => {
    renderView({
      client_id: 7,
      client_name: "Klient Testowy",
      month: "2026-10",
      can_see_amounts: true,
      rows: [
        ready,
        { ...ready, contract_id: 3, person: "Ola Bezwzoru", template: false },
        { ...ready, contract_id: 4, person: "Czeka Ktoś", kind: null, state: "waiting", positions: [] },
      ],
    });
    expect(await screen.findByText("Faktura do Klient Testowy za październik 2026")).toBeInTheDocument();
    expect(screen.getAllByText(/Usługi; ZAM_1_nadgodziny · 4,75 MD/)).toHaveLength(2);
    expect(screen.getByText(/2 do wystawienia, 0 wystawione, 1 czeka/)).toBeInTheDocument();
    expect(screen.getByText(/Bez poprzedniej faktury: nazwa zastępcza/)).toBeInTheDocument();
    expect(screen.queryByText("Czeka Ktoś")).not.toBeInTheDocument();
  });
});
