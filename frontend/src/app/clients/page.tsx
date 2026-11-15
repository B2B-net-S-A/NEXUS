"use client";

import { Suspense, useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useUrlWriter } from "@/lib/url-selection";
import { ClientsListV2 } from "@/components/v2/pages/ClientsListV2";
import { KeyRelationshipsPanel } from "@/components/clients/KeyRelationshipsPanel";
import { ReportsCalendarPanel } from "@/components/client-reports/ReportsCalendarPanel";
import { WorkspaceModeTabs } from "@/components/ds/WorkspaceModeTabs";
import { CLIENTS_MINE_ROLES, resolveClientsView, type ClientsView } from "@/lib/clients-workspace";
import { hasRole, useAuthStore } from "@/store/auth";

/**
 * „Klienci" = jeden ekran z dwoma trybami: lista klientów (z przełącznikiem
 * „Moi / Wszyscy" — dawny „Panel klientów") i kluczowe relacje (dawne „Moje
 * relacje"). Patrz `lib/clients-workspace.ts`.
 *
 * Client-only gate — patrz komentarz w /contracts/page.tsx.
 */
export default function ClientsPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie klientów…</div>;
  }
  return (
    <Suspense
      fallback={<div className="p-8 text-sm text-muted-foreground">Ładowanie klientów…</div>}
    >
      <ClientsWorkspace />
    </Suspense>
  );
}

const MODES = [
  { value: "list", label: "Lista klientów" },
  { value: "contacts", label: "Kluczowe relacje" },
  // Nowość „Raporty dla klientów”: kropka na przycisku trybu (WorkspaceModeTabs).
  { value: "reports", label: "Raporty dla klientów", tourId: "clients.reports" }, // data-tour="clients.reports"
] as const satisfies readonly { value: ClientsView; label: string; tourId?: string }[];

function ClientsWorkspace() {
  const { replaceUrl } = useUrlWriter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const user = useAuthStore((state) => state.user);
  // Tryb czytany z WARTOŚCI parametru przy każdym renderze — miękka
  // nawigacja (np. z palety ⌘K) przełącza widok bez odmontowania strony.
  const view = resolveClientsView(searchParams.get("view"));

  const changeView = (next: ClientsView) => {
    if (next === view) return;
    // Wejście w tryb jest świeże: filtry listy nie przechodzą do kontaktów.
    replaceUrl(next === "list" ? pathname : `${pathname}?view=${next}`);
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
      {/* Lista klientów rysuje tryby pod swoim tytułem (jak Kontrakty);
          kluczowe relacje nie mają tytułu, więc tryby stoją nad nimi. */}
      {view === "reports" ? (
        <>
          {modeTabs}
          <ReportsCalendarPanel
            defaultMine={searchParams.get("mine") === "1" || (searchParams.get("mine") !== "0" && hasRole(user, ...CLIENTS_MINE_ROLES))}
          />
        </>
      ) : view === "contacts" ? (
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
