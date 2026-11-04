"use client";

/**
 * Harness wizualny sekcji „Zakończone" zamówienia MD (ticket 6, 09.2026;
 * wersja B 29.09.2026 — tabela z panelem).
 *
 * Renderuje PRODUKCYJNĄ tabelę zamówień z panelem osoby na zamrożonych danych
 * (zasiany cache, zero zapytań — dlatego stoi w `PUBLIC_PATHS`). Wszystkie
 * stany osoby zakończonej obok siebie: czeka na decyzję, czeka decyzja o puli
 * MD, zostawiony jako historia (umowa rozwiązana), zastąpiony. „Zostaw jako
 * historię" działa na stanie lokalnym, żeby było widać wiersz po decyzji.
 * `?order=<id osoby>` otwiera od razu panel tej osoby. Nazwiska, numery
 * i kwoty są zmyślone (repo jest publiczne).
 */

import { useEffect, useMemo, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { OrderGroupsHarness, seedOrderGroupPanels } from "@/app/preview/order-groups-harness";
import type {
  OrderGroupRead,
  OrderLineRead,
  OrderOffboardingCaseRead,
} from "@/lib/api/orderGroups";

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 30,
    contract_id: 300,
    candidate_id: 5,
    consultant_name: "Jan Kowalski",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-05-01",
    end_date: null,
    rate_cost: 800,
    rate_revenue: 1000,
    input_value: 60,
    input_mode: "md",
    md_total: 60,
    md_remaining: 21.5,
    md_manual_adjustment: 0,
    md_used: 38.5,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    md_optional_total: null,
    md_base_used: null,
    md_optional_used: null,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
    contract_type: "b2b",
    agreement_termination_mode: null,
    agreement_last_day: null,
    ...overrides,
  };
}

const PENDING_POOL: OrderOffboardingCaseRead = {
  id: 71,
  contract_id: 302,
  order_id: 3,
  order_group_id: 30,
  client_id: 18,
  effective_date: "2026-08-31",
  status: "pending",
  version: 1,
  uses_shared_md_pool: false,
  remaining_md_snapshot: 3.7,
  rate_cost_snapshot: 800,
  rate_revenue_snapshot: 1000,
  currency_snapshot: "PLN",
  order_number_snapshot: "4599099001",
  resolution: null,
  target_order_id: null,
  rate_basis: null,
  resolution_payload: null,
  resolved_at: null,
  resolved_by_user_id: null,
  created_by_user_id: null,
  created_at: "2026-08-31T10:00:00Z",
  updated_at: "2026-08-31T10:00:00Z",
};

const INITIAL_LINES: OrderLineRead[] = [
  line(),
  line({
    id: 6,
    contract_id: 306,
    consultant_name: "Ewa Następna",
    start_date: "2026-09-01",
    md_total: 40,
    md_remaining: 36,
    md_used: 4,
    predecessor_order_id: 5,
    predecessor_consultant_name: "Tomasz Zastąpiony",
  }),
  // Ticket 6: zakończył, dodany ręcznie, 25,45 MD — czeka na decyzję.
  line({
    id: 2,
    contract_id: 302,
    consultant_name: "Karol Przykładowy",
    status: "completed",
    is_active: false,
    start_date: "2026-05-01",
    end_date: "2026-08-31",
    cooperation_ended_on: "2026-08-31",
    md_total: 31.413,
    md_remaining: 5.963,
    md_used: 25.45,
    origin: "manual",
    added_at: "2026-08-21T09:00:00Z",
    added_by_name: "Anna Wzorcowa",
  }),
  // Czeka decyzja o pozostałej puli MD (sprawa offboardingu).
  line({
    id: 3,
    contract_id: 303,
    consultant_name: "Paweł Pulowy",
    status: "completed",
    is_active: false,
    start_date: "2026-05-01",
    end_date: "2026-08-31",
    cooperation_ended_on: "2026-08-31",
    md_total: 20,
    md_remaining: 3.7,
    md_used: 16.3,
    offboarding_case: PENDING_POOL,
    agreement_termination_mode: "notice",
    agreement_last_day: "2026-09-30",
  }),
  // Po decyzji: umowa rozwiązana porozumieniem stron.
  line({
    id: 4,
    contract_id: 304,
    consultant_name: "Maria Historyczna",
    status: "completed",
    is_active: false,
    start_date: "2026-03-01",
    end_date: "2026-07-31",
    cooperation_ended_on: "2026-07-31",
    md_total: 40,
    md_remaining: 0,
    md_used: 40,
    history_kept_at: "2026-08-02T09:00:00Z",
    history_kept_by_name: "Anna Wzorcowa",
    agreement_termination_mode: "mutual_agreement",
    agreement_last_day: "2026-07-31",
  }),
  // Zastąpiony — decyzja zapadła (następca w aktywnej obsadzie).
  line({
    id: 5,
    contract_id: 305,
    consultant_name: "Tomasz Zastąpiony",
    status: "completed",
    is_active: false,
    start_date: "2026-03-01",
    end_date: "2026-08-31",
    cooperation_ended_on: "2026-08-31",
    md_total: 50,
    md_remaining: 10,
    md_used: 40,
    replaced_by_order_id: 6,
    replaced_by_consultant_name: "Ewa Następna",
    replaced_by_kind: "swap",
    replaced_by_start_date: "2026-09-01",
    replaced_by_md: 10,
  }),
];

