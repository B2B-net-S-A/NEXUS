// Fikcyjny wiersz listy „Dla Finansów” do testów zakładki „Przelewy”.

import type { PayableRow } from "@/lib/api/hr-payments";

export function payableRow(overrides: Partial<PayableRow> = {}): PayableRow {
  return {
    settlement_id: 1,
    user_id: 7,
    name: "Ola Nowak",
    employment_type: "b2b",
    form_label: "B2B",
    year: 2026,
    month: 10,
    currency: "PLN",
    expected_amount: "17160.00",
    amount_basis: "net",
    amount_to_pay: "21106.80",
    due_on: "2026-11-18",
    overdue: false,
    approved_at: "2026-11-05T09:00:00+01:00",
    approved_by_name: "Filip Finansowy",
    title: "FV 10/2026 1234563218-20261104-5F2A9C0D71B3-4E",
    invoices: [
      {
        id: 3,
        invoice_number: "FV 10/2026",
        ksef_number: "1234563218-20261104-5F2A9C0D71B3-4E",
        gross_amount: "21106.80",
        kind: "original",
      },
    ],
    nip: "1234563218",
    registry_name: "Nowak Recruitment Ola Nowak",
    account_last4: "4521",
    account_source: "white_list",
    account_checked_at: "2026-10-17T10:00:00+02:00",
    white_list_override: false,
    batch_key: null,
    ...overrides,
  };
}
