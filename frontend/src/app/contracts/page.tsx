"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Inbox } from "lucide-react";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";
import {
  ContractsClientPicker,
  type ClientRef,
} from "@/components/contracts/ContractsClientPicker";
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
 *
 * Kontrakty jednego klienta (18.11.2026, wariant B „Konsultanci”) są w profilu
 * klienta: wybór klienta otwiera jego zakładkę „Konsultanci”, a dawny rejestr
 * klienta pod `?client=` przekierowuje tam samo.
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

function viewFromSearch(search: string): ViewMode {
  const resolved = resolveContractsView(new URLSearchParams(search).get("view"));
  // „Obsługa kontraktorów” nie jest już osobnym widokiem — to filtr listy.
  return resolved === "operations" ? "register" : resolved;
}

/** Zakładka „Konsultanci” klienta — tam są jego kontrakty od 18.11.2026. */
function clientConsultantsHref(clientId: number): string {
  return `/clients/${clientId}?tab=konsultanci`;
}

/**
 * Dawne adresy → nowe miejsce: „Obsługa kontraktorów” na ten sam zbiór listy,
 * rejestr klienta (`?client=`) na zakładkę „Konsultanci” tego klienta.
 */
function legacyTarget(search: string): string | null {
  const params = new URLSearchParams(search);
  const clientId = Number(params.get("client"));
  if (params.get("view") !== "order-mail" && Number.isInteger(clientId) && clientId > 0) {
    return clientConsultantsHref(clientId);
  }
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
  const [mounted, setMounted] = useState(false);
  const [view, setView] = useState<ViewMode>(() => viewFromSearch(navigationSearch));
  const [appliedNavigationSearch, setAppliedNavigationSearch] =
    useState(navigationSearch);
  const canSeeOrderMail = useCapability("nav.order_mail");
  const orderMailPending = useOrderMailPendingCount(canSeeOrderMail);

  useEffect(() => {
    setMounted(true);
  }, []);
  // Dawny adres („Obsługa kontraktorów”, rejestr klienta): najpierw podmiana
  // adresu routerem (lista czyta filtry z adresu i z `navigationSearch`),
  // dopiero potem lista.
  const router = useRouter();
  const redirectTarget = legacyTarget(`?${navigationSearch}`);
  useEffect(() => {
    if (redirectTarget) router.replace(redirectTarget);
  }, [redirectTarget, router]);

  // Next can retain this page instance for same-route sidebar navigation.
  // Reconcile the workspace selection during render so an external queryless
  // `/contracts` immediately unmounts the old client/operations view before a
  // child can canonicalise its stale URL back into history.
  if (appliedNavigationSearch !== navigationSearch) {
    setAppliedNavigationSearch(navigationSearch);
    setView(viewFromSearch(navigationSearch));
  }

  const showOrderMail = view === "order-mail" && canSeeOrderMail;

  const changeView = (next: ViewMode) => {
    setView(next);
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

  // Wybór klienta otwiera jego zakładkę „Konsultanci” (18.11.2026) — lista
  // tutaj zostaje przekrojem przez wszystkich klientów.
  const handleClientChange = (next: ClientRef | null) => {
    if (next) router.push(clientConsultantsHref(next.id));
  };

  // „Zamówienia z maila” w rzędzie szybkich filtrów zamiast trzeciej zakładki.
  const orderMailButton = canSeeOrderMail ? (
    <Button
      size="sm"
      variant="outline"
      onClick={() => changeView("order-mail")}
      data-tour="contracts.order-mail.open"
    >
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
  const clientPicker = (
    <ContractsClientPicker
      compact
      value={null}
      onChange={handleClientChange}
    />
  );

  if (!mounted || redirectTarget) {
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
        // „← Kontrakty” wraca do listy bez nowego wpisu w historii (jak przycisk,
        // który kolejkę otwiera).
        <OrderMailQueue onBack={() => changeView("register")} />
      ) : null}
      {showOrderMail ? null : (
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
