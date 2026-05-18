"use client";

import { Activity, BarChart3, Clock, AlertTriangle, Target } from "lucide-react";

const PLANNED_SECTIONS = [
  {
    title: "Activity heatmap",
    description: "Aktywność rekruterów × typ aktywności (zastępuje /analytics)",
    icon: Activity,
  },
  {
    title: "Funnel kandydatów",
    description: "Konwersja per stage (zastępuje /analytics/pipeline + /reports.Rekrutacja)",
    icon: BarChart3,
  },
  {
    title: "Time-to-hire",
    description: "Mediana + P90 per recruiter (180 dni lookback)",
    icon: Clock,
  },
  {
    title: "SLA Alerts",
    description: "Kandydaci overdue w pipeline",
    icon: AlertTriangle,
  },
  {
    title: "Sources funnel",
    description: "Źródła kandydatów + UTM (zastępuje /reports/sources)",
    icon: Target,
  },
];

export function RekrutacjaPanel() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-dashed border-border bg-muted/30 p-6">
        <p className="text-sm font-medium text-foreground">
          Tab Rekrutacja — w przygotowaniu (PR 2)
        </p>
        <p className="text-xs text-muted-foreground mt-1">
          Planowane sekcje, które trafią do tego widoku:
        </p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {PLANNED_SECTIONS.map((s) => {
          const Icon = s.icon;
          return (
            <div
              key={s.title}
              className="rounded-lg border border-border bg-card p-4"
            >
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 text-primary" />
                <p className="text-sm font-medium text-foreground">{s.title}</p>
              </div>
              <p className="text-xs text-muted-foreground mt-2">{s.description}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
