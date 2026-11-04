import { describe, expect, it } from "vitest";

import {
  canTerminateContractor,
  contractorRowSummary,
} from "@/components/client-profile/orders/contractor-order-row";
import type { ClientOrderRead, ContractWithOrdersRead } from "@/lib/api/dlPortal";

const TODAY = "2026-09-29";

function order(partial: Partial<ClientOrderRead> & { id: number }): ClientOrderRead {
  return {
    client_id: 7,
    contract_id: 529,
    job_id: null,
    framework_contract_id: null,
    title: `Z-${partial.id}`,
    description: null,
    status: "active",
    order_type: "periodic",
    start_date: "2026-07-01",
    end_date: null,
    rate_unit: "hourly",
    rate_candidate: null,
    rate_client: 180,
    total_value: null,
    currency: "PLN",
    rate_client_currency: "PLN",
    rate_candidate_currency: "PLN",
    project_part: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    created_by_user_id: null,
    notes: null,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-01T00:00:00Z",
    candidate_id: 99,
    candidate_name: "Tomasz Sadowski",
    contract_status: "active",
    job_title: null,
    monthly_margin: null,
    days_to_end: null,
    ...partial,
  } as ClientOrderRead;
}

function contractor(
  partial: Partial<ContractWithOrdersRead> = {},
): ContractWithOrdersRead {
  return {
    contract_id: 529,
    candidate_id: 99,
    candidate_name: "Tomasz Sadowski",
    contract_status: "active",
    contract_start_date: "2025-07-01",
    contract_end_date: null,
    rate_candidate: 120,
    rate_client_currency: "PLN",
    rate_candidate_currency: "PLN",
    rate_unit: "hourly",
    initial_job_id: null,
    initial_job_title: null,
    latest_order_id: null,
    latest_order_end_date: null,
    latest_order_rate_client: null,
    latest_order_monthly_margin: null,
    days_to_latest_end: null,
    orders: [order({ id: 1 })],
    ...partial,
  };
}

