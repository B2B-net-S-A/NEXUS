"use client";

import type { ReactNode } from "react";

import { PanelRow } from "@/components/v2/kpi/KpiGoalsPanel";
import { buildKpiTopbarModel } from "@/components/v2/kpi/kpi-topbar-model";
import { useMyGoals } from "@/hooks/useMyGoals";
import { useMyKpis } from "@/hooks/useMyKpis";
import { SectionError } from "@/components/insights/sections/_shared";

import { Panel, PanelLoading } from "../ViewKit";

/**
 * „Moje cele” — te same cele, tempo i liczby co licznik w górnym pasku
 * (`buildKpiTopbarModel`), rozłożone na ekran zamiast w dymku. Rekruter:
 * weryfikacje (dzień), rekomendacje (tydzień), placementy (miesiąc);
 * Delivery Lead: placementy portfela, hit ratio, zamknięte rekrutacje.
 *
 * `extra` to komórki spoza celów paska (np. precyzja rekrutera).
 */
export function MyGoalsPanel({
  title = "Moje cele",
  extra,
  footnote,
}: {
  title?: string;
  extra?: ReactNode;
  footnote?: ReactNode;
}) {
  const kpis = useMyKpis();
  const goals = useMyGoals();
  if (kpis.isPending) return <PanelLoading />;
  if (kpis.isError) {
    return (
      <SectionError label={title} error={kpis.error} onRetry={() => void kpis.refetch()} />
    );
  }
  const model = buildKpiTopbarModel(kpis.data ?? [], goals.data ?? null);
  const rows = model?.groups.flatMap((group) => group.rows) ?? [];
  if (rows.length === 0 && !extra) return null;
  return (
    <Panel title={title} hint={model?.panelAside ?? undefined}>
      <div className="grid grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2 xl:grid-cols-4">
        {rows.map((row) => (
          <PanelRow key={row.id} row={row} />
        ))}
        {extra}
      </div>
      {footnote ? <p className="text-xs text-muted-foreground">{footnote}</p> : null}
    </Panel>
  );
}
