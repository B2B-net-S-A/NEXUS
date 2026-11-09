"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FileSignature } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { FilterBar } from "@/components/ds/FilterBar";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SERVICE_LINE_LABELS, useOpportunities } from "@/lib/api/sales";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";

import { formatDealNumber } from "./format";

/**
 * Sprzedaż → Oferty: szanse z wysłaną ofertą. NEXUS nie ma generatora ofert
 * (decyzja 26.10.2026), więc oferta to etap szansy, a plik leży przy szansie.
 */
export function OffersView() {
  const searchParams = useSearchParams();
  const { replaceUrl } = useUrlWriter();
  const [q, setQ] = useState(searchParams?.get("q") ?? "");
  const offers = useOpportunities({ offers_only: true, q, sort: "activity" });
  const items = offers.data?.items ?? [];
  const state = resolveViewState({
    isLoading: offers.isLoading,
    error: offers.error,
    isSuccess: offers.isSuccess,
    isEmpty: items.length === 0,
  });

  return (
    <div className="space-y-3">
      <FilterBar
        search={{
          value: q,
          onChange: (value) => {
            setQ(value);
            const trimmed = value.trim();
            replaceUrl(trimmed ? `${window.location.pathname}?q=${encodeURIComponent(trimmed)}` : window.location.pathname);
          },
          placeholder: "Szukaj oferty, firmy albo NIP…",
          ariaLabel: "Szukaj oferty",
        }}
        resultCount={offers.isSuccess ? offers.data?.total : undefined}
      />
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie ofert…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void offers.refetch()} />
      ) : state === "empty" ? (
        <EmptyState
          icon={FileSignature}
          title="Nie ma wysłanych ofert"
          description="Oferta pojawia się tu, gdy szansa wejdzie na etap „Oferta wysłana”."
        />
      ) : (
        <div className="relative overflow-x-auto">
          <Table className="min-w-[860px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Szansa</TableHead>
                <TableHead className={CALM_HEAD}>Model</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Wartość (zł)</TableHead>
                <TableHead className={CALM_HEAD}>Opiekun</TableHead>
                <TableHead className={CALM_HEAD}>Ostatnia aktywność</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.id} className={CALM_ROW}>
                  <TableCell>
                    <Link href={`/sales/opportunities/${item.id}`} className="font-medium text-foreground hover:underline">
                      {item.title}
                    </Link>
                    <p className={CALM_SUBLINE}>{item.company.name}</p>
                  </TableCell>
                  <TableCell>{item.service_line ? SERVICE_LINE_LABELS[item.service_line] : "—"}</TableCell>
                  <TableCell className={CALM_AMOUNT}>{formatDealNumber(item.value)}</TableCell>
                  <TableCell>{item.owner?.name ?? "—"}</TableCell>
                  <TableCell>{formatIsoDatePl(item.last_touch_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
