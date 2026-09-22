"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import { ContractorsListV2 } from "@/components/v2/pages/ContractorsListV2";
import {
  ContractsClientPicker,
  type ClientRef,
} from "@/components/contracts/ContractsClientPicker";
import { ClientContractRegister } from "@/components/contracts/ClientContractRegister";
import { OrderMailQueue } from "@/components/order-mail/OrderMailQueue";
import { useOrderMailPendingCount } from "@/components/order-mail/useOrderMailPendingCount";
import {
  WorkspaceModeTabs,
  type WorkspaceMode,
} from "@/components/ds/WorkspaceModeTabs";
import { useCapability } from "@/hooks/useCapability";
import { resolveContractsView, type ContractsView } from "@/lib/clients-workspace";
import { hasSectionAccess } from "@/lib/section-access";
import { hasRole, useAuthStore } from "@/store/auth";

type ViewMode = ContractsView;

/**
 * /contracts is one workspace with three modes:
 *  - "register"   — the full contract register (global list or per-client),
 *                   financial-gated. Default; visible to everyone who can open
 *                   /contracts today.
 *  - "operations" — the contractor roster (drafty do uzupełnienia / aktywni /
 *                   kończący się). Role-gated to the same roles the former
 *                   standalone "Kontraktorzy" nav item used. The backend
 *                   enforces access independently (403 for viewers), so the
 *                   toggle is UX, not the security boundary.
 *  - "order-mail" — the order-mail queue („Skrzynka zamówień"). Until
 *                   22.09.2026 a separate nav item „Zamówienia z maila";
 *                   `/order-mail` now redirects here (stored notification
 *                   links keep working, `?doc=` is preserved).
 *
 * The former /contractors route now redirects here with ?view=operations.
 *
 * Workspace state lives in the URL via the History API, so deep-links and
 * back/forward work. The reactive search-param reader sits inside an explicit
 * Suspense boundary required by Next's streaming renderer.
 */

const OPERATIONS_ROLES = [
  "admin",
  "delivery_lead",
  "talent_community_manager",
  "finance",
] as const;

export default function ContractsPage() {
  return (
    <Suspense
      fallback={
        <div className="p-8 text-sm text-muted-foreground">
          Ładowanie kontraktów…
        </div>
      }
    >
      <ContractsPageWithNavigationState />
    </Suspense>
  );
}

function ContractsPageWithNavigationState() {
  const searchParams = useSearchParams();
  return <ContractsWorkspace navigationSearch={searchParams.toString()} />;
}

function selectionFromSearch(search: string): {
  view: ViewMode;
  client: ClientRef | null;
} {
  const params = new URLSearchParams(search);
  const view = resolveContractsView(params.get("view"));
  if (view !== "register") {
    return { view, client: null };
  }
  const clientId = Number(params.get("client"));
  return {
    view: "register",
    client:
      Number.isInteger(clientId) && clientId > 0
        ? {
            id: clientId,
            name: params.get("clientName") ?? `#${clientId}`,
          }
        : null,
  };
}

