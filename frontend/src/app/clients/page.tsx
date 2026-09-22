"use client";

import { Suspense, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ClientsListV2 } from "@/components/v2/pages/ClientsListV2";
import { KeyRelationshipsPanel } from "@/components/clients/KeyRelationshipsPanel";
import { WorkspaceModeTabs } from "@/components/ds/WorkspaceModeTabs";
import { resolveClientsView, type ClientsView } from "@/lib/clients-workspace";

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
] as const satisfies readonly { value: ClientsView; label: string }[];

function ClientsWorkspace() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // Tryb czytany z WARTOŚCI parametru przy każdym renderze — miękka
  // nawigacja (np. z palety ⌘K) przełącza widok bez odmontowania strony.
  const view = resolveClientsView(searchParams.get("view"));

  const changeView = (next: ClientsView) => {
    if (next === view) return;
    // Wejście w tryb jest świeże: filtry listy nie przechodzą do kontaktów.
    router.replace(next === "contacts" ? `${pathname}?view=contacts` : pathname, {
      scroll: false,
    });
  };

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <WorkspaceModeTabs
        label="Tryb modułu Klienci"
        modes={MODES}
        value={view}
        onChange={changeView}
      />
      {view === "contacts" ? <KeyRelationshipsPanel /> : <ClientsListV2 />}
    </div>
  );
}
