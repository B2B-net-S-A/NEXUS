"use client";

/**
 * Harness designu kolejki zamówień z maila — WYŁĄCZNIE mocki, zero wywołań API
 * (warunek `PUBLIC_PATHS` w middleware.ts). Renderuje ten sam
 * `OrderMailQueueView`, którego używa ekran produkcyjny.
 *
 * Dokumenty obok siebie, bo różnicę między nimi łatwo zepsuć niezauważenie:
 * werdykt „automat: pewne" (tryb cienia), „wymaga weryfikacji" z powodami
 * bramki i kwotami ZREDAGOWANYMI (rola bez finansów widzi „—"), rewizja
 * istniejącego zamówienia, nowa osoba z niepewnym odczytem i powrót po
 * przerwie z imiennikiem (punkty „Do sprawdzenia”, 20.11.2026), a na
 * zakładkach „Nierozpoznane” i „Nieudane” po jednym wpisie.
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
    client_policy: "Bank Kappa",
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
    client_name: "Bank Omega S.A.", client_policy: "Bank Omega", subject: "Zamówienie nr 9/97/2031/BL", attachment_name: "3-07-2031-BL.pdf",
    gate_reasons: ["„Szkicowa Barbara”: Dopasowanie z literówką — potwierdź osobę", "„Fikcyjna Aleksandra”: brak żywego (active/ending) kontraktu — automat nie wskrzesza"],
    can_apply: false,
    extraction: {
      title: "9/97/2031/BL", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: null, currency: "PLN", uncertain: false, uncertain_reasons: [], source: "claude",
      consultant_rows: [
        { consultant_name: "Wzorowy Marcin", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", uncertain: false, uncertain_reason: null },
        { consultant_name: "Szkicowa Barbara", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", uncertain: false, uncertain_reason: null },
        { consultant_name: "Fikcyjna Aleksandra", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", uncertain: false, uncertain_reason: null },
      ],
    },
    proposal: {
      client_id: 2, order_number: "9/97/2031/BL", is_group_client: false, blocking: [],
      rows: [
        { row_index: 0, row_name: "Wzorowy Marcin", action: "new", candidate_id: 1, contract_id: 2, target_order_id: null, title: "9/97/2031/BL", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", reasons: [] },
        { row_index: 1, row_name: "Szkicowa Barbara", action: "new", candidate_id: 3, contract_id: 4, target_order_id: null, title: "9/97/2031/BL", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", reasons: [] },
        { row_index: 2, row_name: "Fikcyjna Aleksandra", action: "skip", candidate_id: null, contract_id: null, target_order_id: null, title: "9/97/2031/BL", start_date: "2031-07-01", end_date: "2031-08-31", rate_client: null, rate_unit: "day", md_total: "43", reasons: ["Osoba bez kontraktu do zapisu u tego klienta"] },
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
  // 27.10.2026: przedłużenie z nową stawką, które zaczyna się przed końcem
  // obecnego zamówienia — „było … (#70)” pod stawką i wybór, co zrobić z #70.
  doc(5, {
    client_name: "Bank Delta S.A.", client_policy: "Bank Delta", subject: "Zamówienie 10/2031", attachment_name: "10-2031.pdf",
    gate_reasons: [
      "„Jan Przedłużony”: przy przedłużeniu zmienia się stawka do klienta: 120 zł/h → 138 zł/h (+15%) względem zamówienia #70 — potwierdź, że klient przyjął nową stawkę",
      "„Jan Przedłużony”: Nowe zamówienie zaczyna się 01.12.2031, a #70 (9/2031) trwa do 31.12.2031 — wybierz, czy skrócić #70, czy zacząć nowe po nim",
    ],
    extraction: {
      title: "10/2031", start_date: "2031-12-01", end_date: "2032-05-01", rate_client: "138.00", rate_unit: "hour", md_total: null, currency: "PLN", uncertain: false, uncertain_reasons: [], source: "claude",
      consultant_rows: [{ consultant_name: "Jan Przedłużony", start_date: "2031-12-01", end_date: "2032-05-01", rate_client: "138.00", rate_unit: "hour", md_total: null, uncertain: false, uncertain_reason: null }],
    },
    proposal: {
      client_id: 5, order_number: "10/2031", is_group_client: false, blocking: [],
      rows: [{
        row_index: 0, row_name: "Jan Przedłużony", action: "overlap", candidate_id: 13, contract_id: 23, target_order_id: 70, title: "10/2031",
        start_date: "2031-12-01", end_date: "2032-05-01", rate_client: "138.00", rate_unit: "hour", md_total: null,
        reasons: ["Nowe zamówienie zaczyna się 01.12.2031, a #70 (9/2031) trwa do 31.12.2031 — wybierz, czy skrócić #70, czy zacząć nowe po nim"],
        previous_order_id: 70, previous_order_title: "9/2031", previous_rate_client: "120.000", previous_rate_unit: "hour",
        previous_start_date: "2031-07-01", previous_end_date: "2031-12-31",
        overlap_options: ["trim_previous", "start_after"], overlap_trim_end: "2031-11-30", overlap_start_after: "2032-01-01",
      }],
    },
  }),
  doc(3, {
    client_name: "Doradztwo Przykładowe", client_policy: null, identification_method: "registry_id", subject: "Work Order WO-0000999 Rev. 1", attachment_name: "Work Order - Fieldglass.pdf",
    gate_reasons: ["Klient nie ma własnej polityki odczytu", "„Wzorcowy, Maciej”: revision — Zamówienie o tym numerze już istnieje (#88, 2031-07-01 – 2031-08-31) — porównaj"],
    proposal: {
      client_id: 3, order_number: "WO-0000999", is_group_client: false, blocking: [],
      rows: [{ row_index: 0, row_name: "Wzorcowy, Maciej", action: "revision", candidate_id: 7, contract_id: 9, target_order_id: 88, title: "WO-0000999", start_date: "2031-09-01", end_date: "2031-12-31", rate_client: "220.00", rate_unit: "hour", md_total: null, reasons: ["Zamówienie o tym numerze już istnieje (#88, 2031-07-01 – 2031-08-31) — porównaj"] }],
    },
  }),
  // 20.11.2026: nowa osoba bez umowy i niepewny odczyt — dwa punkty „Do
  // sprawdzenia”, uwagi odczytu zwinięte, zdanie o automacie pod listą.
  doc(8, {
    client_name: "Bank Lambda S.A.", client_policy: "Bank Lambda", sender_email: "jan.nadawca@bank-lambda.example",
    subject: "Zamówienie 2031/77 — administrator baz danych", attachment_name: "2031-77.pdf",
    gate_reasons: [
      "„Zenon Przykładowy”: nie ma jej wśród konsultantów tego klienta ani w bazie — zamówienie czeka na podpisaną umowę B2B",
      "Odczyt niepewny: Niejasny fragment 'Przykładowa Warszawa' - niepewne, czy to osobny konsultant czy część adresu",
      "Odczyt niepewny: „Przykładowa Warszawa”: pozycja z odczytu modelu nie ma wiersza w tabeli Consultant(s) PDF — sprawdź",
    ],
    document_meta: { page_count: 3, ocr_used: false, ocr_capped: false, recheck: { attempts: 16, category: "other", last_at: "2031-03-03T16:25:00Z" } },
    extraction: {
      title: "2031/77", start_date: "2031-12-01", end_date: "2032-03-31", rate_client: "160.00", rate_unit: "hour", md_total: null, currency: "PLN", uncertain: true,
      uncertain_reasons: [], source: "claude",
      consultant_rows: [{ consultant_name: "Zenon Przykładowy", start_date: "2031-12-01", end_date: "2032-03-31", rate_client: "160.00", rate_unit: "hour", md_total: null, uncertain: false, uncertain_reason: null }],
    },
    proposal: {
      client_id: 8, order_number: "2031/77", is_group_client: false, blocking: [],
      rows: [{ row_index: 0, row_name: "Zenon Przykładowy", action: "new_draft", candidate_id: null, contract_id: null, target_order_id: null, title: "2031/77", start_date: "2031-12-01", end_date: "2032-03-31", rate_client: "160.00", rate_unit: "hour", md_total: null, reasons: [], existing_person_ids: [] }],
    },
  }),
  // Powrót po przerwie z imiennikiem w bazie: jeden powód bramki, dwa punkty.
  doc(9, {
    client_name: "Bank Lambda S.A.", client_policy: "Bank Lambda", subject: "Zamówienie 2031/81", attachment_name: "2031-81.pdf",
    gate_reasons: [
      "„Wiesław Powracający”: Powrót po 1 dniu od zakończenia poprzedniego zamówienia; W bazie jest też inna osoba o tym imieniu i nazwisku (#9001) — potwierdź, że to powrót tej samej osoby, i zastosuj ręcznie",
    ],
    document_meta: { page_count: 3, ocr_used: false, ocr_capped: false, recheck: { attempts: 150, category: "other", last_at: "2031-03-03T16:26:00Z" } },
    extraction: {
      title: "2031/81", start_date: "2031-11-01", end_date: "2032-05-31", rate_client: "175.00", rate_unit: "hour", md_total: null, currency: "PLN", uncertain: false,
      uncertain_reasons: [], source: "claude",
      consultant_rows: [{ consultant_name: "Wiesław Powracający", start_date: "2031-11-01", end_date: "2032-05-31", rate_client: "175.00", rate_unit: "hour", md_total: null, uncertain: false, uncertain_reason: null }],
    },
    proposal: {
      client_id: 8, order_number: "2031/81", is_group_client: false, blocking: [],
      rows: [{
        row_index: 0, row_name: "Wiesław Powracający", action: "reactivate", candidate_id: 9000, contract_id: 135, target_order_id: 329, title: "2031/81",
        start_date: "2031-11-01", end_date: "2032-05-31", rate_client: "175.00", rate_unit: "hour", md_total: null,
        reasons: ["Powrót po 1 dniu od zakończenia poprzedniego zamówienia", "W bazie jest też inna osoba o tym imieniu i nazwisku (#9001) — potwierdź, że to powrót tej samej osoby, i zastosuj ręcznie"],
        existing_person_ids: [9001], previous_rate_client: "175.000", previous_rate_unit: "hour",
      }],
    },
  }),
];

/** Zakładka „Nierozpoznane”: mail bez rozpoznanego klienta (odrzuca admin). */
const UNRECOGNIZED: OrderMailDocument[] = [
  doc(6, {
    outcome: "unrecognized_client", client_id: null, client_name: null, client_policy: null, identification_method: null,
    identification_reason: "Żaden numer rejestrowy z dokumentu nie pasuje do klienta w NEXUSIE.",
    sender_email: "biuro@firma-nieznana.example", subject: "Zamówienie prac", attachment_name: "zamowienie-prac.pdf",
    gate_verdict: null, gate_reasons: [], can_apply: false, can_dismiss: true, proposal: null,
    document_meta: { page_count: 1, ocr_used: false, ocr_capped: false, recheck: { attempts: 0, category: "unrecognized", last_at: "2031-03-03T16:26:00Z" } },
    extraction: {
      title: "ZP/0042/2031", start_date: "2031-11-01", end_date: "2032-04-30", rate_client: null, rate_unit: null, md_total: null, currency: "PLN", uncertain: true,
      uncertain_reasons: ["Brak jawnej stawki za dzień albo godzinę."], source: "claude",
      consultant_rows: [{ consultant_name: "Krystyna Fikcyjna", start_date: "2031-11-01", end_date: "2032-04-30", rate_client: null, rate_unit: null, md_total: null, uncertain: true, uncertain_reason: "Tylko łączna wartość zamówienia." }],
    },
  }),
];

