"use client";

/**
 * Harness ekranu „Klienci” (`/clients`) — PRODUKCYJNE `ClientsListV2` (lista
 * klientów w trzech zakładkach portfela) i `KeyRelationshipsPanel` (tryb
 * „Kluczowe relacje”), z tym samym przełącznikiem trybów co
 * `app/clients/page.tsx`:
 *
 * - `/preview/clients-list` — lista klientów (`?category=relationship`
 *   i `?category=inactive` otwierają pozostałe zakładki portfela),
 * - `/preview/clients-list?view=contacts` — kluczowe relacje.
 *
 * Zero zapytań: cache react-query zasiany z góry (`staleTime: Infinity`),
 * a przechwytujący `axios` odrzuca lokalnie każde żądanie, które mimo to by
 * wyszło (wyszukiwarka, okna „Przenieś”, „Nowy klient”, „Czyszczenie listy”).
 * Użytkownik w store to fikcyjny admin — widzi „Nowy klient”, „Przenieś”
 * i „Aktualizuj”.
 *
 * Firmy, osoby, adresy i telefony są zmyślone (repo jest publiczne).
 */

import { Suspense, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { KeyRelationshipsPanel } from "@/components/clients/KeyRelationshipsPanel";
import { WorkspaceModeTabs } from "@/components/ds/WorkspaceModeTabs";
import { ToastProvider } from "@/components/Toast";
import { ClientsListV2 } from "@/components/v2/pages/ClientsListV2";
import {
  api,
  type ClientDirectoryCategory,
  type ClientDirectoryCategoryCounts,
  type ClientDirectoryItem,
  type ClientDirectoryResponse,
} from "@/lib/api";
import { resolveClientsView, type ClientsView } from "@/lib/clients-workspace";
import { useAuthStore, type User } from "@/store/auth";

const PREVIEW_ADMIN: User = {
  id: 1,
  email: "preview@example.com",
  name: "Administrator Przykładowy",
  role: "admin",
  roles: ["admin"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
};

// ── Lista klientów ───────────────────────────────────────────────────────────

type ScopeSeed = Pick<ClientDirectoryItem, "scope_id" | "client_id" | "display_name"> &
  Partial<ClientDirectoryItem>;

/** Wiersz katalogu: zakres bez umowy ramowej, w zakładce z manifestu. */
function scope(seed: ScopeSeed): ClientDirectoryItem {
  const category = seed.category ?? "active";
  return {
    msa_id: null,
    legal_name: null,
    scope_label: null,
    industry: null,
    active_consultants_count: 0,
    active_contracts_count: 0,
    consultants_scope: "client",
    effective_date: null,
    expiry_date: null,
    category,
    category_base: category,
    client_status: "active",
    category_override: null,
    contract_start_override: null,
    contract_end_override: null,
    ...seed,
  };
}

const DIRECTORY: Record<ClientDirectoryCategory, ClientDirectoryItem[]> = {
  active: [
    // Jeden klient, dwa zakresy — każdy z własną umową ramową i licznikiem.
    scope({
      scope_id: 1,
      client_id: 101,
      msa_id: 11,
      display_name: "Bank Przykładowy",
      legal_name: "Bank Przykładowy S.A.",
      industry: "Bankowość",
      scope_label: "Umowa ramowa IT 2025",
      active_consultants_count: 14,
      active_contracts_count: 15,
      consultants_scope: "scope",
      effective_date: "2025-01-01",
      expiry_date: "2027-12-31",
    }),
    scope({
      scope_id: 2,
      client_id: 101,
      msa_id: 12,
      display_name: "Bank Przykładowy",
      legal_name: "Bank Przykładowy S.A.",
      industry: "Bankowość",
      scope_label: "Utrzymanie systemów centralnych",
      active_consultants_count: 3,
      active_contracts_count: 3,
      consultants_scope: "scope",
      effective_date: "2026-03-01",
    }),
    scope({
      scope_id: 3,
      client_id: 102,
      msa_id: 13,
      display_name: "Telekom Demo",
      legal_name: "Telekom Demo sp. z o.o.",
      industry: "Telekomunikacja",
      active_consultants_count: 8,
      active_contracts_count: 9,
      effective_date: "2024-06-15",
      expiry_date: "2026-12-31",
    }),
    // Przeniesiony ręcznie z „Relacyjnych”, z przypiętą datą startu.
    scope({
      scope_id: 4,
      client_id: 103,
      display_name: "Ubezpieczenia Wzorcowe",
      legal_name: "Towarzystwo Ubezpieczeń Wzorcowe S.A.",
      industry: "Ubezpieczenia",
      scope_label: "Program Data & AI",
      active_consultants_count: 5,
      active_contracts_count: 5,
      effective_date: "2026-02-01",
      category_base: "relationship",
      category_override: "active",
      contract_start_override: "2026-02-01",
    }),
    // Prospekt dodany w tej zakładce: bez umowy i bez konsultantów.
    scope({
      scope_id: 5,
      client_id: 104,
      display_name: "Fintech Próbny",
      legal_name: "Fintech Próbny",
      industry: "Fintech",
      client_status: "prospect",
    }),
    scope({
      scope_id: 6,
      client_id: 105,
      msa_id: 14,
      display_name: "Energia Testowa",
      legal_name: "Energia Testowa Dystrybucja S.A.",
      industry: "Energetyka",
      scope_label: "Zespół integracji",
      active_consultants_count: 2,
      active_contracts_count: 2,
      effective_date: "2025-09-01",
      expiry_date: "2026-10-31",
    }),
    // Bez nazwy prawnej, branży i zakresu — wiersz bez drobnego druku.
    scope({
      scope_id: 7,
      client_id: 106,
      display_name: "Urząd Przykładowy",
      active_consultants_count: 1,
      active_contracts_count: 1,
    }),
  ],
  relationship: [
    scope({
      scope_id: 8,
      client_id: 107,
      msa_id: 15,
      category: "relationship",
      display_name: "Logistyka Makietowa",
      legal_name: "Logistyka Makietowa sp. z o.o.",
      industry: "Logistyka i transport",
      effective_date: "2023-04-01",
      expiry_date: "2026-03-31",
    }),
    scope({
      scope_id: 9,
      client_id: 108,
      category: "relationship",
      category_base: "active",
      category_override: "relationship",
      display_name: "Software Atrapa",
      legal_name: "Software Atrapa sp. z o.o.",
      industry: "Oprogramowanie",
      scope_label: "Zespoły produktowe",
      client_status: "inactive",
    }),
  ],
  inactive: [
    scope({
      scope_id: 10,
      client_id: 109,
      msa_id: 16,
      category: "inactive",
      display_name: "Media Zmyślone",
      legal_name: "Media Zmyślone S.A.",
      industry: "Media",
      client_status: "inactive",
      effective_date: "2021-01-01",
      expiry_date: "2023-12-31",
    }),
    scope({
      scope_id: 11,
      client_id: 110,
      category: "inactive",
      display_name: "Produkcja Wzorcowa",
      legal_name: "Zakłady Produkcyjne Wzorcowe sp. z o.o.",
      industry: "Przemysł",
      client_status: "inactive",
    }),
  ],
};

function uniqueClients(items: ClientDirectoryItem[]): number {
  return new Set(items.map((item) => item.client_id)).size;
}

const CATEGORY_COUNTS: ClientDirectoryCategoryCounts = {
  active: uniqueClients(DIRECTORY.active),
  relationship: uniqueClients(DIRECTORY.relationship),
  inactive: uniqueClients(DIRECTORY.inactive),
};

function directoryPage(category: ClientDirectoryCategory): ClientDirectoryResponse {
  const items = DIRECTORY[category];
  return {
    items,
    total_rows: items.length,
    total_clients: uniqueClients(items),
    page: 1,
    page_size: 50,
    category_counts: CATEGORY_COUNTS,
    as_of: new Date().toISOString(),
  };
}

// ── Kluczowe relacje ─────────────────────────────────────────────────────────

/** Kształt wiersza `GET /api/my-relationships` (lustro typu z panelu). */
interface RelationshipRow {
  contact_id: number;
  name: string;
  position: string | null;
  email: string | null;
  phone: string | null;
  client_id: number;
  client_name: string;
  is_decision_maker: boolean;
  relationship_strength: "cold" | "warm" | "strong" | "champion" | null;
  relationship_notes: string | null;
  last_personal_touchpoint_at: string | null;
  last_contacted_at: string | null;
  days_since_personal_touchpoint: number | null;
}

type RelationshipSeed = Omit<
  RelationshipRow,
  "last_personal_touchpoint_at" | "last_contacted_at"
>;

/** Najdawniej kontaktowane na górze — tak sortuje serwer. */
const RELATIONSHIPS: RelationshipSeed[] = [
  {
    contact_id: 506,
    name: "Ewa Próbna",
    position: "HR Business Partner",
    email: null,
    phone: "+48 500 000 006",
    client_id: 105,
    client_name: "Energia Testowa",
    is_decision_maker: false,
    relationship_strength: null,
    relationship_notes: null,
    days_since_personal_touchpoint: null,
  },
  {
    contact_id: 504,
    name: "Piotr Demonstracyjny",
    position: "CTO",
    email: "piotr.demonstracyjny@fintech-probny.example",
    phone: "+48 500 000 004",
    client_id: 104,
    client_name: "Fintech Próbny",
    is_decision_maker: true,
    relationship_strength: "cold",
    relationship_notes:
      "Rozmowa wstępna na konferencji. Wraca do tematu po zamknięciu rundy finansowania.",
    days_since_personal_touchpoint: 132,
  },
  {
    contact_id: 505,
    name: "Tomasz Fikcyjny",
    position: null,
    email: "tomasz.fikcyjny@logistyka-makietowa.example",
    phone: null,
    client_id: 107,
    client_name: "Logistyka Makietowa",
    is_decision_maker: false,
    relationship_strength: "warm",
    relationship_notes: "Dawny sponsor projektu WMS. Warto odświeżyć kontakt przed budżetowaniem.",
    days_since_personal_touchpoint: 95,
  },
  {
    contact_id: 503,
    name: "Julia Makietowa",
    position: "Head of Data",
    email: "julia.makietowa@ubezpieczenia-wzorcowe.example",
    phone: "+48 500 000 003",
    client_id: 103,
    client_name: "Ubezpieczenia Wzorcowe",
    is_decision_maker: false,
    relationship_strength: "warm",
    relationship_notes: "Planuje rozbudowę zespołu analityków w przyszłym kwartale.",
    days_since_personal_touchpoint: 47,
  },
  {
    contact_id: 502,
    name: "Marek Testowy",
    position: "Kierownik Zakupów IT",
    email: "marek.testowy@telekom-demo.example",
    phone: "+48 500 000 002",
    client_id: 102,
    client_name: "Telekom Demo",
    is_decision_maker: false,
    relationship_strength: "strong",
    relationship_notes: "Prowadzi przedłużenia zamówień. Woli krótkie podsumowanie mailem po każdej rozmowie.",
    days_since_personal_touchpoint: 24,
  },
  {
    contact_id: 501,
    name: "Anna Przykładowa",
    position: "Dyrektor IT",
    email: "anna.przykladowa@bank-przykladowy.example",
    phone: "+48 500 000 001",
    client_id: 101,
    client_name: "Bank Przykładowy",
    is_decision_maker: true,
    relationship_strength: "champion",
    relationship_notes:
      "Poleca nas innym departamentom. Lunch raz w miesiącu, ostatnio rozmowa o zespole migracji danych.",
    days_since_personal_touchpoint: 6,
  },
];

/** Data kontaktu zgodna z „N dni temu” — liczona po zamontowaniu. */
function touchpointDate(daysAgo: number | null): string | null {
  if (daysAgo === null) return null;
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return date.toISOString();
}

function relationshipRows(): RelationshipRow[] {
  return RELATIONSHIPS.map((row) => {
    const touchpoint = touchpointDate(row.days_since_personal_touchpoint);
    return {
      ...row,
      last_personal_touchpoint_at: touchpoint,
      last_contacted_at: touchpoint,
    };
  });
}

// ── Zasiew i ekran ───────────────────────────────────────────────────────────

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
    },
  });
  // Klucz listy: kategoria, fraza, strona, „Moi klienci” (admin = wszyscy).
  qc.setQueryData(["clients-directory", "active", "", 1, false], directoryPage("active"));
  qc.setQueryData(
    ["clients-directory", "relationship", "", 1, false],
    directoryPage("relationship"),
  );
  qc.setQueryData(["clients-directory", "inactive", "", 1, false], directoryPage("inactive"));
  qc.setQueryData(["my-relationships"], relationshipRows());
  return qc;
}

