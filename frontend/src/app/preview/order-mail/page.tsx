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

import { useEffect, useState } from "react";
import { OrderMailQueueView } from "@/components/order-mail/OrderMailQueue";
import type {
  OrderMailDocument,
  OrderMailOutcome,
  OrderMailRecheckRun,
  OrderMailRecheckWindow,
  OrderMailSyncStatus,
} from "@/lib/api/orderMail";

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
  // Ticket B (09.2026): zamówienie kosztowe z osobą, której współpraca się
  // zakończyła — decyzja w oknie zamówienia, „Zastosuj" wyłączone.
  doc(4, {
    client_name: "Operator Telekom S.A.", client_policy: "Operator", subject: "Zlecenie wykonawcze SAP 4500000777", attachment_name: "zlecenie.pdf",
    gate_reasons: ["„Marian Odchodzący”: „Marian Odchodzący” nie ma już aktywnej współpracy u tego klienta (kontrakt zakończony 12.02.2031). Zdecyduj: zostaw tę osobę na zamówieniu jako zapis historyczny, wznów współpracę, zastąp ją inną osobą albo usuń z zamówienia"],
    proposal: {
      client_id: 4, order_number: "SAP 4500000777", is_group_client: true, blocking: [],
      rows: [
        { row_index: 0, row_name: "Ewa Obecna", action: "new", candidate_id: 11, contract_id: 21, target_order_id: null, title: "SAP 4500000777", start_date: "2031-04-01", end_date: null, rate_client: "840.00", rate_unit: "day", md_total: null, order_type: "cost", reasons: [] },
        { row_index: 1, row_name: "Marian Odchodzący", action: "decide_person", candidate_id: 12, contract_id: 22, target_order_id: null, title: "SAP 4500000777", start_date: "2031-04-01", end_date: null, rate_client: "1280.00", rate_unit: "day", md_total: null, order_type: "cost", reasons: ["„Marian Odchodzący” nie ma już aktywnej współpracy u tego klienta (kontrakt zakończony 12.02.2031). Zdecyduj: zostaw tę osobę na zamówieniu jako zapis historyczny, wznów współpracę, zastąp ją inną osobą albo usuń z zamówienia"] },
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

/** Ostatnie sprawdzenie skrzynki — trzy liczby z ticketu plus przycisk „Pobierz". */
const SYNC_STATUS: OrderMailSyncStatus = {
  enabled: true,
  interval_minutes: 60,
  autoapply_enabled: false,
  running: false,
  started_at: "2031-03-03T08:02:00Z",
  interrupted: false,
  can_trigger: true,
  last_completed: {
    reason: "scheduled", started_at: "2031-03-03T08:02:00Z", finished_at: new Date(Date.now() - 12 * 60_000).toISOString(),
    status: "ok", error: null, messages: 4, new_messages: 2, attachments: 3, auto_applied: 1, needs_review: 1,
    unrecognized: 0, duplicates: 1, skipped_existing: 2, ignored_no_pdf: 0, ignored_sender: 0, failed: 0,
    rechecked: 3, recheck_applied: 1, recheck_held: 2, recheck_alerts: 1, errors: [],
  },
};

/** Trzy stany sekcji historii obok siebie: zapis, czekanie na podpis, eskalacja. */
const RECHECK_RUNS: OrderMailRecheckRun[] = [
  {
    id: 2,
    started_at: "2031-03-03T08:02:00Z",
    finished_at: "2031-03-03T08:02:40Z",
    trigger: "scheduled",
    checked: 3,
    applied: 1,
    held: 2,
    entries: [
      {
        document_id: 1,
        client_id: 7,
        client_name: "Bank Pocztowy S.A.",
        order_number: "OIT/0189/2031/ITVM",
        people: ["Jan Kowalski"],
        outcome: "applied",
        category: null,
        reasons: [],
      },
      {
        document_id: 2,
        client_id: 7,
        client_name: "Bank Pocztowy S.A.",
        order_number: "OIT/0190/2031/ITVM",
        people: ["Anna Nowa"],
        outcome: "held",
        category: "awaiting_contract",
        reasons: [
          "„Anna Nowa”: „Anna Nowa” (#812) jest już w bazie, ale bez trwającej współpracy u innego klienta. Potwierdź, że to ta sama osoba, i zastosuj ręcznie",
        ],
      },
      {
        document_id: 3,
        client_id: 9,
        client_name: "Nordea Bank Abp",
        order_number: "Call Off 4711",
        people: ["Piotr Zając"],
        outcome: "held",
        category: "other",
        reasons: ["„Piotr Zając”: stawka 12 hour poza pasmem 50–500"],
        alerted: true,
      },
    ],
  },
  {
    id: 1,
    started_at: "2031-03-03T07:02:00Z",
    finished_at: "2031-03-03T07:02:11Z",
    trigger: "manual",
    checked: 2,
    applied: 0,
    held: 2,
    entries: [],
  },
];

const RECHECK_WINDOW: OrderMailRecheckWindow = { start_hour: 8, end_hour: 18, enabled: true };

export default function OrderMailPreviewPage() {
  const [outcome, setOutcome] = useState<OrderMailOutcome>("needs_review");
  const [selectedId, setSelectedId] = useState<number | null>(1);
  const [checking, setChecking] = useState(false);
  // `?empty=1` pokazuje sekcję historii bez wierszy, ale ze znacznikiem —
  // wariant „nic się nie zmieniło od tygodnia". Czytane w efekcie, nie przy
  // renderze: `window` nie istnieje przy SSR, a rozjazd wywala hydrację.
  const [emptyHistory, setEmptyHistory] = useState(false);
  useEffect(() => {
    setEmptyHistory(new URLSearchParams(window.location.search).has("empty"));
  }, []);
  const items = outcome === "needs_review" ? ITEMS : [];
  return (
    <OrderMailQueueView
      mailbox={{
        status: SYNC_STATUS,
        statusError: false,
        checking,
        checkError: null,
        // W harnessie „sprawdzanie" trwa 2 s i wraca do wyniku — sam wygląd stanu zajętego.
        onCheckNow: () => { setChecking(true); setTimeout(() => setChecking(false), 2000); },
      }}
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
      recheck={{
        runs: emptyHistory ? [] : RECHECK_RUNS,
        state: "ready",
        scoped: false,
        // Bieg bez zmian nie zapisuje wiersza — znacznik jest wtedy jedynym
        // dowodem, że mechanizm żyje. Stąd wariant „pusta historia + znacznik".
        lastCheckedAt: "2031-03-03T08:02:00Z",
        unchangedRuns: emptyHistory ? 7 : 0,
        window: RECHECK_WINDOW,
        onRetry: () => undefined,
      }}
    />
  );
}
