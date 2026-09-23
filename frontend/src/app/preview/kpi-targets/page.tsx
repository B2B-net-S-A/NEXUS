"use client";

/**
 * Harness „Cele KPI" (plan PR3) — prawdziwy `KpiTargetsSettings` na zasianym
 * cache'u, ZERO zapytań przy ładowaniu (strażnik: `harness-seeds.test.ts`).
 * Zapis w polu uderzyłby w prawdziwe API (401) — to harness wyglądu, nie flow.
 */

import { useMemo } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { KpiTargetsSettings } from "@/components/settings/KpiTargetsSettings";
import type { KpiTargetEvent, KpiTargetsMatrix } from "@/lib/api/kpiTargets";

const KPIS: KpiTargetsMatrix["kpis"] = [
  { kpi_id: "daily_first_verifications", title: "Weryfikacje dziś", description: "", period: "day", period_label: "dziennie", race_threshold: true },
  { kpi_id: "daily_new_candidates", title: "Nowi kandydaci dziś", description: "", period: "day", period_label: "dziennie", race_threshold: false },
  { kpi_id: "weekly_cvs_sent", title: "Rekomendacje w tygodniu", description: "", period: "week", period_label: "tygodniowo", race_threshold: false },
  { kpi_id: "monthly_placements", title: "Placementy w tym miesiącu", description: "", period: "month", period_label: "miesięcznie", race_threshold: false },
  { kpi_id: "monthly_precision", title: "Precyzja (30 dni)", description: "", period: "month", period_label: "miesięcznie", race_threshold: true },
];

const CATALOG: Record<string, Record<string, number>> = {
  recruiter: { daily_first_verifications: 4, daily_new_candidates: 5, weekly_cvs_sent: 15, monthly_placements: 1, monthly_precision: 75 },
  sourcer: { daily_first_verifications: 4, daily_new_candidates: 5, weekly_cvs_sent: 0, monthly_placements: 1, monthly_precision: 75 },
  tac: { daily_first_verifications: 4, daily_new_candidates: 5, weekly_cvs_sent: 12, monthly_placements: 1, monthly_precision: 75 },
};

function roleCells(role: string, overrides: Record<string, number> = {}) {
  return Object.fromEntries(
    KPIS.map((kpi) => {
      const catalog = CATALOG[role][kpi.kpi_id];
      const override = overrides[kpi.kpi_id] ?? null;
      return [kpi.kpi_id, { catalog_default: catalog, override, effective: override ?? catalog }];
    }),
  );
}

function userCells(base: Record<string, number>, personal: Record<string, number> = {}) {
  return Object.fromEntries(
    KPIS.map((kpi) => {
      const override = personal[kpi.kpi_id] ?? null;
      return [
        kpi.kpi_id,
        { effective: override ?? base[kpi.kpi_id], override, source: (override === null ? "role" : "user") as "role" | "user" },
      ];
    }),
  );
}

const MATRIX: KpiTargetsMatrix = {
  kpis: KPIS,
  roles: [
    { role: "recruiter", label: "Rekruter", targets: roleCells("recruiter", { weekly_cvs_sent: 18 }) },
    { role: "sourcer", label: "Sourcer", targets: roleCells("sourcer") },
    { role: "tac", label: "TAC", targets: roleCells("tac") },
  ],
  users: [
    { user_id: 1, name: "Anna Kowalska", roles: ["recruiter"], targets: userCells({ ...CATALOG.recruiter, weekly_cvs_sent: 18 }, { monthly_placements: 2 }) },
    { user_id: 2, name: "Piotr Nowak", roles: ["sourcer"], targets: userCells(CATALOG.sourcer) },
    { user_id: 3, name: "Ewa Wiśniewska", roles: ["recruiter", "tac"], targets: userCells({ ...CATALOG.recruiter, weekly_cvs_sent: 18 }) },
  ],
};

const HISTORY: KpiTargetEvent[] = [
  { id: 2, scope: "user", role: null, role_label: null, subject_user_id: 1, subject_name: "Anna Kowalska", kpi_id: "monthly_placements", kpi_title: "Placementy w tym miesiącu", action: "set", from_value: null, to_value: 2, actor_name: "Dominik Zieliński", created_at: "2026-09-23T09:12:00+02:00" },
  { id: 1, scope: "role", role: "recruiter", role_label: "Rekruter", subject_user_id: null, subject_name: null, kpi_id: "weekly_cvs_sent", kpi_title: "Rekomendacje w tygodniu", action: "set", from_value: null, to_value: 18, actor_name: "Dominik Zieliński", created_at: "2026-09-22T16:40:00+02:00" },
];

export default function KpiTargetsPreviewPage() {
  const queryClient = useMemo(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, retryOnMount: false, staleTime: Infinity } },
    });
    qc.setQueryData(["kpi-targets"], MATRIX);
    qc.setQueryData(["kpi-targets", "history"], HISTORY);
    return qc;
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <main className="mx-auto max-w-7xl space-y-6 bg-background p-6">
        <h1 className="text-2xl font-bold text-foreground">Cele KPI — podgląd</h1>
        <KpiTargetsSettings />
      </main>
    </QueryClientProvider>
  );
}