const MODES = [
  { value: "list", label: "Lista klientów" },
  { value: "contacts", label: "Kluczowe relacje" },
] as const satisfies readonly { value: ClientsView; label: string }[];

/** Lustro `ClientsWorkspace` z `app/clients/page.tsx` — tryb z `?view=`. */
function ClientsWorkspace() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const view = resolveClientsView(searchParams.get("view"));

  const changeView = (next: ClientsView) => {
    if (next === view) return;
    router.replace(next === "contacts" ? `${pathname}?view=contacts` : pathname, {
      scroll: false,
    });
  };

  const modeTabs = (
    <WorkspaceModeTabs
      label="Tryb modułu Klienci"
      modes={MODES}
      value={view}
      onChange={changeView}
    />
  );

  return (
    <div className="space-y-4">
      {view === "contacts" ? (
        <>
          {modeTabs}
          <KeyRelationshipsPanel />
        </>
      ) : (
        <ClientsListV2 modeTabs={modeTabs} />
      )}
    </div>
  );
}

export default function ClientsListPreview() {
  const [queryClient, setQueryClient] = useState<QueryClient | null>(null);

  // Po zamontowaniu: daty kontaktów „od dziś” zna tylko przeglądarka, a blokada
  // sieci i fikcyjny użytkownik mają zniknąć razem z harnessem.
  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    const previousUser = useAuthStore.getState().user;
    useAuthStore.setState({ user: PREVIEW_ADMIN });
    setQueryClient(seededClient());
    return () => {
      api.interceptors.request.eject(blocker);
      useAuthStore.setState({ user: previousUser });
    };
  }, []);

  if (!queryClient) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="flex min-h-dvh flex-col gap-4 bg-background p-4 sm:p-6">
          <header>
            <p className="text-sm font-semibold text-foreground">Harness — ekran „Klienci”</p>
            <p className="text-sm text-muted-foreground">
              Publiczny podgląd na fikcyjnych danych. Zero zapytań do API. Zakładki portfela
              i tryb „Kluczowe relacje” (<code>?view=contacts</code>) przełączają się jak na{" "}
              <code>/clients</code>.
            </p>
          </header>
          <Suspense
            fallback={<div className="text-sm text-muted-foreground">Ładowanie klientów…</div>}
          >
            <ClientsWorkspace />
          </Suspense>
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
