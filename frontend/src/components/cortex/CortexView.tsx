"use client";

import { useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Gauge, Grid3x3 } from "lucide-react";
import { cn } from "@/lib/utils";
import { RequireRole } from "@/components/RequireRole";
import { CoveragePanel } from "@/components/cortex/CoveragePanel";
import { TechMapPanel } from "@/components/cortex/TechMapPanel";
import type { UserRole } from "@/store/auth";

// RODO gate: widoki agregują dane kompetencyjne kandydatów — ten sam zestaw
// ról co zakładka "Klienci & Delivery" w Insights i backendowy CortexUser.
export const CORTEX_ROLES: UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "tac",
];

type TabId = "tech" | "coverage";

type TabDef = {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
};

const TABS: TabDef[] = [
  { id: "tech", label: "Mapa technologiczna", icon: Grid3x3 },
  { id: "coverage", label: "Jakość danych", icon: Gauge },
];

const DEFAULT_TAB: TabId = "tech";

function isTabId(v: string | null): v is TabId {
  return v === "tech" || v === "coverage";
}

export function CortexView() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const rawTab = searchParams.get("tab");
  const activeTab: TabId = useMemo(
    () => (isTabId(rawTab) ? rawTab : DEFAULT_TAB),
    [rawTab]
  );

  useEffect(() => {
    if (!rawTab) {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", DEFAULT_TAB);
      router.replace(`/cortex?${params.toString()}`, { scroll: false });
    }
  }, [rawTab, router, searchParams]);

  const handleTabChange = (next: TabId) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", next);
    router.push(`/cortex?${params.toString()}`, { scroll: false });
  };

  return (
    <RequireRole roles={CORTEX_ROLES}>
      <div className="p-6 max-w-7xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Cortex</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Mapa kompetencji bazy — kto co umie, skąd to wiemy i jak świeża to
            wiedza
          </p>
        </div>

        <div className="border-b border-border">
          <nav className="flex gap-6" aria-label="Tabs">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => handleTabChange(tab.id)}
                  className={cn(
                    "pb-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap inline-flex items-center gap-2",
                    activeTab === tab.id
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
                  )}
                  aria-current={activeTab === tab.id ? "page" : undefined}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                </button>
              );
            })}
          </nav>
        </div>

        <div>
          {activeTab === "tech" && <TechMapPanel />}
          {activeTab === "coverage" && <CoveragePanel />}
        </div>
      </div>
    </RequireRole>
  );
}
