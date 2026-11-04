// Wspólne fikcyjne dane testów zakładki „Faktury z KSeF” — repo jest publiczne.

import type { KsefInvoice, KsefStatus } from "@/lib/api/hr-ksef";

export function invoice(overrides: Partial<KsefInvoice> = {}): KsefInvoice {
  return {
    id: 1,
    source: "ksef",
    ksef_number: "7777777777-20261105-0B91E4C2A7D8-1F",
    ksef_acquired_at: "2026-11-05T10:02:00.000+00:00",
    seller_nip: "7777777777",
    seller_name: "Anna Przykładowa Consulting",
    user: { id: 7, name: "Anna Przykładowa" },
    invoice_number: "FV/27/10/26",
    invoice_kind: "original",
    corrects_invoice_id: null,
    corrected_ksef_number: null,
    issue_date: "2026-11-05",
    sale_date: "2026-10-31",
    period: "2026-10",
    currency: "PLN",
    net_amount: "14540.00",
    vat_amount: "3344.20",
    gross_amount: "17884.20",
    items_count: 2,
    match_status: "matched",
    settlement: { id: 3, status: "mismatch", expected_amount: "14420.00", year: 2026, month: 10 },
    has_pdf: false,
    fetched_at: "2026-11-05T11:00:00.000+00:00",
    ...overrides,
  };
}

export const STATUS: KsefStatus = {
  mode: "test",
  mode_label: "testowe MF",
  enabled: true,
  health: "healthy",
  disabled_reason: null,
  disabled_text: null,
  context_nip: "9876543210",
  token_configured: true,
  cursor: "2026-11-17T12:00:00.000+00:00",
  last_run_at: "2026-11-17T13:00:00.000+00:00",
  last_run_kind: "auto",
  last_success_at: "2026-11-17T13:00:00.000+00:00",
  last_error: null,
  last_error_text: null,
  last_error_at: null,
  blocked_until: null,
  last_counts: { saved: 1, skipped: 4 },
  pending: 0,
  problems: [],
  white_list: {
    mode: "simulate",
    day: "2026-11-17",
    used: { search: 2, check: 1 },
    limits: { search: 100, check: 100 },
  },
};
