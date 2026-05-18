"use client";

import { Trophy, Briefcase, Link2, Award } from "lucide-react";

const PLANNED_SECTIONS = [
  {
    title: "Board KPI",
    description: "YTD placements/revenue/consultants + trendy (z /reports.Zarząd)",
    icon: Trophy,
  },
  {
    title: "Przetargi",
    description: "Win rate + lista (z /reports.Przetargi)",
    icon: Briefcase,
  },
  {
    title: "Invite Links",
    description: "Analytics linków aplikacyjnych (z /reports.Invite Links)",
    icon: Link2,
  },
  {
    title: "Champions podium",
    description: "Quarterly champions: DL i recruiter",
    icon: Award,
  },
];

export function ZarzadPanel() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-dashed border-border bg-muted/30 p-6">
        <p className="text-sm font-medium text-foreground">
          Tab Zarząd — w przygotowaniu (PR 4)
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
