"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Building2, Crown, Loader2, Users, Wallet } from "lucide-react";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { Degraded, KpiCard, SectionError } from "./_shared";
import { count, DefinitionNote, money } from "./InsightsFormat";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Ranking klientów na `/api/insights/clients/ranking`.
 *
 * Zastępuje `ClientsRanking.tsx`, który czytał `/api/admin/clients-overview`.
 * Tamten endpoint stoi na `FinanceReadUser`, a `/insights` jest po D7 otwarte
 * dla KAŻDEJ zalogowanej roli — więc dla większości firmy sekcja kończyła się
 * czerwonym „Błąd ładowania rankingu klientów.". 403 renderowany jako awaria
 * bez wyjaśnienia jest gorszy niż brak sekcji: czyta się jak utrata danych.
 *
 * Kafle są FOLDEM po tej samej liście, którą pokazuje tabela (koperta
 * `totals`), więc „Suma marży" da się sprawdzić dodając kolumnę na ekranie.
 * Dlatego tabela renderuje WSZYSTKIE wiersze w kontenerze ze scrollem, a nie
 * `slice(0, 10)` — kafel nad przyciętą listą nie daje się zweryfikować.
 */
export function InsightsClientsRanking({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.clientsRanking(period),
    queryFn: () => insightsBoardApi.clientsRanking(period),
  });

  const clients = data?.clients ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: clients.length === 0,
  });

  const totals = data?.totals;
  const incomplete: string[] = [];
  if (totals && !totals.revenue_complete) {
    incomplete.push(
      "Część przychodów nie została policzona (brak kursu NBP) — kwoty tych " +
        "wierszy nie wchodzą do kafli.",
    );
  }
  if (totals && !totals.monthly_margin_complete) {
    incomplete.push(
      "Część marż nie została policzona — wiersz pokazuje „—”, a kafel liczy " +
        "go jako zero. Suma jest zaniżona, nie równa zeru.",
    );
  }

  return (
    <section className="space-y-3">
      <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <Building2 className="h-5 w-5 text-primary" />
        Ranking klientów
        {data && (
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            Wycena na {data.valuation.on}
          </span>
        )}
      </h2>

      {viewState === "loading" ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Ranking klientów"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" || !data || !totals ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Brak klientów z żywymi kontraktami.
        </p>
      ) : (
        <>
          <div
            role="group"
            aria-label="Kafle rankingu klientów"
            className="grid grid-cols-2 gap-4 md:grid-cols-4"
          >
            <KpiCard
              label="Aktywne MRR / mc"
              value={money(totals.active_revenue)}
              sub={`${count(totals.active_clients)} klientów z konsultantem`}
              icon={Wallet}
              color="green"
            />
            <KpiCard
              label="Marża / mc"
              value={money(totals.monthly_margin_total)}
              sub="Suma kolumny „Marża/mc”"
              icon={Wallet}
              color="blue"
            />
            <KpiCard
              label="Przychód lifetime"
              value={money(totals.total_revenue_all_time)}
              sub="Nieprzycinany oknem — z definicji cała historia"
              icon={Wallet}
              color="purple"
            />
            <KpiCard
              label="Konsultanci"
              value={count(totals.active_consultants)}
              sub={`${count(totals.active_contracts)} kontraktów · ${count(
                totals.active_orders_count,
              )} zamówień`}
              icon={Users}
              color="indigo"
            />
          </div>

          {incomplete.length > 0 && (
            <Degraded reason={incomplete} status="partial" />
          )}

          <DefinitionNote>{data.valuation.note}</DefinitionNote>

          <div className="max-h-[32rem] overflow-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 border-b border-border bg-muted">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">#</th>
                  <th className="px-3 py-2 text-left font-medium">Klient</th>
                  <th className="px-3 py-2 text-left font-medium">Head DL</th>
                  <th className="px-3 py-2 text-right font-medium">
                    Przychód lifetime
                  </th>
                  <th className="px-3 py-2 text-right font-medium">
                    Aktywne / mc
                  </th>
                  <th className="px-3 py-2 text-right font-medium">Marża/mc</th>
                  <th className="px-3 py-2 text-right font-medium">
                    Zamówienia
                  </th>
                  <th className="px-3 py-2 text-right font-medium">
                    Konsultanci / kontrakty
                  </th>
                  <th className="px-3 py-2 text-left font-medium">MSA</th>
                </tr>
              </thead>
              <tbody>
                {clients.map((r, idx) => (
                  <tr
                    key={r.client_id}
                    className="border-b border-border hover:bg-accent/30"
                  >
                    <td className="px-3 py-2 text-muted-foreground">
                      {idx + 1}
                    </td>
                    <td className="px-3 py-2">
                      <Link
                        href={`/clients/${r.client_id}?tab=analityka`}
                        className="flex items-center gap-1 font-medium hover:text-primary"
                      >
                        <Building2 className="h-3.5 w-3.5 text-muted-foreground" />
                        {r.name}
                      </Link>
                      {r.industry && (
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {r.industry}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.head_dl_name ? (
                        <span className="flex items-center gap-1">
                          <Crown className="h-3 w-3 text-primary" />
                          {r.head_dl_name}
                        </span>
                      ) : (
                        <span className="italic text-muted-foreground">
                          brak
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right font-medium tabular-nums">
                      {money(r.total_revenue_all_time)}
                      {!r.revenue_complete && (
                        <IncompleteMark title="Brak kursu NBP — kwota niepełna." />
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-green-700 dark:text-green-400">
                      {money(r.active_revenue)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-primary">
                      {money(r.monthly_margin_total)}
                      {!r.margin_complete && (
                        <IncompleteMark title="Marża niepełna — brak kursu albo brak stawki kandydata." />
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {r.active_orders_count}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {r.active_consultants} / {r.active_contracts}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {r.framework_status ? (
                        <>
                          {r.framework_status}
                          {r.framework_expiry_date && (
                            <div className="text-muted-foreground">
                              do {r.framework_expiry_date}
                            </div>
                          )}
                        </>
                      ) : (
                        <span className="italic text-muted-foreground">
                          brak
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

/** Znacznik przy kwocie, której nie policzono w całości. */
function IncompleteMark({ title }: { title: string }) {
  return (
    <span
      className="ml-1 cursor-help text-amber-600 dark:text-amber-400"
      title={title}
      aria-label={title}
    >
      *
    </span>
  );
}
