"use client";

import type { ReactNode } from "react";
import { ArrowRight } from "lucide-react";

import {
  FrameworkStatCard,
  InvoicingStatCard,
  JobsStatCard,
  LatestJobsCard,
  PeopleCard,
  PeopleStatCard,
  ReportsCard,
} from "@/components/client-profile/ClientOverviewCards";
import {
  useClientOverviewAttention,
  type OverviewAttentionItem,
} from "@/components/client-profile/overview-attention";
import { useClientProfile } from "@/components/client-profile/useClientProfile";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import type { ClientTab } from "@/lib/client-tab";
import { CLIENT_SUBTAB_LABELS } from "@/lib/client-tab-groups";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";

interface Props {
  clientId: number;
  onOpen: (tab: ClientTab) => void;
  /** Umowy klienta (podgląd dokumentów): karta umowy ramowej i jej znacznik. */
  showContracts: boolean;
  /** Moduł faktur: karta rozliczenia poprzedniego miesiąca. */
  showInvoicing: boolean;
  /** Główny Delivery Lead („Imię Nazwisko +1”) — karta „Ludzie klienta”. */
  deliveryLead?: string | null;
  /** Sprzęt, statystyki współpracy i notatki — dolny rząd Przeglądu. */
  children?: ReactNode;
}

/**
 * Przegląd klienta (makieta 19.11.2026, wariant A, decyzja Artura): najpierw
 * „co zrobić” — sprawy z całego profilu w jednej liście z przejściem do
 * zakładki — potem stan w czterech liczbach, najnowsze rekrutacje, ludzie
 * klienta i raporty. Do 19.11.2026 lewa połowa ekranu stała pusta, a sprawy
 * były rozsiane po pięciu kartach w prawej kolumnie; rekrutacji nie było wcale.
 * Pełne listy i akcje zostają w zakładkach.
 */
export function ProfileTab({
  clientId,
  onOpen,
  showContracts,
  showInvoicing,
  deliveryLead,
  children,
}: Props) {
  // To samo zapytanie czyta nagłówek strony klienta i zakładka „Konsultanci”.
  const query = useClientProfile(clientId);
  const attention = useClientOverviewAttention(clientId, { showContracts });
  const { data } = query;
  // 403 ≠ awaria ≠ pusty profil — i awaria ma „Spróbuj ponownie” (audyt S10).
  const viewState = resolveViewState({
    isLoading: query.isPending,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });

  if (viewState === "loading") {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <div className="mr-2 h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        Ładowanie profilu...
      </div>
    );
  }

  if (isBlockingViewState(viewState) || !data) {
    return (
      <QueryStateNotice
        state={
          isBlockingViewState(viewState)
            ? (viewState as "forbidden" | "not_found" | "error")
            : "error"
        }
        description={viewState === "error" ? "Nie udało się wczytać profilu klienta." : undefined}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <div className="space-y-3">
      <AttentionPanel items={attention.items} onOpen={onOpen} />
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <PeopleStatCard data={data} onOpen={onOpen} />
        <JobsStatCard data={data} onOpen={onOpen} />
        {showInvoicing ? <InvoicingStatCard clientId={clientId} onOpen={onOpen} /> : null}
        {showContracts ? <FrameworkStatCard clientId={clientId} onOpen={onOpen} /> : null}
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-2 lg:items-start">
        <LatestJobsCard data={data} onOpen={onOpen} />
        <PeopleCard clientId={clientId} onOpen={onOpen} deliveryLead={deliveryLead} />
      </div>
      <div className="@container grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-2 lg:items-start xl:grid-cols-3">
        <ReportsCard clientId={clientId} onOpen={onOpen} />
        {children}
      </div>
    </div>
  );
}

/** „Wymaga uwagi · N” — pusta lista mówi to wprost, zamiast znikać. */
function AttentionPanel({
  items,
  onOpen,
}: {
  items: OverviewAttentionItem[];
  onOpen: (tab: ClientTab) => void;
}) {
  return (
    <section
      className="rounded-xl border border-border bg-card px-4 py-3 shadow-xs dark:bg-muted"
      aria-labelledby="client-overview-attention"
      data-tour="client.overview.attention"
    >
      <h2 id="client-overview-attention" className="text-sm font-semibold text-foreground">
        Wymaga uwagi{items.length > 0 ? ` · ${items.length}` : ""}
      </h2>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">
          Nic nie czeka: zamówienia, umowa, raporty i kluczowe osoby są w porządku.
        </p>
      ) : (
        <ul className="mt-1 divide-y divide-border">
          {items.map((item) => (
            <li key={item.key} className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 py-1.5">
              <StatusDot tone={item.tone} note={item.note} className="min-w-0">
                {item.label}
              </StatusDot>
              <button
                type="button"
                onClick={() => onOpen(item.tab)}
                className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                {CLIENT_SUBTAB_LABELS[item.tab]}
                <ArrowRight className="h-3 w-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
