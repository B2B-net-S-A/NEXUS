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
import {
  MY_CLIENTS_CARDS_QUERY_KEY,
  MyClientsAlertsPanel,
} from "@/components/v2/dashboard/MyClientsAlertsPanel";
import type {
  DlAlertCard,
  DlAlertRead,
  DlAlertStatus,
} from "@/lib/api/dlAlerts";

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

type CaseKind = "data" | "empty";

// Lista statusów w JEDNYM miejscu — zasiew podgladu iteruje po niej, więc
// dołożenie trzeciego statusu nie zostawi po cichu klucza strzelającego do API.
const DL_ALERT_STATUSES: readonly DlAlertStatus[] = [
  "new",
  "handled",
  "resolved",
] as const;

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
    // Zasiew idzie PĘTLĄ po wszystkich statusach, a nie ręcznie klucz po
    // kluczu. `DlAlertsSection` renderuje obie zakładki bezwarunkowo i
    // przełącza `queryKey` na ["dl-alerts", tab], a klucz niezasiany nie ma
    // `dataUpdatedAt` — więc `staleTime: Infinity` go NIE powstrzymuje.
    // Poleciałoby realne zapytanie, wróciłby 401, a globalny interceptor
    // przerzuciłby CAŁĄ stronę na /login: publiczny podgląd wylogowałby
    // oglądającego jednym kliknięciem w „Historię". Domyślny odrzucający
    // `queryFn` tego nie załatwia — komponent podaje własny, a jawny wygrywa.
    // Dlatego obietnica „zero zapytań" nie może zależeć od tego, czy ktoś
    // pamiętał o drugim kluczu.
    const seed: Record<DlAlertStatus, DlAlertRead[]> =
      kind === "data"
        ? { new: WITH_DATA, handled: HANDLED, resolved: [] }
        : { new: [], handled: [], resolved: [] };
    for (const status of DL_ALERT_STATUSES) {
      qc.setQueryData(["dl-alerts", status], {
        alerts: seed[status],
        total_new: seed.new.length,
        total_handled: seed.handled.length,
      });
    }
    // Gałąź AWARII świadomie nie ma tu swojego przypadku — patrz komentarz
    // przy `CASES` na dole pliku.
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

// Zamrożone karty panelu „Moi klienci" — ten sam układ co makieta z ticketu.
// Dane FIKCYJNE (repo jest publiczne): żadnych prawdziwych nazwisk.
function card(overrides: Partial<DlAlertCard>): DlAlertCard {
  return {
    id: 100,
    event_key: "periodic_order_ending:order:1:end:2026-10-14:3",
    alert_type: "periodic_order_ending",
    alert_type_label: "Kończące się zamówienie",
    section: "ending",
    priority: "standard",
    client_id: 12,
    client_name: "Klient Alfa",
    order_group_id: null,
    order_id: 1,
    title: "Klient Alfa — zamówienie kończy się",
    message: "",
    link: "/clients/12?tab=zamowienia&order=1",
    candidate_name: null,
    end_date: null,
    days_left: null,
    missing_fields: [],
    source: null,
    received_at: null,
    first_alert_at: "2026-09-14T08:00:00Z",
    last_alert_at: "2026-09-14T08:00:00Z",
    repeat_count: 1,
    email_sent: false,
    email_requested: false,
    can_mark_handled: true,
    ...overrides,
  };
}