describe("contractorRowSummary", () => {
  it("aktywne zamówienie bezterminowe: numer, okres, obie stawki i stan „Aktywne”", () => {
    const row = contractorRowSummary(contractor(), TODAY);
    expect(row).toMatchObject({
      key: "contract-529",
      contractId: 529,
      name: "Tomasz Sadowski",
      orderNumber: "Z-1",
      periodLabel: "01.07.2026 → bezterminowo",
      costLabel: "120 PLN/h",
      costFromContract: true,
      revenueLabel: "180 PLN/h",
      state: { kind: "active", label: "Aktywne", tone: "ok" },
      futureCount: 0,
      historyCount: 0,
      isDraftCard: false,
      isEnded: false,
    });
  });

  it("zamówienie kończące się jutro: „kończy się za 1 dzień”, bez numeru i słowa „przyszłe”", () => {
    const row = contractorRowSummary(
      contractor({
        ending_without_successor_order_id: 1,
        ending_without_successor_days: 1,
        orders: [order({ id: 1, end_date: "2026-09-30" })],
      }),
      TODAY,
    );
    expect(row.state).toEqual({
      kind: "ending",
      label: "kończy się za 1 dzień",
      tone: "warn",
    });
  });

  it("przyszłe zamówienie, które samo się kończy: „przyszłe zamówienie X kończy się…”", () => {
    const row = contractorRowSummary(
      contractor({
        ending_without_successor_order_id: 2,
        ending_without_successor_days: 20,
        orders: [
          order({ id: 2, title: "NEXT-2", start_date: "2026-10-04", end_date: "2026-10-19" }),
          order({ id: 1, title: "CUR-2", start_date: "2026-06-01", end_date: "2026-10-03" }),
        ],
      }),
      TODAY,
    );
    expect(row.state.label).toBe("przyszłe zamówienie NEXT-2 kończy się za 20 dni");
    expect(row.orderNumber).toBe("CUR-2");
    expect(row.futureCount).toBe(1);
  });

  it("jedyne zamówienie, które jeszcze się nie zaczęło, mówi „kończy się za N dni” (górny slot)", () => {
    const row = contractorRowSummary(
      contractor({
        ending_without_successor_order_id: 3,
        ending_without_successor_days: 20,
        orders: [order({ id: 3, start_date: "2026-10-02", end_date: "2026-10-19" })],
      }),
      TODAY,
    );
    expect(row.state.label).toBe("kończy się za 20 dni");
    expect(row.futureCount).toBe(0);
  });

  it("okres minął, umowa trwa: „Brak aktywnego zamówienia” (nie „Zakończony”)", () => {
    const row = contractorRowSummary(
      contractor({
        orders: [
          order({ id: 4, status: "completed", start_date: "2026-01-01", end_date: "2026-08-31" }),
        ],
      }),
      TODAY,
    );
    expect(row.state).toEqual({
      kind: "no_active_order",
      label: "Brak aktywnego zamówienia",
      tone: "bad",
    });
    expect(row.isEnded).toBe(false);
  });

  it("karta szkicu: „Brak zamówienia”, bez numeru i okresu", () => {
    const row = contractorRowSummary(
      contractor({ draft_card: true, rate_candidate: null, orders: [] }),
      TODAY,
    );
    expect(row).toMatchObject({
      isDraftCard: true,
      orderNumber: null,
      periodLabel: null,
      costLabel: null,
      revenueLabel: null,
      state: { kind: "no_order", label: "Brak zamówienia", tone: "warn" },
    });
  });

  it("umowa zakończona przed dziś: „Zakończony DD.MM.RRRR”, isEnded", () => {
    const row = contractorRowSummary(
      contractor({
        contract_status: "ended",
        contract_end_date: "2026-08-31",
        orders: [order({ id: 5, status: "active" })],
      }),
      TODAY,
    );
    expect(row.isEnded).toBe(true);
    expect(row.state).toEqual({
      kind: "ended",
      label: "Zakończony 31.08.2026",
      tone: "mut",
    });
  });

  it("status „ended” z datą w przyszłości to jeszcze nie „Zakończeni”", () => {
    const row = contractorRowSummary(
      contractor({ contract_status: "ended", contract_end_date: "2026-10-31" }),
      TODAY,
    );
    expect(row.isEnded).toBe(false);
  });

  it("bez dostępu do kwot etykiety stawek są puste (tabela pokaże „—”)", () => {
    const row = contractorRowSummary(contractor(), TODAY, { canViewFinance: false });
    expect(row.costLabel).toBeNull();
    expect(row.revenueLabel).toBeNull();
    expect(row.costFromContract).toBe(false);
    // Reszta wiersza zostaje — redakcja dotyczy wyłącznie kwot.
    expect(row.orderNumber).toBe("Z-1");
  });

  it("stawka z zamówienia wygrywa z kontraktem, waluta i jednostka też", () => {
    const row = contractorRowSummary(
      contractor({
        orders: [
          order({
            id: 6,
            rate_unit: "daily",
            rate_candidate: 1000,
            rate_candidate_currency: "EUR",
            rate_client: 1450,
            rate_client_currency: "EUR",
          }),
        ],
      }),
      TODAY,
    );
    expect(row.costLabel).toBe("1000 EUR/MD");
    expect(row.revenueLabel).toBe("1450 EUR/MD");
  });

  it("szkic zamówienia bez stawki przychodowej: stan „Szkic zamówienia”, przychód pusty", () => {
    const row = contractorRowSummary(
      contractor({ orders: [order({ id: 7, status: "draft", rate_client: null })] }),
      TODAY,
    );
    expect(row.state.kind).toBe("draft_order");
    expect(row.revenueLabel).toBeNull();
  });
});

describe("canTerminateContractor (re-eksport reguły)", () => {
  it("chowa wyłącznie stany terminalne", () => {
    expect(canTerminateContractor("draft")).toBe(true);
    expect(canTerminateContractor("ended")).toBe(false);
    expect(canTerminateContractor("void")).toBe(false);
  });
});
