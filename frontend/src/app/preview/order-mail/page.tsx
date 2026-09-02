"use client";

/**
 * Harness designu kolejki zamówień z maila — WYŁĄCZNIE mocki, zero wywołań API
 * (warunek `PUBLIC_PATHS` w middleware.ts). Renderuje ten sam
 * `OrderMailQueueView`, którego używa ekran produkcyjny.
 *
 * Trzy dokumenty obok siebie, bo różnicę między nimi łatwo zepsuć niezauważenie:
 * werdykt „automat: pewne" (tryb cienia), „wymaga weryfikacji" z powodami
 * bramki i kwotami ZREDAGOWANYMI (rola bez finansów widzi „—"), oraz rewizja
 * istniejącego zamówienia.
 */

import { useState } from "react";
import { OrderMailQueueView } from "@/components/order-mail/OrderMailQueue";
import type { OrderMailDocument, OrderMailOutcome } from "@/lib/api/orderMail";

function doc(id: number, over: Partial<OrderMailDocument>): OrderMailDocument {
  return {
    id,
    received_at: "2031-03-03T08:02:00Z",
    sender_email: "zamowienia@bank-a.example",
    subject: "Zamówienie nr 1830/2031",
    attachment_name: "Z_1830_2031.pdf",
    outcome: "needs_review",
    client_id: 1,
    client_name: "Bank A S.A.",
    identification_method: "registry_id",
    identification_reason: "Numer rejestrowy z dokumentu pasuje do jednego klienta.",
    client_policy: "PKO BP",
    gate_verdict: "review",
    gate_reasons: [],
    document_meta: { page_count: 1, ocr_used: false, ocr_capped: false },
    extraction: {
      title: "1830/2031", start_date: "2031-09-01", end_date: "2031-11-30", rate_client: "900.00",
      rate_unit: "day", md_total: "64", currency: "PLN", uncertain: false, uncertain_reasons: [], source: "claude",
      consultant_rows: [{ consultant_name: "Anna Przykładowa", start_date: "2031-09-01", end_date: "2031-11-30", rate_client: "900.00", rate_unit: "day", md_total: "64", uncertain: false, uncertain_reason: null }],
    },
    proposal: {
      client_id: 1, order_number: "1830/2031", is_group_client: false, blocking: [],
      rows: [{ row_index: 0, row_name: "Anna Przykładowa", action: "future", candidate_id: 10, contract_id: 20, target_order_id: null, title: "1830/2031", start_date: "2031-09-01", end_date: "2031-11-30", rate_client: "900.00", rate_unit: "day", md_total: "64", reasons: [] }],
    },
    applied_order_id: null, applied_at: null, reviewed_at: null, error: null, can_apply: true, has_file: true,
    ...over,
  };
}

const ITEMS: OrderMailDocument[] = [
  doc(1, { gate_verdict: "auto", gate_reasons: [] }),
  doc(2, {
    client_name: "VeloBank S.A.", client_policy: "VeloBank", subject: "Zamówienie nr 3/07/2031/BL", attachment_name: "3-07-2031-BL.pdf",
    gate_reasons: ["„Jęczeń Barbara”: Dopasowanie z literówką — potwierdź osobę", "„Likas Aleksandra”: brak żywego (active/ending) kontraktu — automat nie wskrzesza"],
    can_apply: false,
    extraction: {
      title: "3/07/2031/BL", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: null, currency: "PLN", uncertain: false, uncertain_reasons: [], source: "claude",
      consultant_rows: [
        { consultant_name: "Baczewski Marcin", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", uncertain: false, uncertain_reason: null },
        { consultant_name: "Jęczeń Barbara", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", uncertain: false, uncertain_reason: null },
        { consultant_name: "Likas Aleksandra", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", uncertain: false, uncertain_reason: null },
      ],
    },
    proposal: {
      client_id: 2, order_number: "3/07/2031/BL", is_group_client: false, blocking: [],
      rows: [
        { row_index: 0, row_name: "Baczewski Marcin", action: "new", candidate_id: 1, contract_id: 2, target_order_id: null, title: "3/07/2031/BL", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", reasons: [] },
        { row_index: 1, row_name: "Jęczeń Barbara", action: "new", candidate_id: 3, contract_id: 4, target_order_id: null, title: "3/07/2031/BL", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", reasons: [] },
        { row_index: 2, row_name: "Likas Aleksandra", action: "skip", candidate_id: null, contract_id: null, target_order_id: null, title: "3/07/2031/BL", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", reasons: ["Osoba bez kontraktu do zapisu u tego klienta"] },
      ],
    },
  }),
  doc(3, {
    client_name: "Ernst & Young", client_policy: null, identification_method: "registry_id", subject: "Work Order EYWO00016165 Rev. 13", attachment_name: "Work Order - Fieldglass.pdf",
    gate_reasons: ["Klient nie ma własnej polityki odczytu", "„Makarewicz, Maciej”: revision — Zamówienie o tym numerze już istnieje (#88, 2031-07-01 – 2031-08-31) — porównaj"],
    proposal: {
      client_id: 3, order_number: "EYWO00016165", is_group_client: false, blocking: [],
      rows: [{ row_index: 0, row_name: "Makarewicz, Maciej", action: "revision", candidate_id: 7, contract_id: 9, target_order_id: 88, title: "EYWO00016165", start_date: "2031-09-01", end_date: "2031-12-31", rate_client: "220.00", rate_unit: "hour", md_total: null, reasons: ["Zamówienie o tym numerze już istnieje (#88, 2031-07-01 – 2031-08-31) — porównaj"] }],
    },
  }),
];

export default function OrderMailPreviewPage() {
  const [outcome, setOutcome] = useState<OrderMailOutcome>("needs_review");
  const [selectedId, setSelectedId] = useState<number | null>(1);
  const items = outcome === "needs_review" ? ITEMS : [];
  return (
    <OrderMailQueueView
      outcome={outcome}
      onOutcomeChange={setOutcome}
      state="ready"
      items={items}
      total={items.length}
      selectedId={selectedId}
      onSelect={setSelectedId}
      onApply={() => undefined}
      onDismiss={() => undefined}
      onRetry={() => undefined}
      busy={false}
      applyError={null}
    />
  );
}
