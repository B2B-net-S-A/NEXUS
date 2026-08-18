"use client";

/**
 * Harness wizualny sekcji „Powiadomienia" w dashboardzie Delivery Leada.
 *
 * Renderuje PRODUKCYJNY `DlAlertsSection` na zasianym cache react-query
 * (`staleTime: Infinity`), więc żaden `queryFn` się nie odpala i strona nie
 * robi ani jednego zapytania — dzięki temu może stać w `PUBLIC_PATHS`.
 *
 * Sekcja czyta stan z jednego klucza `["dl-alerts", status]`, więc każdy stan
 * jest osobną instancją z własnym `QueryClientProvider`. Dzięki temu awaria,
 * pustka i dane stoją obok siebie i widać, że NIE wyglądają tak samo.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { DlAlertsSection } from "@/components/v2/dashboard/DlAlertsSection";
import type { DlAlertRead } from "@/lib/api/dlAlerts";

function alert(overrides: Partial<DlAlertRead> = {}): DlAlertRead {
  return {
    id: 1,
    alert_type: "cost_order_exhausted",
    alert_type_label: "Zamówienie kosztowe wyczerpane",
    status: "new",
    status_label: "Nowe",
    client_id: 12,
    client_name: "Polkomtel",
    order_group_id: 5,
    order_id: null,
    title: "Polkomtel — zamówienie SAP 4500719650 wyczerpane",
    message:
      "⚠ Polkomtel — zamówienie SAP 4500719650 zostało wyczerpane i przeniesione do zakończonych. Sprawdź rozliczenie i zorganizuj nowe zamówienie.",
    link: "/clients/12?tab=zamowienia",
    recipient_user_id: 3,
    recipient_name: "Anna Delivery",
    created_at: "2026-08-01T08:00:00Z",
    handled_at: null,
    handled_by_user_id: null,
    handled_by_name: null,
    reaction_seconds: null,
    reaction_label: "—",
    ...overrides,
  };
}

const WITH_DATA = [
  alert(),
  alert({
    id: 2,
    alert_type: "md_budget_low",
    alert_type_label: "Niski poziom MD na zamówieniu",
    client_name: "BIK",
    message:
      "⏳ BIK — zamówieniu 445 pozostało mniej niż 15 MD. Zorganizuj nowe zamówienie/przedłużenie.",
    created_at: "2026-08-08T08:00:00Z",
  }),
  alert({
    id: 3,
    alert_type: "draft_consultant_unassigned",
    alert_type_label: "Konsultant bez zamówienia (Draft)",
    client_name: "BNP",
    message:
      "🆕 BNP — Jan Kowalski czeka na przypisanie do zamówienia (status: Draft). Potrzebne jest zamówienie dla tej osoby.",
    created_at: "2026-08-15T08:00:00Z",
  }),
];

const HANDLED = [
  alert({
    id: 9,
    status: "handled",
    status_label: "Obsłużone",
    alert_type: "missing_revenue_rate",
    alert_type_label: "Brak stawki przychodowej",
    message: "✏️ Polkomtel — uzupełnij stawkę przychodową dla Anny Nowak w zamówieniu 446.",
    created_at: "2026-07-01T08:00:00Z",
    handled_at: "2026-07-03T11:30:00Z",
    handled_by_name: "Anna Delivery",
    reaction_seconds: 185400,
    reaction_label: "2 d 3 h",
  }),
];

type CaseKind = "data" | "empty" | "error";

function Case({
  title,
  why,
  kind,
}: {
  title: string;
  why: string;
  kind: CaseKind;
}) {
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: { staleTime: Infinity, retry: false, refetchOnMount: false },
      },
    });
    if (kind === "data") {
      qc.setQueryData(["dl-alerts", "new"], {
        alerts: WITH_DATA,
        total_new: WITH_DATA.length,
        total_handled: HANDLED.length,
      });
      qc.setQueryData(["dl-alerts", "handled"], {
        alerts: HANDLED,
        total_new: WITH_DATA.length,
        total_handled: HANDLED.length,
      });
    } else if (kind === "empty") {
      qc.setQueryData(["dl-alerts", "new"], {
        alerts: [],
        total_new: 0,
        total_handled: 0,
      });
    } else {
      // Gałąź awarii dostaje `queryFn`, które ODRZUCA lokalnie — bez sieci.
      //
      // Pierwsza wersja po prostu nie zasiewała klucza, licząc na to, że
      // niezalogowane zapytanie samo skończy się błędem. Kończyło się gorzej:
      // `/api/dl-alerts` zwracał 401, globalny interceptor axiosa przerzucał
      // CAŁĄ stronę na /login i harness znikał po kilku sekundach — razem ze
      // stanami, które miał pokazać. Publiczny podgląd nie może wylogowywać
      // oglądającego ani wykonywać żadnego żądania.
      qc.setDefaultOptions({
        queries: {
          staleTime: Infinity,
          retry: false,
          refetchOnMount: false,
          queryFn: () => Promise.reject(new Error("podgląd: wymuszona awaria")),
        },
      });
    }
    return qc;
  }, [kind]);

  return (
    <section className="flex flex-col gap-2">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="text-xs text-muted-foreground">{why}</p>
      </div>
      <QueryClientProvider client={queryClient}>
        <DlAlertsSection />
      </QueryClientProvider>
    </section>
  );
}

export default function DlAlertsPreview() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-8 p-8">
      <header>
        <h1 className="text-lg font-semibold">
          Harness — sekcja Powiadomienia (dashboard Delivery Lead)
        </h1>
        <p className="text-sm text-muted-foreground">
          Publiczny podgląd na zamrożonych danych.
        </p>
      </header>

      <Case
        kind="data"
        title="Nowe powiadomienia"
        why="Trzy typy zdarzeń naraz; „Historia” ma własny licznik, żeby przełączenie nie było skokiem w ciemno."
      />
      <Case
        kind="empty"
        title="Pusty stan"
        why="Brak nowych powiadomień to informacja, nie awaria — komunikat mówi to wprost."
      />
      <Case
        kind="error"
        title="Awaria pobrania"
        why="Musi wyglądać INACZEJ niż pustka: pusta lista po nieudanym zapytaniu czyta się jak utrata danych."
      />
    </main>
  );
}
