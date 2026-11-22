"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Building2, CalendarDays, FolderOpen, Gauge, Gavel, Landmark, LineChart } from "lucide-react";

import { TabbedNav } from "@/components/ds";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AnalysisTab } from "./AnalysisTab";
import { BudgetTab } from "./BudgetTab";
import { DocumentsTab } from "./DocumentsTab";
import { MeetingsTab } from "./MeetingsTab";
import { PulpitTab } from "./PulpitTab";
import { RadaFirmaTab } from "./RadaFirmaTab";
import { VotesTab } from "./VotesTab";

// „Firma” Rady: od R7 (uwagi Rady 18.11.2026) własny, krótszy widok —
// placementy, kontraktorzy na projektach, zejścia z powodami i wnioski.
// Insights → Firma zostaje bez zmian dla Finansów i admina.
const TABS = [
  { value: "pulpit", label: "Pulpit", icon: LineChart },
  { value: "budzet", label: "Budżet", icon: Landmark },
  { value: "analiza", label: "Analiza", icon: Gauge },
  { value: "posiedzenia", label: "Posiedzenia", icon: CalendarDays },
  { value: "uchwaly", label: "Uchwały", icon: Gavel },
  { value: "firma", label: "Firma", icon: Building2 },
  { value: "dokumenty", label: "Dokumenty", icon: FolderOpen },
];

export function RadaView() {
  const router = useRouter();
  const params = useSearchParams();
  const requested = params.get("tab");
  const tab = TABS.some((t) => t.value === requested) ? (requested as string) : "pulpit";
  const go = (v: string) => router.replace(`/rada?tab=${v}`);
  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-4 sm:px-6">
      <header className="mb-3">
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Rada nadzorcza
        </p>
        <h1 className="text-xl font-semibold text-foreground">Rada</h1>
      </header>
      {/* Uwagi Rady z 19.11.2026: na telefonie siedem zakładek chowało się
          za krawędzią (widać było trzy) — tam wybór sekcji z listy. */}
      <div className="mb-2 sm:hidden">
        <Select value={tab} onValueChange={go}>
          <SelectTrigger aria-label="Sekcja Rady" className="h-10">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TABS.map((t) => (
              <SelectItem key={t.value} value={t.value}>
                {t.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <TabbedNav
        tabs={TABS}
        value={tab}
        onValueChange={go}
        ariaLabel="Sekcje Rady"
        className="max-sm:[&>div:first-child]:hidden"
      >
        <div className="pt-2 sm:pt-4">
          {tab === "pulpit" ? <PulpitTab /> : null}
          {tab === "budzet" ? <BudgetTab /> : null}
          {tab === "analiza" ? <AnalysisTab /> : null}
          {tab === "posiedzenia" ? <MeetingsTab /> : null}
          {tab === "uchwaly" ? <VotesTab /> : null}
          {tab === "firma" ? <RadaFirmaTab /> : null}
          {tab === "dokumenty" ? <DocumentsTab /> : null}
        </div>
      </TabbedNav>
    </div>
  );
}
