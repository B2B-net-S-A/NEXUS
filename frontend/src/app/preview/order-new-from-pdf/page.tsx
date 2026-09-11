"use client";

/**
 * Harness designu kart konsultantów w oknie „Nowe zamówienie" (ticket 09.2026).
 *
 * Renderuje PRAWDZIWE `OrderPlanLineCard` z kart zbudowanych przez tę samą
 * funkcję co okno (`draftsFromPlan`) — bez sieci: cache pickera konsultanta
 * jest zasiany z góry (`setQueryData` + `staleTime: Infinity`), więc żaden
 * `queryFn` się nie odpala. To warunek wejścia do `PUBLIC_PATHS` w
 * middleware.ts — stronę otwiera nightly Playwright bez sesji.
 *
 * Dwie sekcje: przykład z ticketu (PDF BIK: Suwała + Łaski) oraz cztery
 * warianty dopasowania obok siebie. Ich różnice łatwo zepsuć niezauważenie:
 * żółta karta nie może wyglądać jak zielona, a „dwie osoby" nie może
 * wyglądać jak „brak dopasowania" — to dwie różne decyzje Delivery Leada.
 */

import { useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { OrderGroupFormModal } from "@/components/client-profile/orders/OrderGroupFormModal";
import { OrderPlanLineCard } from "@/components/client-profile/orders/OrderPlanLineCard";
import type { OrderType } from "@/lib/api/dlPortal";
import type {
  OrderGroupExtraction,
  OrderPlanContract,
  OrderPlanLine,
} from "@/lib/api/orderGroups";
import {
  draftsFromPlan,
  duplicatePersonKeys,
  lineIssues,
  type OrderLineDraft,
  type OrderPlanContext,
} from "@/lib/order-plan";

const CLIENT_ID = 18;

function contract(overrides: Partial<OrderPlanContract>): OrderPlanContract {
  return {
    contract_id: 1,
    candidate_id: 1,
    contractor_name: "",
    status: "active",
    start_date: "2025-06-01",
    end_date: null,
    rate_cost: 148.75,
    rate_cost_unit: "daily",
    rate_cost_currency: "PLN",
    rate_cost_rate_to_pln: 1,
    rate_cost_per_md_pln: 148.75,
    ...overrides,
  };
}

function line(overrides: Partial<OrderPlanLine>): OrderPlanLine {
  return {
    ordinal: 1,
    document_name: null,
    position_label: null,
    rate_revenue: 1080,
    rate_revenue_unit: "day",
    rate_revenue_gross: null,
    md_total: 35,
    start_date: null,
    end_date: null,
    match_status: "auto",
    match_reason: "Zapis identyczny z dokumentem",
    contract: null,
    options: [],
    nearest_names: [],
    warnings: [],
    ...overrides,
  };
}

function extraction(lines: OrderPlanLine[]): OrderGroupExtraction {
  return {
    order_number: "4500030845",
    start_date: "2026-09-03",
    end_date: null,
    total_value: 91560,
    currency: "PLN",
    md_total: null,
    suggested_order_type: "md",
    client_policy: null,
    consultant_ref: null,
    title_needs_review: false,
    document_incomplete: false,
    uncertain: false,
    uncertain_reasons: [],
    lines,
  };
}

const BIK = extraction([
  line({
    ordinal: 1,
    document_name: "Krzysztof Suwała",
    position_label: "10",
    contract: contract({ contract_id: 11, candidate_id: 101, contractor_name: "Krzysztof Suwała" }),
  }),
  line({
    ordinal: 2,
    document_name: "Paweł Łaski",
    position_label: "20",
    rate_revenue: 1280,
    md_total: 42,
    match_status: "confirm",
    match_reason:
      "W kontrakcie przed imieniem i nazwiskiem jest dopisek „Active” — rdzeń nazwy się zgadza — potwierdź, że to ta sama osoba",
    contract: contract({
      contract_id: 12,
      candidate_id: 102,
      contractor_name: "Active Paweł Łaski",
      rate_cost: 160,
    }),
  }),
]);

const VARIANTS = extraction([
  line({
    ordinal: 1,
    document_name: "Paweł Łaski",
    position_label: "10",
    contract: contract({ contract_id: 21, candidate_id: 201, contractor_name: "Pawel Laski" }),
  }),
  line({
    ordinal: 2,
    document_name: "Jan Kowalski",
    position_label: "20",
    match_status: "confirm",
    match_reason:
      "W kontrakcie przed imieniem i nazwiskiem jest dopisek „Active” — rdzeń nazwy się zgadza — potwierdź, że to ta sama osoba",
    contract: contract({ contract_id: 22, candidate_id: 202, contractor_name: "Active Jan Kowalski" }),
  }),
  line({
    ordinal: 3,
    document_name: "Anna Nowak",
    position_label: "30",
    match_status: "ambiguous",
    match_reason:
      "Znaleziono 2 różne osoby o tym imieniu i nazwisku u tego klienta — system nie zgaduje, wskaż właściwą osobę po numerze kontraktu lub dacie rozpoczęcia",
    options: [
      contract({ contract_id: 31, candidate_id: 301, contractor_name: "Anna Nowak", start_date: "2024-03-01" }),
      contract({ contract_id: 32, candidate_id: 302, contractor_name: "Anna Nowak", start_date: "2026-02-01" }),
    ],
  }),
  line({
    ordinal: 4,
    document_name: "Jan Kowalczyk",
    position_label: "40",
    match_status: "none",
    match_reason:
      "Brak kontraktu z tym imieniem i nazwiskiem u tego klienta — system nie koryguje literówek ani nie zgaduje podobieństwa",
    nearest_names: ["Jan Kowalski"],
  }),
]);

// Zlecenie wykonawcze kosztowe (kształt dokumentu Polkomtela, dane zmyślone):
// stawki z wierszy tabeli, bez liczby MD; osoba z zakończoną współpracą i osoba,
// której nie ma w systemie — obie z jawnym wyborem zamiast cichego błędu.
const COST_ORDER: OrderGroupExtraction = {
  ...extraction([
    line({
      ordinal: 1,
      document_name: "Nowak-Testowa Ewa",
      rate_revenue: 840,
      md_total: null,
      match_status: "confirm",
      match_reason:
        "Imię i nazwisko zapisano w odwrotnej kolejności — potwierdź, że to ta sama osoba",
      contract: contract({ contract_id: 41, candidate_id: 401, contractor_name: "Ewa Nowak-Testowa" }),
    }),
    line({
      ordinal: 2,
      document_name: "Odeszły Marian",
      rate_revenue: 1280,
      md_total: null,
      match_status: "inactive",
      match_reason:
        "Imię i nazwisko zapisano w odwrotnej kolejności; „Odeszły Marian” nie ma już aktywnej współpracy u tego klienta (kontrakt zakończony 12.08.2026). Zdecyduj: zostaw tę osobę na zamówieniu jako zapis historyczny, wznów współpracę, zastąp ją inną osobą albo usuń z zamówienia",
      contract: contract({
        contract_id: 42,
        candidate_id: 402,
        contractor_name: "Marian Odeszły",
        status: "ended",
        end_date: "2026-08-12",
      }),
    }),
    line({
      ordinal: 3,
      document_name: "Nieobecny Zenon",
      rate_revenue: 1100,
      md_total: null,
      match_status: "none",
      match_reason:
        "Nie znaleziono „Nieobecny Zenon” w systemie — brak kontraktu z tym imieniem i nazwiskiem u tego klienta (system nie koryguje literówek ani nie zgaduje podobieństwa). Wskaż tę osobę ręcznie, zastąp ją kimś innym albo usuń z zamówienia",
    }),
  ]),
  order_number: "SAP 4500987654",
  start_date: "2026-03-30",
  total_value: 40000,
};

const CONTEXT: OrderPlanContext = {
  orderType: "md",
  sharedMd: false,
  groupStart: "2026-09-03",
  groupEnd: null,
};

const COST_CONTEXT: OrderPlanContext = {
  orderType: "cost",
  sharedMd: false,
  groupStart: "2026-03-30",
  groupEnd: null,
};

function Cards({
  plan,
  title,
  context = CONTEXT,
}: {
  plan: OrderGroupExtraction;
  title: string;
  context?: OrderPlanContext;
}) {
  const [lines, setLines] = useState<OrderLineDraft[]>(() => draftsFromPlan(plan));
  const duplicated = duplicatePersonKeys(lines);
  const ready = lines.filter((item) => lineIssues(item, context).length === 0).length;
  return (
    <section className="space-y-3 rounded-xl border border-border bg-background p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-foreground">{title}</h2>
      {lines.map((item) => (
        <OrderPlanLineCard
          key={item.key}
          clientId={CLIENT_ID}
          draft={item}
          showMd={context.orderType === "md" && !context.sharedMd}
          duplicated={duplicated.has(item.key)}
          issues={lineIssues(item, context)}
          onChange={(next) =>
            setLines((current) => current.map((row) => (row.key === item.key ? next : row)))
          }
          onRemove={() => setLines((current) => current.filter((row) => row.key !== item.key))}
        />
      ))}
      <p className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        {ready} z {lines.length} pozycji gotowe do zapisania
      </p>
    </section>
  );
}

export default function OrderNewFromPdfPreview() {
  // Okno otwiera się dopiero na kliknięcie: zamknięte nie woła niczego, a
  // „Zczytaj…" bez sesji pokazuje gałąź błędu odczytu — celowo, jak w
  // harnessie pickera.
  const [modalOpen, setModalOpen] = useState(false);
  const [orderType, setOrderType] = useState<Exclude<OrderType, "periodic">>("md");
  const queryClient = useMemo(() => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    client.setQueryData(["order-line-consultant-options", CLIENT_ID, ""], {
      options: [
        {
          candidate_id: 202,
          contract_id: 22,
          full_name: "Jan Kowalski",
          first_name: "Jan",
          last_name: "Kowalski",
          source: "client_recruitment",
          source_label: "Rekrutacja u klienta",
          job_title: "Analityk",
          suggested_rate_cost: 150,
          has_different_client_contract_rates: false,
        },
      ],
      total: 1,
    });
    return client;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto flex max-w-2xl flex-col gap-6 bg-muted/20 p-6">
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          className="self-start rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
        >
          Otwórz okno „Nowe zamówienie"
        </button>
        <OrderGroupFormModal
          open={modalOpen}
          onOpenChange={setModalOpen}
          group={null}
          clientId={CLIENT_ID}
          orderType={orderType}
          onOrderTypeChange={(next) => {
            if (next !== "periodic") setOrderType(next);
          }}
          allowedOrderTypes={["periodic", "cost", "md"]}
          submitting={false}
          error={null}
          onSubmit={() => setModalOpen(false)}
          onDeleteFile={async () => undefined}
        />
        <Cards plan={BIK} title="Zamówienie BIK 4500030845 — dwie pozycje z PDF-a" />
        <Cards plan={VARIANTS} title="Warianty dopasowania" />
        <Cards
          plan={COST_ORDER}
          context={COST_CONTEXT}
          title="Zlecenie wykonawcze SAP 4500987654 — kosztowe, kwota 40 000 zł, bez MD"
        />
      </main>
    </QueryClientProvider>
  );
}
