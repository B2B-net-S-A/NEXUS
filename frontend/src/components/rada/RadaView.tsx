"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Building2, CalendarDays, FolderOpen, Gauge, Landmark, LineChart } from "lucide-react";

import { TabbedNav } from "@/components/ds";
import { FirmaView } from "@/components/insights/views/FirmaView";
import { AnalysisTab } from "./AnalysisTab";
import { BudgetTab } from "./BudgetTab";
import { DocumentsTab } from "./DocumentsTab";
import { MeetingsTab } from "./MeetingsTab";
import { PulpitTab } from "./PulpitTab";

// „Firma” to ten sam widok co w Insights (decyzja Artura 16.11.2026: Rada
// przejmuje go z Insights, które znika z jej menu).
const TABS = [
  { value: "pulpit", label: "Pulpit", icon: LineChart },
  { value: "budzet", label: "Budżet", icon: Landmark },
  { value: "analiza", label: "Analiza", icon: Gauge },
  { value: "posiedzenia", label: "Posiedzenia", icon: CalendarDays },
  { value: "firma", label: "Firma", icon: Building2 },
  { value: "dokumenty", label: "Dokumenty", icon: FolderOpen },
];

export function RadaView() {
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get("tab");
  const tab = TABS.some((t) => t.value === requested) ? (requested as string) : "pulpit";
  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-4 sm:px-6">
      <header className="mb-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Rada nadzorcza
        </p>
        <h1 className="text-xl font-semibold text-foreground">Rada</h1>
      </header>
      <TabbedNav
        tabs={TABS}
        value={tab}
        onValueChange={(v) => router.replace(`/rada?tab=${v}`)}
        ariaLabel="Sekcje Rady"
      >
        <div className="pt-4">
          {tab === "pulpit" ? <PulpitTab /> : null}
          {tab === "budzet" ? <BudgetTab /> : null}
          {tab === "analiza" ? <AnalysisTab /> : null}
          {tab === "posiedzenia" ? <MeetingsTab /> : null}
          {tab === "firma" ? <FirmaView /> : null}
          {tab === "dokumenty" ? <DocumentsTab /> : null}
        </div>
      </TabbedNav>
    </div>
  );
}
