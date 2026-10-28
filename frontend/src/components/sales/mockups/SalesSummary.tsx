"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatCard } from "@/components/ds/StatCard";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useOpportunities, usePipelines, type Opportunity } from "@/lib/api/sales";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

import { daysSince, formatDealAmount, formatDealNumber } from "../format";
import { SalesSelect } from "../SalesSelect";

const STALE_DAYS = 14;
const num = (value: string | null) => Number(value ?? 0) || 0;

interface OwnerRow {
  name: string;
  open: number;
  value: number;
  weighted: number;
  mrr: number;
  stale: number;
  noClose: number;
}

function byOwner(items: Opportunity[]): OwnerRow[] {
  const rows = new Map<string, OwnerRow>();
  for (const opp of items) {
    const name = opp.owner?.name ?? "Bez opiekuna";
    const row = rows.get(name) ?? { name, open: 0, value: 0, weighted: 0, mrr: 0, stale: 0, noClose: 0 };
    row.open += 1;
    row.value += num(opp.value);
    row.weighted += num(opp.weighted_value);
    row.mrr += num(opp.mrr_value);
    if ((daysSince(opp.last_activity_at ?? opp.updated_at) ?? 0) > STALE_DAYS) row.stale += 1;
    if (!opp.expected_close_date) row.noClose += 1;
    rows.set(name, row);
  }
  return [...rows.values()].sort((a, b) => b.value - a.value);
}

/** MAKIETA: Sprzedaż → Podsumowanie (zamiast pulpitu Atlasa) — liczone z otwartych szans lejka. */
export function SalesSummary() {
  const pipelines = usePipelines();
  const [pipelineId, setPipelineId] = useState("");
  const selected =
    pipelines.data?.find((pipeline) => String(pipeline.id) === pipelineId) ??
    pipelines.data?.find((pipeline) => pipeline.is_default);
  const opportunities = useOpportunities({ pipeline_id: selected?.id, status: "open" }, Boolean(selected));
  const items = opportunities.data?.items ?? [];
  const state = resolveViewState({
    isLoading: opportunities.isLoading || pipelines.isLoading,
    error: opportunities.error ?? pipelines.error,
    isSuccess: opportunities.isSuccess,
  });
  const owners = byOwner(items);
  const total = owners.reduce(
    (acc, row) => ({
      value: acc.value + row.value,
      weighted: acc.weighted + row.weighted,
      mrr: acc.mrr + row.mrr,
      stale: acc.stale + row.stale,
    }),
    { value: 0, weighted: 0, mrr: 0, stale: 0 },
  );
  const stages = (selected?.stages ?? []).filter((stage) => stage.outcome === "open");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <SalesSelect
          ariaLabel="Lejek"
          className="w-48"
          value={selected ? String(selected.id) : ""}
          onValueChange={setPipelineId}
          options={(pipelines.data ?? []).map((pipeline) => ({ value: String(pipeline.id), label: pipeline.name }))}
        />
        <SalesSelect
          ariaLabel="Okres"
          className="w-48"
          value="all"
          onValueChange={() => undefined}
          options={[
            { value: "all", label: "Cały otwarty lejek" },
            { value: "q", label: "Zamknięcie w tym kwartale" },
            { value: "nq", label: "W następnym kwartale" },
          ]}
        />
      </div>
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void opportunities.refetch()} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Otwarte szanse" value={items.length} sub={selected?.name} />
            <StatCard label="Wartość lejka" value={formatDealAmount(total.value)} />
            <StatCard label="Prognoza ważona" value={formatDealAmount(total.weighted)} />
            <StatCard
              label={`Bez ruchu > ${STALE_DAYS} dni`}
              value={total.stale}
              sub="szanse bez aktywności"
            />
          </div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
            <Card className="p-4">
              <h2 className="mb-2 text-base font-semibold text-foreground">Zespół</h2>
              <Table>
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
                  {owners.map((row) => (
                    <TableRow key={row.name} className={CALM_ROW}>
                      <TableCell className="font-medium">{row.name}</TableCell>
                      <TableCell className={CALM_AMOUNT}>{row.open}</TableCell>
                      <TableCell className={CALM_AMOUNT}>{formatDealNumber(row.value)}</TableCell>
                      <TableCell className={CALM_AMOUNT}>{formatDealNumber(row.weighted)}</TableCell>
                      <TableCell className={`${CALM_AMOUNT} ${row.stale ? "text-warning" : ""}`}>{row.stale}</TableCell>
                      <TableCell className={CALM_AMOUNT}>{row.noClose}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
            <Card className="p-4">
              <h2 className="mb-2 text-base font-semibold text-foreground">Etapy</h2>
              <ul className="space-y-1.5 text-sm">
                {stages.map((stage) => {
                  const inStage = items.filter((opp) => opp.stage.id === stage.id);
                  const value = inStage.reduce((sum, opp) => sum + num(opp.value), 0);
                  const width = total.value ? Math.max(2, Math.round((value / total.value) * 100)) : 0;
                  return (
                    <li key={stage.id}>
                      <div className="flex justify-between gap-2">
                        <span className="truncate">{stage.name}</span>
                        <span className="tabular-nums text-muted-foreground">
                          {inStage.length} · {formatDealNumber(value)}
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
      )}
    </div>
  );
}