/** Zakładka „Nieudane”: błąd przetwarzania, system ponawia sam. */
const FAILED: OrderMailDocument[] = [
  doc(7, {
    outcome: "failed", gate_verdict: null, gate_reasons: [], can_apply: false, can_dismiss: true, proposal: null, extraction: null,
    error: "Błąd przetwarzania: przekroczony czas odczytu PDF", failed_retry_pending: true,
    document_meta: { failed_retry: { attempts: 1 } },
  }),
];

const ITEMS_BY_OUTCOME: Partial<Record<OrderMailOutcome, OrderMailDocument[]>> = {
  needs_review: ITEMS,
  unrecognized_client: UNRECOGNIZED,
  failed: FAILED,
};

/** Liczniki zakładek — tyle, ile wpisów ma każda lista harnessu. */
const COUNTS = { needs_review: ITEMS.length, auto_applied: 0, applied: 0, unrecognized_client: UNRECOGNIZED.length, failed: FAILED.length };

/**
 * Ostatnie sprawdzenie skrzynki — trzy liczby z ticketu plus przycisk „Pobierz".
 * „12 min temu” liczone przy renderze, nie przy wczytaniu modułu: serwer dev
 * trzyma moduł od startu, więc stała dawała inny wiek niż przeglądarka
 * i błąd hydratacji.
 */
