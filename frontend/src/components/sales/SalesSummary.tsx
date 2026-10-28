"use client";

import Link from "next/link";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatCard } from "@/components/ds/StatCard";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { usePipelines, useSalesSummary, type SummaryPeriod } from "@/lib/api/sales";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

import { formatDealAmount, formatDealNumber } from "./format";
import { SalesSelect } from "./SalesSelect";

const STALE_DAYS = 14;
const PERIODS: { value: SummaryPeriod; label: string }[] = [
  { value: "all", label: "Cały otwarty lejek" },
  { value: "quarter", label: "Zamknięcie w tym kwartale" },
  { value: "next_quarter", label: "W następnym kwartale" },
];

/**
 * Sprzedaż → Podsumowanie (zamiast pulpitu Atlasa): otwarte szanse lejka,
 * wartość, prognoza ważona, zespół i etapy. Definicje 1:1 z Atlasa
 * (`sales_dashboard_service.py`), liczone w API — bez limitu strony.
 */
export function SalesSummary() {
  const pipelines = usePipelines();
  const [pipelineId, setPipelineId] = useState("");
  const [period, setPeriod] = useState<SummaryPeriod>("all");
  const summary = useSalesSummary(pipelineId ? Number(pipelineId) : null, period);
  const data = summary.data;
  const state = resolveViewState({
    isLoading: summary.isLoading,
    error: summary.error,
    isSuccess: summary.isSuccess,
  });
  const total = Number(data?.value ?? 0) || 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <SalesSelect
          ariaLabel="Lejek"
          className="w-48"
          value={pipelineId || (data ? String(data.pipeline.id) : "")}
          onValueChange={setPipelineId}
          options={(pipelines.data ?? []).map((pipeline) => ({ value: String(pipeline.id), label: pipeline.name }))}
        />
        <SalesSelect
          ariaLabel="Okres"
          className="w-56"
          value={period}
          onValueChange={(value) => setPeriod((value || "all") as SummaryPeriod)}
          options={PERIODS}
        />
      </div>
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void summary.refetch()} />
      ) : data ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Otwarte szanse" value={data.open_count} sub={data.pipeline.name} />
            <StatCard label="Wartość lejka" value={formatDealAmount(data.value)} />
            <StatCard label="Prognoza ważona" value={formatDealAmount(data.weighted)} />
            <StatCard label={`Bez ruchu > ${STALE_DAYS} dni`} value={data.stale_count} sub="szanse bez aktywności" />
          </div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
            <Card className="min-w-0 p-4">
              <h2 className="mb-2 text-base font-semibold text-foreground">Zespół</h2>
              <div className="overflow-x-auto">
                <Table className="min-w-[620px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead className={CALM_HEAD}>Opiekun</TableHead>
                      <TableHead className={`${CALM_HEAD} text-right`}>Otwarte</TableHead>
                      <TableHead className={`${CALM_HEAD} text-right`}>Wartość (zł)</TableHead>
                      <TableHead className={`${CALM_HEAD} text-right`}>Ważona (zł)</TableHead>
                      <TableHead className={`${CALM_HEAD} text-right`}>Bez ruchu</TableHead>
                      <TableHead className={`${CALM_HEAD} text-right`}>Bez daty zamknięcia</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.by_owner.map((row) => (
                      <TableRow key={row.owner?.id ?? "none"} className={CALM_ROW}>
                        <TableCell className="font-medium">
                          {row.owner ? (
                            <Link
                              href={`/sales?opiekun=${row.owner.id}`}
                              className="hover:underline"
                            >
                              {row.owner.name}
                            </Link>
                          ) : (
                            "Bez opiekuna"
                          )}
                        </TableCell>
                        <TableCell className={CALM_AMOUNT}>{row.open}</TableCell>
                        <TableCell className={CALM_AMOUNT}>{formatDealNumber(row.value)}</TableCell>
                        <TableCell className={CALM_AMOUNT}>{formatDealNumber(row.weighted)}</TableCell>
                        <TableCell className={`${CALM_AMOUNT} ${row.stale ? "text-warning" : ""}`}>{row.stale}</TableCell>
                        <TableCell className={CALM_AMOUNT}>{row.no_close}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
            <Card className="p-4">
              <h2 className="mb-2 text-base font-semibold text-foreground">Etapy</h2>
              <ul className="space-y-1.5 text-sm">
                {data.by_stage.map((row) => {
                  const value = Number(row.value) || 0;
                  const width = total ? Math.max(2, Math.round((value / total) * 100)) : 0;
                  return (
                    <li key={row.stage.id}>
                      <div className="flex justify-between gap-2">
                        <span className="truncate">{row.stage.name}</span>
                        <span className="tabular-nums text-muted-foreground">
                          {row.count} · {formatDealNumber(value)}
                        </span>
                      </div>
                      <div className="mt-0.5 h-1.5 rounded-full bg-muted">
                        <div className="h-1.5 rounded-full bg-primary" style={{ width: `${width}%` }} />
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}