function ContractsWorkspace({
  navigationSearch,
}: {
  navigationSearch: string;
}) {
  const initialSelection = selectionFromSearch(navigationSearch);
  const [mounted, setMounted] = useState(false);
  const [view, setView] = useState<ViewMode>(initialSelection.view);
  const [client, setClient] = useState<ClientRef | null>(
    initialSelection.client,
  );
  const [appliedNavigationSearch, setAppliedNavigationSearch] =
    useState(navigationSearch);
  const { user } = useAuthStore();
  // Rola + sufit sekcji Delivery (U8): odebrana sekcja = brak widoku, nie 403.
  const canSeeOperations =
    hasRole(user, ...OPERATIONS_ROLES) &&
    hasSectionAccess(user, "delivery", "read");
  const canSeeOrderMail = useCapability("nav.order_mail");
  const orderMailPending = useOrderMailPendingCount(canSeeOrderMail);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Next can retain this page instance for same-route sidebar navigation.
  // Reconcile the workspace selection during render so an external queryless
  // `/contracts` immediately unmounts the old client/operations view before a
  // child can canonicalise its stale URL back into history.
  if (appliedNavigationSearch !== navigationSearch) {
    const nextSelection = selectionFromSearch(navigationSearch);
    setAppliedNavigationSearch(navigationSearch);
    setView(nextSelection.view);
    setClient(nextSelection.client);
  }

  // Guard: a non-operational role that deep-links ?view=operations falls back
  // to the register (and the backend would 403 the roster fetch anyway).
  const showOperations = view === "operations" && canSeeOperations;
  const showOrderMail = view === "order-mail" && canSeeOrderMail;
  const activeView: ViewMode = showOperations
    ? "operations"
    : showOrderMail
      ? "order-mail"
      : "register";
  const modes: WorkspaceMode<ViewMode>[] = [
    ...(canSeeOperations
      ? [{ value: "operations" as const, label: "Obsługa kontraktorów" }]
      : []),
    { value: "register", label: "Rejestr kontraktów" },
    ...(canSeeOrderMail
      ? [
          {
            value: "order-mail" as const,
            label: "Skrzynka zamówień",
            count: orderMailPending,
          },
        ]
      : []),
  ];

  const changeView = (next: ViewMode) => {
    setView(next);
    if (next !== "register") {
      // Client scope is a register-only concept.
      setClient(null);
    }
    // A mode switch is a fresh entry into the target view. Build the URL from
    // scratch so global `page`/filters, operations tab/page and client-register
    // filters can never be interpreted by another view.
    const target =
      next === "operations"
        ? "/contracts?view=operations&tab=active"
        : next === "order-mail"
          ? "/contracts?view=order-mail"
          : "/contracts";
    window.history.replaceState(
      window.history.state,
      "",
      target,
    );
  };

  const handleClientChange = (next: ClientRef | null) => {
    setClient(next);
    const params = new URLSearchParams(window.location.search);
    if (next) {
      if (client?.id !== next.id) {
        // Podkategorie należą do konkretnego klienta; nie wolno przenosić ich
        // do kolejnego rejestru. Pozostałe filtry są klient-niezależne.
        params.delete("register_subcategory");
        params.delete("register_page");
      }
      params.set("client", String(next.id));
      params.set("clientName", next.name);
    } else {
      params.delete("client");
      params.delete("clientName");
    }
    const qs = params.toString();
    window.history.replaceState(
      window.history.state,
      "",
      `/contracts${qs ? `?${qs}` : ""}`,
    );
  };

  if (!mounted) {
    return (
      <div className="p-8 text-sm text-muted-foreground">Ładowanie kontraktów…</div>
    );
  }

  return (
    <div className="max-w-[1400px] mx-auto space-y-4">
      {modes.length > 1 && (
        <WorkspaceModeTabs
          label="Tryb modułu Kontrakty"
          modes={modes}
          value={activeView}
          onChange={changeView}
        />
      )}

      {showOperations ? (
        <Suspense
          fallback={
            <div className="p-8 text-sm text-muted-foreground">
              Ładowanie kontraktorów…
            </div>
          }
        >
          <ContractorsListV2 />
        </Suspense>
      ) : showOrderMail ? (
        <OrderMailQueue />
      ) : (
        <>
          <ContractsClientPicker value={client} onChange={handleClientChange} />
          {client ? (
            <Suspense
              fallback={
                <div className="p-8 text-sm text-muted-foreground">
                  Ładowanie rejestru klienta…
                </div>
              }
            >
              <ClientContractRegister
                clientId={client.id}
                clientName={client.name}
                navigationSearch={navigationSearch}
              />
            </Suspense>
          ) : (
            <Suspense
              fallback={
                <div className="p-8 text-sm text-muted-foreground">
                  Ładowanie kontraktów…
                </div>
              }
            >
              <ContractsListV2 navigationSearch={navigationSearch} />
            </Suspense>
          )}
        </>
      )}
    </div>
  );
}
