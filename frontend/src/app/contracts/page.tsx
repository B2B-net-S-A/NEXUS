"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, Inbox } from "lucide-react";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import {
  ContractsClientPicker,
  type ClientRef,
} from "@/components/contracts/ContractsClientPicker";
import { ClientContractRegister } from "@/components/contracts/ClientContractRegister";
import { OrderMailQueue } from "@/components/order-mail/OrderMailQueue";
import { useOrderMailPendingCount } from "@/components/order-mail/useOrderMailPendingCount";
import { Button } from "@/components/ui/button";
import { useCapability } from "@/hooks/useCapability";
import { resolveContractsView, type ContractsView } from "@/lib/clients-workspace";

type ViewMode = ContractsView;

/**
 * /contracts — jedna lista kontraktów (makieta 18.11.2026):
 *  - rejestr (`ContractsListV2`) z szybkimi filtrami „Do uzupełnienia ·
 *    Aktywne · Kończące się · Wszystkie” zamiast trybów „Obsługa
 *    kontraktorów” / „Rejestr kontraktów”, które pokazywały te same umowy
 *    w dwóch cięciach i z innymi licznikami;
 *  - „Zamówienia z maila” to przycisk z licznikiem obok szybkich filtrów; kolejka
 *    otwiera się pod `?view=order-mail` (linki z powiadomień bez zmian)
 *    z powrotem do listy.
 *
 * Dawne `?view=operations&tab=…` (i `/contractors`) prowadzą na listę
 * z odpowiadającym filtrem.
 */

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
  const resolved = resolveContractsView(params.get("view"));
  // „Obsługa kontraktorów” nie jest już osobnym widokiem — to filtr listy.
  const view: ViewMode = resolved === "operations" ? "register" : resolved;
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

/** Dawny adres „Obsługi kontraktorów” → ten sam zbiór na liście. */
function legacyOperationsTarget(search: string): string | null {
  const params = new URLSearchParams(search);
  if (params.get("view") !== "operations") return null;
  const tab = params.get("tab");
  // „Kończący się” = ten sam zbiór co filtr „Kończące się” (`?ending=30`
  // → `bucket=ending` na serwerze).
  if (tab === "ending") return "/contracts?ending=30";
  const statuses = tab === "draft" ? ["draft", "ready_for_signature"] : ["active", "ending"];
  const next = new URLSearchParams();
  statuses.forEach((status) => next.append("status", status));
  return `/contracts?${next.toString()}`;
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
  const canSeeOrderMail = useCapability("nav.order_mail");
  const orderMailPending = useOrderMailPendingCount(canSeeOrderMail);

  useEffect(() => {
    setMounted(true);
  }, []);
  // Dawny adres „Obsługi kontraktorów”: najpierw podmiana adresu routerem
  // (lista czyta filtry z adresu i z `navigationSearch`), dopiero potem lista.
  const router = useRouter();
  const legacyTarget = legacyOperationsTarget(`?${navigationSearch}`);
  useEffect(() => {
    if (legacyTarget) router.replace(legacyTarget);
  }, [legacyTarget, router]);

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

  const showOrderMail = view === "order-mail" && canSeeOrderMail;

  const changeView = (next: ViewMode) => {
    setView(next);
    if (next !== "register") {
      // Client scope is a register-only concept.
      setClient(null);
    }
    // A mode switch is a fresh entry into the target view. Build the URL from
    // scratch so global `page`/filters, operations tab/page and client-register
    // filters can never be interpreted by another view.
    const target = next === "order-mail" ? "/contracts?view=order-mail" : "/contracts";
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

  // „Zamówienia z maila” w rzędzie szybkich filtrów zamiast trzeciej zakładki.
  const orderMailButton = canSeeOrderMail ? (
    <Button size="sm" variant="outline" onClick={() => changeView("order-mail")}>
      <Inbox className="h-4 w-4" aria-hidden="true" />
      Zamówienia z maila
      {orderMailPending ? (
        <span
          className="rounded-full bg-primary px-1.5 text-[11px] font-semibold leading-5 text-primary-foreground tabular-nums"
          aria-label={`${orderMailPending} do weryfikacji`}
        >
          {orderMailPending > 99 ? "99+" : orderMailPending}
        </span>
      ) : null}
    </Button>
  ) : null;
  const backToList = (
    <div>
      <Button size="sm" variant="ghost" onClick={() => changeView("register")}>
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Wróć do listy kontraktów
      </Button>
    </div>
  );
  const clientPicker = (
    <ContractsClientPicker
      compact
      value={client}
      onChange={handleClientChange}
    />
  );

  if (!mounted || legacyTarget) {
    return (
      <div className="p-8 text-sm text-muted-foreground">Ładowanie kontraktów…</div>
    );
  }

  return (
    // Bez limitu szerokości (jak pulpit) — panel szczegółów mieści się obok
    // tabeli bez osobnego poszerzania ramki.
    <div className="space-y-4">
      {/* Jedna lista z szybkimi filtrami; kolejka zamówień z maila z przycisku. */}
      {showOrderMail ? (
        <OrderMailQueue modeTabs={backToList} />
      ) : null}
      {showOrderMail ? null : client ? (
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
            toolbarLead={clientPicker}
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
          <ContractsListV2
            navigationSearch={navigationSearch}
            toolbarLead={clientPicker}
            trailingActions={orderMailButton}
          />
        </Suspense>
      )}
    </div>
  );
}