function syncStatus(now: number): OrderMailSyncStatus {
  return {
    enabled: true,
    interval_minutes: 60,
    autoapply_enabled: false,
    running: false,
    started_at: "2031-03-03T08:02:00Z",
    interrupted: false,
    can_trigger: true,
    last_completed: {
      reason: "scheduled", started_at: "2031-03-03T08:02:00Z", finished_at: new Date(now - 12 * 60_000).toISOString(),
      status: "ok", error: null, messages: 4, new_messages: 2, attachments: 3, auto_applied: 1, needs_review: 1,
      unrecognized: 0, duplicates: 1, skipped_existing: 2, ignored_no_pdf: 0, ignored_sender: 0, failed: 0,
      rechecked: 3, recheck_applied: 1, recheck_held: 2, recheck_alerts: 1, errors: [],
    },
  };
}

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
        client_name: "Bank Sigma S.A.",
        order_number: "OIT/9901/2031/ITVM",
        people: ["Jan Kowalski"],
        outcome: "applied",
        category: null,
        reasons: [],
      },
      {
        document_id: 2,
        client_id: 7,
        client_name: "Bank Sigma S.A.",
        order_number: "OIT/9902/2031/ITVM",
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
        client_name: "Bank Północny Abp",
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

// Podgląd w harnessie czyta fikcyjny plik statyczny (ten sam co harness
// Finansów) — to nie jest wywołanie API.
async function loadStaticPdf(): Promise<Blob> {
  const response = await fetch("/preview/cv-search/cv-tekst.pdf");
  if (!response.ok) throw new Error("brak pliku");
  return response.blob();
}

export default function OrderMailPreviewPage() {
  const [outcome, setOutcome] = useState<OrderMailOutcome>("needs_review");
  const [selectedId, setSelectedId] = useState<number | null>(1);
  const [checking, setChecking] = useState(false);
  const [status] = useState(() => syncStatus(Date.now()));
  // `?empty=1` pokazuje sekcję historii bez wierszy, ale ze znacznikiem —
  // wariant „nic się nie zmieniło od tygodnia". Czytane w efekcie, nie przy
  // renderze: `window` nie istnieje przy SSR, a rozjazd wywala hydrację.
  const [emptyHistory, setEmptyHistory] = useState(false);
  useEffect(() => {
    setEmptyHistory(new URLSearchParams(window.location.search).has("empty"));
  }, []);
  const items = ITEMS_BY_OUTCOME[outcome] ?? [];
  return (
    // Ekran produkcyjny dostaje margines od powłoki; harness jej nie ma.
    <div className="p-4 sm:p-6">
    <OrderMailQueueView
      loadPdf={loadStaticPdf}
      counts={COUNTS}
      mailbox={{
        status,
        statusError: false,
        checking,
        checkError: null,
        // W harnessie „sprawdzanie" trwa 2 s i wraca do wyniku — sam wygląd stanu zajętego.
        onCheckNow: () => { setChecking(true); setTimeout(() => setChecking(false), 2000); },
      }}
      outcome={outcome}
      onOutcomeChange={(o) => {
        setOutcome(o);
        setSelectedId(null);
      }}
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
    </div>
  );
}
