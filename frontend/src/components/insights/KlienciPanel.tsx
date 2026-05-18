"use client";

import { Building2, UserCheck, DollarSign, Users, AlertOctagon } from "lucide-react";

const PLANNED_SECTIONS = [
  {
    title: "Ranking klientów",
    description: "Lifetime/active revenue, margin, MSA status (z /admin/clients-overview)",
    icon: Building2,
  },
  {
    title: "DL Leaderboard",
    description: "Performance Delivery Leads (zmergowane z /reports.Delivery)",
    icon: UserCheck,
  },
  {
    title: "Sales overview",
    description: "MRR trend, ending contracts 30d, top clients",
    icon: DollarSign,
  },
  {
    title: "Top hiring managers",
    description: "Ranking osób po stronie klientów (z /admin/hiring-managers)",
    icon: Users,
  },
  {
    title: "At-risk clients",
    description: "Klienci wymagający uwagi (z /reports.Klienci)",
    icon: AlertOctagon,
  },
];

export function KlienciPanel() {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-dashed border-border bg-muted/30 p-6">
        <p className="text-sm font-medium text-foreground">
          Tab Klienci & Delivery — w przygotowaniu (PR 3)
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
