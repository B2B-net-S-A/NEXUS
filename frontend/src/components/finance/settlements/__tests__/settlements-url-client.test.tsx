/**
 * Klient z adresu w Finanse → Rozliczenia.
 *
 * Linki z zakładki „Faktury” kontraktu (`stClient`, `stMonth`, `stContract`)
 * i z raportów klienta (`stClient`) wskazują klienta. Gdy lista klientów była
 * już w pamięci (ktoś wcześniej otworzył Rozliczenia), efekt „domyślny klient”
 * biegł w tym samym cyklu co odczyt adresu, widział jeszcze `clientId == null`
 * i podmieniał klienta na tego z największą liczbą zadań. Dane fikcyjne.
 */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const CLIENTS = [
  { client_id: 1, name: "Klient z zadaniami", todo: 5, active_contracts: 9, rules_set: true },
  { client_id: 12, name: "Klient z linku", todo: 0, active_contracts: 2, rules_set: true },
];

// Lista klientów od razu gotowa — jak z pamięci React Query po wcześniejszej wizycie.
vi.mock("@/lib/api/client-settlements", () => ({
  useContractNipReview: () => ({ data: { items: [] }, isSuccess: true, isError: false }),
  useSettlementClients: () => ({
    data: CLIENTS,
    isSuccess: true,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/lib/api/client-time-reports", () => ({
  useTimeReportClients: () => ({ data: { client_ids: [] } }),
}));
vi.mock("@/lib/api/client-einvoices", () => ({
  useEinvoiceClients: () => ({ data: { client_ids: [] } }),
}));

const cardProps = vi.hoisted(() => ({ last: null as Record<string, unknown> | null }));

vi.mock("../SettlementCard", () => ({
  SettlementCard: (props: Record<string, unknown>) => {
    cardProps.last = props;
    return null;
  },
}));
vi.mock("../ClientInvoiceView", () => ({ ClientInvoiceView: () => null }));
vi.mock("../ClientRulesEditor", () => ({ ClientRulesEditor: () => null }));
vi.mock("../EinvoicesView", () => ({ EinvoicesView: () => null }));
vi.mock("../EstimatesView", () => ({ EstimatesView: () => null }));
vi.mock("../SettlementMonthView", () => ({ SettlementMonthView: () => null }));
vi.mock("../SettlementsStartCard", () => ({ SettlementsStartCard: () => null }));
vi.mock("../TimeReportIdsPanel", () => ({ TimeReportIdsPanel: () => null }));
vi.mock("../TimeReportPersonCard", () => ({ TimeReportPersonCard: () => null }));
vi.mock("../TimeReportView", () => ({ TimeReportView: () => null }));

import { SettlementsTab } from "../SettlementsTab";

afterEach(() => {
  window.history.replaceState(null, "", "/");
  cardProps.last = null;
});

describe("SettlementsTab — klient z adresu", () => {
  it("link z kontraktu otwiera wskazanego klienta, choć lista klientów jest już w pamięci", () => {
    window.history.replaceState(
      null,
      "",
      "/finance?view=settlements&stClient=12&stMonth=2026-10&stContract=684",
    );
    render(<SettlementsTab canWrite={false} />);

    expect(screen.getByRole("combobox", { name: "Klient" })).toHaveValue("12");
    expect(cardProps.last).toMatchObject({ contractId: 684, month: "2026-10" });
  });

  it("bez klienta w adresie wybiera klienta z największą liczbą zadań", () => {
    window.history.replaceState(null, "", "/finance?view=settlements");
    render(<SettlementsTab canWrite={false} />);

    expect(screen.getByRole("combobox", { name: "Klient" })).toHaveValue("1");
  });
});
