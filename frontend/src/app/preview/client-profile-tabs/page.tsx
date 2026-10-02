"use client";

/**
 * Harness profilu klienta — PRODUKCYJNA strona `app/clients/[id]/page.tsx`
 * (nagłówek z liczbami, pasek zakładek i wszystkie zakładki) dla fikcyjnego
 * klienta „Bank Przykładowy S.A.”.
 *
 * Zero zapytań: cache react-query zasiany z góry pod każdy klucz, po który
 * sięgają strona i jej zakładki, a przechwytujący `axios` odrzuca wszystko,
 * co mimo to by wyszło (zapomniany klucz, zapis z otwartego okna) — zamiast
 * przekierowania na `/login` widać wtedy błąd w zakładce. Użytkownik w store
 * to fikcyjny admin z finansami — widać kwoty i akcje.
 *
 * Strona czyta `useParams()` i zapisuje zakładkę przez `router.replace` pod
 * `/clients/{id}`. Harness podaje jej parametr trasy i router, który adresy
 * tego klienta przepisuje na adres harnessu — klik w zakładkę zostaje tutaj.
 *
 * `?tab=` wybiera zakładkę: profil, zasady, projekty, zamowienia, importy-md,
 * zespol, kontakty, umowy-ramowe, analityka. `?tab=importy-md&import=3302`
 * otwiera import, `?tab=umowy-ramowe&framework=7001` rozwija aneksy umowy.
 *
 * Osoby, firma, numery i kwoty są zmyślone (repo jest publiczne) — `fixtures.ts`.
 */

import { Suspense, useEffect, useMemo, useState, type ReactNode } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider, type QueryKey } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { AppRouterContext } from "next/dist/shared/lib/app-router-context.shared-runtime";
import { PathParamsContext } from "next/dist/shared/lib/hooks-client-context.shared-runtime";

import ClientDetailPage from "@/app/clients/[id]/page";
import { ToastProvider } from "@/components/Toast";
import { CLIENT_CONFLICTS_LIMIT } from "@/components/client-profile/ClientConflictsSection";
import { clientMdImportsQueryKey } from "@/components/client-profile/orders/ClientMdImportsTab";
import { api } from "@/lib/api";
import { conflictKeys } from "@/lib/conflicts";
import { useAuthStore } from "@/store/auth";
import { useTabsStore, type Tab } from "@/store/tabs";

import {
  CLIENT_ID,
  PREVIEW_USER,
  buildFixtures,
  dashboardQueryKey,
  type ClientProfileFixtures,
} from "./fixtures";

const HARNESS_PATH = "/preview/client-profile-tabs";
const CLIENT_PATH = `/clients/${CLIENT_ID}`;

/** Zasiane dane są „świeże” dłużej, niż żyje karta — także dla hooków
 *  z własnym `staleTime` (karta klienta, kategorie, projekty). */
const FRESH_FOR_MS = 7 * 24 * 60 * 60 * 1000;

function seededClient(data: ClientProfileFixtures): QueryClient {
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        // Zakładka, której nikt jeszcze nie otworzył, nie może stracić zasiewu.
        gcTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
    },
  });
  const seed = (key: QueryKey, value: unknown) =>
    qc.setQueryData(key, value, { updatedAt: Date.now() + FRESH_FOR_MS });

  // Strona: klient (klucz niesie `id` z `useParams`, czyli napis) i zespół.
  seed(["client", String(CLIENT_ID)], data.client);
  seed(["client-team", CLIENT_ID], data.team);

  // Profil: konsultanci i liczby nagłówka, statystyki, materiały, konflikty.
  seed(["client-profile", CLIENT_ID], data.profile);
  seed(["competence-categories-active"], data.competenceCategories);
  seed(["client-coop-stats", CLIENT_ID, "year"], data.coopStats);
  seed(["client-coop-trend", CLIENT_ID, 6], data.coopTrend);
  seed(["client-one-pagers", CLIENT_ID], data.onePagers);
  seed(["client-required-docs", CLIENT_ID], data.requiredDocs);
  seed(["required-document-templates"], data.requiredDocTemplates);
  seed(["client-contract-terms", CLIENT_ID], data.contractTerms);
  seed(
    conflictKeys.registry({
      client_id: CLIENT_ID,
      state: "active",
      limit: CLIENT_CONFLICTS_LIMIT,
      offset: 0,
    }),
    data.conflicts,
  );

  // Zasady współpracy: karta, jej historia (formularz edycji) i reguła CV.
  seed(["client-playbook", CLIENT_ID], data.playbook);
  seed(["client-playbook-history", CLIENT_ID], data.playbookHistory);
  seed(["client-cv-rule", CLIENT_ID], data.cvRule);

  // Projekty: oba kubełki przy pustej wyszukiwarce.
  seed(["client-jobs", CLIENT_ID, "active", ""], data.activeJobs);
  seed(["client-jobs", CLIENT_ID, "closed", ""], data.closedJobs);

  // Kontakty, Delivery Lead i wiedza o kliencie.
  seed(["client-contacts", CLIENT_ID], data.contacts);
  seed(["client-knowledge", CLIENT_ID], data.knowledge);
  seed(["users-list-owners"], data.users);

  // Umowy: ramowe z aneksami i cennik.
  seed(["framework-contracts", CLIENT_ID], data.frameworkContracts);
  for (const [frameworkId, amendments] of Object.entries(data.amendments)) {
    seed(["amendments", CLIENT_ID, Number(frameworkId)], amendments);
  }
  seed(["rate-cards", CLIENT_ID], data.rateCards);

  // Analityka i importy MD (lista + każdy import).
  seed(dashboardQueryKey(PREVIEW_USER), data.dashboard);
  seed(clientMdImportsQueryKey(CLIENT_ID), { imports: data.mdImports.list });
  for (const detail of data.mdImports.details) {
    seed([...clientMdImportsQueryKey(CLIENT_ID), detail.id], detail);
  }

  // Zamówienia — minimalnie; pełny widok ma `/preview/client-orders`.
  seed(["client-order-groups", CLIENT_ID], data.orderGroups);
  seed(["dl-orders-grouped", CLIENT_ID], data.contractors);
  seed(["client-default-rate-unit", CLIENT_ID], "hourly");
  return qc;
}

