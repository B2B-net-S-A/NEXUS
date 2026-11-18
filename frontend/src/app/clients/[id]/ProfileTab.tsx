"use client";

import { AlertTriangle, ArrowRight, Users } from "lucide-react";
import { useClientProfile } from "@/components/client-profile/useClientProfile";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { formatDate, type ActiveConsultantItem } from "@/types/client-profile";

interface Props {
  clientId: number;
  /** Przejście do zakładki „Konsultanci” (pełna lista i akcje). */
  onOpenConsultants?: () => void;
}

/** Ile osób z „Wymaga uwagi” pokazuje Przegląd; resztę ma zakładka. */
const ATTENTION_PREVIEW = 5;

function attentionText(row: ActiveConsultantItem): string {
  const codes = row.attention ?? [];
  if (codes.includes("no_current_order")) {
    return row.order_end_date
      ? `brak bieżącego zamówienia (ostatnie do ${formatDate(row.order_end_date)})`
      : "brak zamówienia";
  }
  if (codes.includes("order_ending")) {
    return row.order_ending_on
      ? `zamówienie bez kontynuacji po ${formatDate(row.order_ending_on)}`
      : "zamówienie bez kontynuacji";
  }
  return "umowa wypowiedziana";
}

/**
 * Przegląd klienta: karta „Konsultanci” — liczby i osoby, które wymagają
 * uwagi. Pełna lista z umową, zamówieniem, stawkami i akcjami jest w zakładce
 * „Konsultanci” (decyzja Artura 18.11.2026); do 18.11 stała tu cała tabela
 * Obecni / Planowani / Archiwum.
 *
 * Profil NIE pokazuje rekrutacji w żadnej formie — wszystkie rekrutacje klienta
 * żyją w zakładce Projekty. Powód i notatka przegranej (`close_reason` /
 * `close_notes`) nie mają w aplikacji widoku — znany, świadomie odłożony brak.
 */
export function ProfileTab({ clientId, onOpenConsultants }: Props) {
  // To samo zapytanie czyta nagłówek strony klienta (liczby „Aktywni
  // konsultanci” i „Aktywne MRR”) i zakładka „Konsultanci” — jeden klucz.
  const query = useClientProfile(clientId);
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

  const attention = data.active_consultants.filter((row) => (row.attention?.length ?? 0) > 0);
  const planned = data.planned_consultants?.length ?? 0;
  const pending = data.pending_consultants?.length ?? 0;

  return (
    <section
      className="space-y-3 rounded-xl border border-border bg-card p-4 dark:bg-muted"
      aria-labelledby="client-consultants-summary"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="client-consultants-summary" className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Users className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          Konsultanci
        </h2>
        {onOpenConsultants ? (
          <Button size="sm" variant="outline" onClick={onOpenConsultants}>
            Wszyscy konsultanci <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        ) : null}
      </div>
      <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <div className="flex items-baseline gap-1.5">
          <dt className="text-muted-foreground">Obecni</dt>
          <dd className="font-semibold tabular-nums">{data.active_consultants.length}</dd>
        </div>
        <div className="flex items-baseline gap-1.5">
          <dt className="text-muted-foreground">Wymaga uwagi</dt>
          <dd className={attention.length > 0 ? "font-semibold tabular-nums text-warning-muted-foreground" : "font-semibold tabular-nums"}>
            {attention.length}
          </dd>
        </div>
        <div className="flex items-baseline gap-1.5">
          <dt className="text-muted-foreground">Planowani</dt>
          <dd className="font-semibold tabular-nums">{planned}</dd>
        </div>
        {pending > 0 ? (
          <div className="flex items-baseline gap-1.5">
            <dt className="text-muted-foreground">Szkice</dt>
            <dd className="font-semibold tabular-nums">{pending}</dd>
          </div>
        ) : null}
        <div className="flex items-baseline gap-1.5">
          <dt className="text-muted-foreground">Zakończeni</dt>
          <dd className="font-semibold tabular-nums">{data.historical.placements_total ?? data.historical.placements.length}</dd>
        </div>
      </dl>
      {attention.length > 0 ? (
        <ul className="space-y-1 text-sm">
          {attention.slice(0, ATTENTION_PREVIEW).map((row) => (
            <li key={row.contract_id} className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden="true" />
              <span>
                <span className="font-medium">{row.candidate.name}</span>
                <span className="text-muted-foreground"> — {attentionText(row)}</span>
              </span>
            </li>
          ))}
          {attention.length > ATTENTION_PREVIEW ? (
            <li className="text-xs text-muted-foreground">
              i {attention.length - ATTENTION_PREVIEW} więcej w zakładce „Konsultanci”
            </li>
          ) : null}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">Nikt u tego klienta nie wymaga teraz uwagi.</p>
      )}
    </section>
  );
}