const PANEL_CARDS: DlAlertCard[] = [
  card({
    id: 101,
    priority: "high",
    client_name: "Bank Beta",
    candidate_name: "Anita Przykładowa",
    end_date: "2026-10-14",
    days_left: 7,
    message:
      "Zamówienie dla Anita Przykładowa kończy się 2026-10-14. Przygotuj kolejne zamówienie lub przedłużenie.",
    repeat_count: 4,
    email_sent: true,
    email_requested: true,
  }),
  card({
    id: 102,
    event_key: "periodic_order_ending:order:2:end:2026-10-07:3",
    client_name: "Grupa Gamma",
    candidate_name: "Marcin Testowy",
    end_date: "2026-10-07",
    days_left: 23,
    message:
      "Zamówienie dla Marcin Testowy kończy się 2026-10-07. Skontaktuj się z klientem w sprawie przedłużenia i przygotuj nowe zamówienie.",
    link: "/clients/13?tab=zamowienia&order=2",
  }),
  card({
    id: 103,
    event_key: "md_budget_low:order:3:3",
    alert_type: "md_budget_low",
    alert_type_label: "Niski poziom MD na zamówieniu",
    client_name: "Telekom Delta",
    candidate_name: "Ola Wzorcowa",
    message: "Zamówieniu MD-445 dla Ola Wzorcowa zostało 18 MD. Zorganizuj nowe zamówienie lub przedłużenie.",
    link: "/clients/14?tab=zamowienia&order=3",
    repeat_count: 2,
  }),
  card({
    id: 104,
    event_key: "new_contractor_draft:order:4:3",
    alert_type: "new_contractor_draft",
    alert_type_label: "Nowy kontraktor — draft zamówienia",
    section: "new_contractor",
    client_name: "Telekom Delta",
    candidate_name: "Jan Próbny",
    message:
      "Nowy kontraktor Jan Próbny — umowa podpisana obustronnie. Uzupełnij: stawkę przychodową, okres zamówienia, numer zamówienia.",
    link: "/clients/14?tab=zamowienia&order=4",
    missing_fields: ["stawkę przychodową", "okres zamówienia", "numer zamówienia"],
    source: "b2b_generator",
  }),
  // BNP: dwa NIEZALEŻNE sygnały o TYM SAMYM zamówieniu — długi okres i wysokie
  // zużycie podstawy MD. Stoją obok siebie, bo nigdy nie są łączone w jedną kartę.
  card({
    id: 106,
    event_key: "md_base_usage_high:order:6:3",
    alert_type: "md_base_usage_high",
    alert_type_label: "Wysokie zużycie podstawy MD",
    client_name: "Bank Zeta",
    candidate_name: "Piotr Wzorowy",
    title: "Bank Zeta — 82% podstawy MD na zamówieniu 4500123456",
    message:
      "Zamówienie 4500123456 dla Piotr Wzorowy: wykorzystano 180 z 220 MD podstawy (82%). Zaplanuj przedłużenie albo kolejne zamówienie.",
    link: "/clients/15?tab=zamowienia&order=6",
    order_group_id: 9,
    order_id: 6,
    repeat_count: 3,
  }),
  card({
    id: 107,
    event_key: "periodic_order_ending:order:6:end:2026-12-31:3",
    client_name: "Bank Zeta",
    candidate_name: "Piotr Wzorowy",
    title: "Bank Zeta — zamówienie dla Piotr Wzorowy kończy się",
    end_date: "2026-12-31",
    days_left: 28,
    message:
      "Zamówienie dla Piotr Wzorowy kończy się 2026-12-31. Skontaktuj się z klientem w sprawie przedłużenia i przygotuj nowe zamówienie.",
    link: "/clients/15?tab=zamowienia&order=6",
    order_group_id: 9,
    order_id: 6,
    email_sent: true,
  }),
  card({
    id: 105,
    event_key: "order_mail_review:order_mail:5:3",
    alert_type: "order_mail_review",
    alert_type_label: "Zamówienie z maila do weryfikacji",
    section: "order_mail",
    client_name: "Słodycze Epsilon",
    candidate_name: "Maria Fikcyjna",
    message:
      "Zamówienie dla Maria Fikcyjna do Słodycze Epsilon czeka na ręczną weryfikację w zakładce Zamówienia z maila.",
    link: "/order-mail?doc=5",
    received_at: "2026-09-13",
  }),
];

function PanelCase({
  title,
  why,
  cards,
}: {
  title: string;
  why: string;
  cards: DlAlertCard[];
}) {
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: {
        queries: { staleTime: Infinity, retry: false, refetchOnMount: false },
      },
    });
    // `updatedAt` daleko w przyszłości: panel ma własne `staleTime`, więc
    // świeży „teraz" zestarzałby się po 30 s i fokus okna wysłałby zapytanie.
    const future = Date.now() + 10 * 365 * 24 * 3600 * 1000;
    qc.setQueryData(
      MY_CLIENTS_CARDS_QUERY_KEY,
      { cards, total: cards.length },
      { updatedAt: future },
    );
    for (const status of DL_ALERT_STATUSES) {
      qc.setQueryData(
        ["dl-alerts", status],
        {
          alerts: status === "handled" ? HANDLED : [],
          total_new: 0,
          total_handled: HANDLED.length,
        },
        { updatedAt: future },
      );
    }
    return qc;
  }, [cards]);

  return (
    <section className="flex flex-col gap-2">
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        <p className="text-xs text-muted-foreground">{why}</p>
      </div>
      <QueryClientProvider client={queryClient}>
        <MyClientsAlertsPanel refetchIntervalMs={false} />
      </QueryClientProvider>
    </section>
  );
}

export default function DlAlertsPreview() {
  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-8 px-4 py-8 sm:px-8">
      <PanelCase
        title="Panel „Moi klienci” — sprawy do zrobienia"
        why="Wysoki priorytet (≤7 dni), przypomnienie standardowe, draft z Generatora umów i mail do weryfikacji. Mail do DL leci przy pierwszej karcie (zwykle miesiąc przed końcem) oraz na progach 14 i 7 dni. Checkbox zdejmuje kartę, przycisk prowadzi do konkretnego obiektu."
        cards={PANEL_CARDS}
      />
      <PanelCase
        title="Panel „Moi klienci” — pusty stan"
        why="Brak spraw to informacja, nie awaria."
        cards={[]}
      />
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
      {/* Gałęzi AWARII nie da się tu pokazać bez wykonania zapytania, a to
          jest dokładnie to, czego publiczny podgląd robić nie może:
          `DlAlertsSection` przekazuje własne `queryFn` (jawne wygrywa
          z domyślnym), a wpisanie stanu błędu wprost do cache'u nie
          powstrzymuje pierwszego pobrania. Pierwsza wersja tej strony po
          prostu nie zasiewała klucza — zapytanie leciało do API, wracało 401,
          a globalny interceptor axiosa przerzucał CAŁĄ stronę na /login
          i podgląd znikał oglądającemu z ekranu.

          Rozróżnienie „awaria ≠ pustka" jest bronione testem
          `DlAlertsSection.test.tsx` → „awaria pobrania NIE renderuje się jako
          pusty stan", który mockuje API i asertuje oba komunikaty naraz.
          Lepszy test niż kafelek, który kosztuje wylogowanie. */}
    </main>
  );
}
