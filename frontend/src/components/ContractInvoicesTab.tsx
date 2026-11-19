"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatIsoDatePl as formatDate } from "@/lib/date-pl";
import { formatCurrency } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";

/** Wiersz `GET /api/contracts/{id}/contractor-invoices` (kwoty jako tekst albo `null`). */
export interface ContractorInvoice {
  id: number;
  ksef_number: string;
  invoice_number: string | null;
  invoice_type: string | null;
  is_correction: boolean;
  issue_date: string | null;
  period_month: string | null;
  nip_state: string;
  net_amount: string | null;
  gross_amount: string | null;
  currency: string;
}

interface ContractorInvoicesResponse {
  contract_id: number;
  client_id: number;
  invoices: ContractorInvoice[];
}

const NIP_STATE_LABELS: Record<string, string> = {
  known: "z kontraktu",
  confirmed: "zatwierdzony",
  suggested: "do zatwierdzenia",
};

/** „2026-10” → „10.2026”. */
export function formatPeriodMonth(month: string | null): string {
  const match = month ? /^(\d{4})-(\d{2})$/.exec(month) : null;
  return match ? `${match[2]}.${match[1]}` : "—";
}

/** Karta osoby w Finanse → Rozliczenia za ten miesiąc (parametry `SettlementsTab`). */
export function settlementsMonthHref(
  clientId: number,
  contractId: number,
  month: string,
): string {
  const params = new URLSearchParams({
    view: "settlements",
    stClient: String(clientId),
    stMonth: month,
    stContract: String(contractId),
  });
  return `/finance?${params.toString()}`;
}

function money(value: string | null, currency: string): string {
  return value == null ? "—" : formatCurrency(Number(value), currency);
}

/**
 * Faktury konsultanta z KSeF (decyzja Artura 19.11.2026): te same faktury co
 * na karcie osoby w Finanse → Rozliczenia, ze wszystkich miesięcy kontraktu.
 * Tylko do odczytu — fakturę wystawia konsultant w KSeF, a NEXUS ją pobiera.
 * Do 19.11 zakładka czytała ręczny rejestr `/api/invoices` z „Dodaj fakturę”,
 * który na produkcji nie miał ani jednego wiersza.
 */
export function ContractInvoicesTab({ contractId }: { contractId: number }) {
  const query = useQuery<ContractorInvoicesResponse>({
    queryKey: ["contract-contractor-invoices", contractId],
    queryFn: () =>
      api
        .get(`/api/contracts/${contractId}/contractor-invoices`)
        .then((r) => r.data),
  });
  const invoices = query.data?.invoices ?? [];
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: invoices.length === 0,
  });

  if (viewState === "loading") {
    return (
      <div className="text-sm text-muted-foreground flex items-center gap-2">
        <Loader2 className="w-4 h-4 animate-spin" /> Ładowanie faktur…
      </div>
    );
  }
  if (viewState === "forbidden" || viewState === "not_found" || viewState === "error") {
    return (
      <QueryStateNotice
        state={viewState}
        description={apiErrorMessage(
          query.error,
          "Nie udało się wczytać faktur konsultanta z KSeF.",
        )}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (viewState === "empty" || !query.data) {
    return (
      <div className="text-sm text-muted-foreground bg-card dark:bg-muted rounded-2xl p-6 text-center shadow-xs">
        Brak faktur konsultanta w KSeF dla tego kontraktu.
      </div>
    );
  }

  const { client_id: clientId } = query.data;
  const latestMonth = invoices.find((inv) => inv.period_month)?.period_month ?? null;

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-foreground">Faktury konsultanta z KSeF</h3>
      <div className="bg-card dark:bg-muted rounded-2xl shadow-xs overflow-x-auto">
        <table className="w-full min-w-[44rem] text-sm">
          <thead className="bg-muted dark:bg-muted/40 text-xs uppercase text-muted-foreground">
            <tr>
              <th className="text-left px-3 py-2">Miesiąc</th>
              <th className="text-left px-3 py-2">Numer</th>
              <th className="text-left px-3 py-2">Rodzaj</th>
              <th className="text-left px-3 py-2">Wystawiona</th>
              <th className="text-right px-3 py-2">Netto</th>
              <th className="text-right px-3 py-2">Brutto</th>
              <th className="text-left px-3 py-2">NIP</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.id} className="border-t border-border">
                <td className="px-3 py-2 whitespace-nowrap">
                  {inv.period_month ? (
                    <Link
                      href={settlementsMonthHref(clientId, contractId, inv.period_month)}
                      className="text-primary hover:underline"
                      title="Otwórz miesiąc w Rozliczeniach"
                    >
                      {formatPeriodMonth(inv.period_month)}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="font-medium">{inv.invoice_number ?? "—"}</div>
                  <div className="text-xs text-muted-foreground break-all">{inv.ksef_number}</div>
                </td>
                <td className="px-3 py-2">{inv.is_correction ? "Korekta" : "Faktura"}</td>
                <td className="px-3 py-2 whitespace-nowrap">{formatDate(inv.issue_date)}</td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {money(inv.net_amount, inv.currency)}
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap">
                  {money(inv.gross_amount, inv.currency)}
                </td>
                <td
                  className={`px-3 py-2 whitespace-nowrap ${inv.nip_state === "suggested" ? "text-warning font-medium" : "text-muted-foreground"}`}
                >
                  {NIP_STATE_LABELS[inv.nip_state] ?? inv.nip_state}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Kontrole faktury (kwota z RCP, korekty, biała lista VAT) i termin płatności są na karcie
        osoby w Rozliczeniach.
        {latestMonth && (
          <>
            {" "}
            <Link
              href={settlementsMonthHref(clientId, contractId, latestMonth)}
              className="font-medium text-primary hover:underline"
            >
              Otwórz {formatPeriodMonth(latestMonth)} w Rozliczeniach →
            </Link>
          </>
        )}
      </p>
    </div>
  );
}