/** Adres profilu tego klienta → ten sam adres w harnessie; reszta bez zmian. */
function toHarnessHref(href: string): string {
  if (href === CLIENT_PATH) return HARNESS_PATH;
  if (href.startsWith(`${CLIENT_PATH}?`)) {
    return `${HARNESS_PATH}${href.slice(CLIENT_PATH.length)}`;
  }
  return href;
}

/**
 * Strona profilu żyje pod `/clients/[id]`: bierze `id` z `useParams()`,
 * a wybraną zakładkę zapisuje przez `router.replace("/clients/{id}?tab=…")`.
 * Tutaj dostaje parametr trasy i router przepisujący te adresy na harness —
 * bez tego klik w zakładkę wychodziłby na prawdziwy profil (i na `/login`).
 */
function HarnessRouting({ children }: { children: ReactNode }) {
  const router = useRouter();
  const harnessRouter = useMemo<typeof router>(
    () => ({
      ...router,
      push: (href, options) => router.push(toHarnessHref(href), options),
      replace: (href, options) => router.replace(toHarnessHref(href), options),
    }),
    [router],
  );
  const params = useMemo(() => ({ id: String(CLIENT_ID) }), []);
  return (
    <AppRouterContext.Provider value={harnessRouter}>
      <PathParamsContext.Provider value={params}>{children}</PathParamsContext.Provider>
    </AppRouterContext.Provider>
  );
}

interface OpenTabsSnapshot {
  tabs: Tab[];
  activeTabId: string | null;
}

/**
 * Strona dopisuje klienta do „Otwartych kart” (store zapisywany w
 * localStorage). Fikcyjny klient nie może tam zostać po wizycie w harnessie,
 * więc po efektach strony przywracamy listę sprzed jej zamontowania.
 */
function ProfileUnderTest({ openTabs }: { openTabs: OpenTabsSnapshot }) {
  useEffect(() => {
    useTabsStore.setState(openTabs);
  }, [openTabs]);
  return <ClientDetailPage />;
}

interface HarnessState {
  queryClient: QueryClient;
  openTabs: OpenTabsSnapshot;
}

function ClientProfileTabsHarness() {
  const [armed, setArmed] = useState(false);
  const [state, setState] = useState<HarnessState | null>(null);

  // Fikcyjny użytkownik wchodzi do store'u dopiero w drugim przebiegu
  // efektów: w pierwszym powłoka aplikacji (rodzic tej strony) wczytuje sesję
  // z localStorage i nadpisałaby go, a strona profilu musi znać użytkownika
  // już przy pierwszym renderze (inaczej `?tab=umowy-ramowe` cofa się na Profil).
  useEffect(() => setArmed(true), []);

  useEffect(() => {
    if (!armed) return;
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    const auth = useAuthStore.getState();
    const previousAuth = {
      user: auth.user,
      token: auth.token,
      realUser: auth.realUser,
      hydrated: auth.hydrated,
    };
    useAuthStore.setState({
      user: PREVIEW_USER,
      token: null,
      realUser: null,
      hydrated: true,
    });
    const tabs = useTabsStore.getState();
    setState({
      queryClient: seededClient(buildFixtures()),
      openTabs: { tabs: tabs.tabs, activeTabId: tabs.activeTabId },
    });
    return () => {
      api.interceptors.request.eject(blocker);
      useAuthStore.setState(previousAuth);
    };
  }, [armed]);

  if (!state) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <QueryClientProvider client={state.queryClient}>
      <ToastProvider>
        <main className="mx-auto flex max-w-[1680px] flex-col gap-4 p-4 sm:p-6">
          <header>
            <h1 className="text-lg font-semibold">Harness — profil klienta (zakładki)</h1>
            <p className="text-sm text-muted-foreground">
              Publiczny podgląd na fikcyjnych danych. Zero zapytań do API. Zakładkę
              wybiera <code>?tab=</code>: profil, zasady, projekty, zamowienia,
              importy-md, zespol, kontakty, umowy-ramowe, analityka.
            </p>
          </header>
          <HarnessRouting>
            <ProfileUnderTest openTabs={state.openTabs} />
          </HarnessRouting>
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}

export default function ClientProfileTabsPreview() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>}>
      <ClientProfileTabsHarness />
    </Suspense>
  );
}
