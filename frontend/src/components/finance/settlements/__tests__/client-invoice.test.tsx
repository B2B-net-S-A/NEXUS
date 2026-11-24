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
    { name: "Usługi; ZAM_1", unit: "MD", quantity: "17", unit_price: "1100.00", net: "18700.00", kind: "base", currency: "PLN" },
    { name: "Usługi; ZAM_1_nadgodziny", unit: "MD", quantity: "4.75", unit_price: "1320.00", net: "6270.00", kind: "overtime", currency: "PLN" },
  ],
  currency: "PLN",
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
    // Hurtem tylko wystawione (nazwa z numeru KSeF), przy osobie — jej RCP.
    expect(screen.getByRole("button", { name: /Pobierz RCP wystawionych \(0\)/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Pobierz RCP: Jan Testowy" })).toBeEnabled();
  });

  it("osoba z podziałem z maila klienta ma wiersz na każde zamówienie", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const part = (orderId: number, number: string, quantity: string, state: ClientInvoiceRow["state"]): ClientInvoiceRow => ({
      ...ready,
      order_id: orderId,
      order_number: number,
      state,
      invoice_number: state === "issued" ? "155/11/2026" : null,
      positions: [{ name: `Usługi; ${number}`, unit: "MD", quantity, unit_price: "800.00", net: "0.00", kind: "base", currency: "PLN" }],
    });
    renderView({
      client_id: 7,
      client_name: "Klient Testowy",
      month: "2026-10",
      can_see_amounts: true,
      rows: [part(11, "4500011111", "5", "ready"), part(12, "4500022222", "17", "issued")],
    });
    expect(await screen.findByText("4500011111")).toBeInTheDocument();
    expect(screen.getByText("4500022222")).toBeInTheDocument();
    expect(screen.getByText(/Usługi; 4500011111 · 5 MD/)).toBeInTheDocument();
    expect(screen.getByText(/Usługi; 4500022222 · 17 MD/)).toBeInTheDocument();
    expect(screen.getByText(/1 do wystawienia, 1 wystawione/)).toBeInTheDocument();
    expect(errors.mock.calls.some((call) => String(call[0]).includes("same key"))).toBe(false);
    errors.mockRestore();
  });
});

describe("Do faktury dla klienta z T4T (Nordea)", () => {
  beforeEach(() => mocks.get.mockReset());

  const t4tRow: ClientInvoiceRow = {
    ...ready,
    kind: "time_report",
    positions: [
      { name: "NIDS:2020-000001, IT", unit: "godz.", quantity: "176", unit_price: "150.00", net: "26400.00", kind: "base", currency: "PLN" },
    ],
    t4t: { approved: "176.00", pending: "0.00", billed: "176.00", invoiced: null, notes: [] },
  };

  it("wstrzymuje osobę z godzinami niezatwierdzonymi i pokazuje termin faktury", async () => {
    const held: ClientInvoiceRow = {
      ...t4tRow,
      contract_id: 5,
      person: "Piotr Wzorcowy",
      state: "awaiting_t4t",
      hold_reason: "Godziny niezatwierdzone w T4T (wersja z 10.11): 32 h czeka na akceptację.",
      t4t: { approved: "144.00", pending: "32.00", billed: "144.00", invoiced: null, notes: ["Mail z akceptacją nie pochodzi od managera klienta."] },
    };
    renderView({
      client_id: 7,
      client_name: "Klient T4T",
      month: "2026-10",
      can_see_amounts: true,
      time_report: { version_id: 3, received_on: "2026-11-10", label: "wersja z 10.11" },
      deadline: { date: "2026-11-15", days_left: 3, overdue: false, missing: 1, people: ["Piotr Wzorcowy"] },
      rows: [t4tRow, held],
    });
    expect(await screen.findByText(/1 czeka na godziny w T4T, 0 bez zatwierdzonych godzin/)).toBeInTheDocument();
    expect(screen.getByText(/Godziny niezatwierdzone w T4T \(wersja z 10\.11\)/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Do terminu faktury 15.11 zostały 3 dni: 1 osoba bez zatwierdzonych godzin w T4T. Bez godzin: Piotr Wzorcowy.",
    );
    expect(screen.getAllByText("Czeka na T4T").length).toBeGreaterThan(0);
    // Do skopiowania idzie tylko osoba z zatwierdzonymi godzinami.
    expect(positionsText([t4tRow, held])).toBe("NIDS:2020-000001, IT\t176\tgodz.\t150,00\t26400,00");
  });
});