function group(lines: OrderLineRead[]): OrderGroupRead {
  return {
    id: 30,
    client_id: 18,
    order_number: "4599099001",
    start_date: "2026-03-01",
    end_date: null,
    notes: null,
    created_at: "2026-03-01T10:00:00Z",
    status: "active",
    status_label: "Aktywne",
    closure_date: null,
    closure_reason: null,
    is_cost_based: false,
    is_md_budget_based: false,
    budget_amount: null,
    budget_used: null,
    budget_remaining: null,
    budget_manual_adjustment: null,
    md_budget_total: null,
    md_budget_used: null,
    md_budget_remaining: null,
    md_budget_manual_adjustment: null,
    executive_contract: null,
    md_positions_total: null,
    md_used_total: null,
    contract_value_pln: null,
    used_value_pln: null,
    predecessor_group_id: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    file_uploaded_at: null,
    can_add_consultant: true,
    lines,
    active_consultants: lines.filter((item) => item.is_active).length,
    event_count: 0,
    future_orders: [],
  };
}

/** `?order=<id>` — panel osoby od wejścia (zrzuty ekranu). */
function initialLineId(): number | null {
  if (typeof window === "undefined") return null;
  const value = Number(new URLSearchParams(window.location.search).get("order"));
  return INITIAL_LINES.some((item) => item.id === value) ? value : null;
}

export default function OrderEndedLinesPreview() {
  const [lines, setLines] = useState(INITIAL_LINES);
  const [lastAction, setLastAction] = useState<string | null>(null);
  // Adres czytany po zamontowaniu — SSR nie zna `window`, a różny stan
  // pierwszego renderu dałby błąd hydracji.
  const [lineId, setLineId] = useState<number | null>(null);
  useEffect(() => setLineId(initialLineId()), []);
  const current = group(lines);

  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: Infinity,
          retry: false,
          queryFn: () => Promise.reject(new Error("podgląd: brak zasianych danych")),
        },
      },
    });
    seedOrderGroupPanels(qc, 18, [group(INITIAL_LINES)]);
    return qc;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto flex max-w-6xl flex-col gap-6 p-4 sm:p-8">
        <header>
          <h1 className="text-lg font-semibold">
            Harness — „Zakończone” w zamówieniu MD
          </h1>
          <p className="text-sm text-muted-foreground">
            Publiczny podgląd na zamrożonych danych. Zero zapytań do API. Kliknij
            wiersz, żeby otworzyć panel.
            {lastAction ? ` Ostatnia akcja: ${lastAction}.` : ""}
          </p>
        </header>
        <OrderGroupsHarness
          key={lineId ?? "brak"}
          clientId={18}
          groups={[current]}
          initialSelection={lineId ? { kind: "line", groupId: 30, lineId } : null}
          onAction={setLastAction}
          onKeepHistory={(_g, target) =>
            setLines((prev) =>
              prev.map((item) =>
                item.id === target.id
                  ? {
                      ...item,
                      history_kept_at: "2026-09-25T09:00:00Z",
                      history_kept_by_name: "Ty",
                    }
                  : item,
              ),
            )
          }
        />
      </main>
    </QueryClientProvider>
  );
}
