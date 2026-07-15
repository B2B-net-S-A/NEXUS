"use client";

import { useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ArrowLeftRight,
  Building2,
  Gauge,
  Grid3x3,
  Layers,
  ListChecks,
  Scale,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { RequireRole } from "@/components/RequireRole";
import { CoveragePanel } from "@/components/cortex/CoveragePanel";
import { TechMapPanel } from "@/components/cortex/TechMapPanel";
import { SkillSearchPanel } from "@/components/cortex/SkillSearchPanel";
import { ClientStackPanel } from "@/components/cortex/ClientStackPanel";
import { SuccessorsPanel } from "@/components/cortex/SuccessorsPanel";
import { SupplyDemandPanel } from "@/components/cortex/SupplyDemandPanel";
import { CurationPanel } from "@/components/cortex/CurationPanel";
import { hasRole, useAuthStore, type UserRole } from "@/store/auth";

// RODO gate: widoki agregują dane kompetencyjne kandydatów — ten sam zestaw
// ról co zakładka "Klienci & Delivery" w Insights i backendowy CortexUser.
export const CORTEX_ROLES: UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "tac",
];

type TabId =
  | "tech"
  | "skills"
  | "clients"
  | "successors"
  | "supply"
  | "coverage"
  | "curation";

type TabDef = {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  /** Only rendered (and reachable via the nav) for admins. */
  adminOnly?: boolean;
};

const TABS: TabDef[] = [
  { id: "tech", label: "Mapa technologiczna", icon: Grid3x3 },
  { id: "skills", label: "Technologie", icon: Layers },
  { id: "clients", label: "Klienci", icon: Building2 },
  { id: "successors", label: "Następcy", icon: ArrowLeftRight },
  { id: "supply", label: "Podaż/Popyt", icon: Scale },
  { id: "coverage", label: "Jakość danych", icon: Gauge },
  { id: "curation", label: "Kuracja", icon: ListChecks, adminOnly: true },
];

const TAB_IDS = new Set<string>(TABS.map((t) => t.id));
const DEFAULT_TAB: TabId = "tech";

function isTabId(v: string | null): v is TabId {
  return v !== null && TAB_IDS.has(v);
}

export function CortexView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const user = useAuthStore((s) => s.user);
  const isAdmin = hasRole(user, "admin");

  const visibleTabs = useMemo(
    () => TABS.filter((t) => !t.adminOnly || isAdmin),
    [isAdmin]
  );

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
          <nav className="flex gap-6 overflow-x-auto" aria-label="Tabs">
            {visibleTabs.map((tab) => {
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
          {activeTab === "skills" && <SkillSearchPanel />}
          {activeTab === "clients" && <ClientStackPanel />}
          {activeTab === "successors" && <SuccessorsPanel />}
          {activeTab === "supply" && <SupplyDemandPanel />}
          {activeTab === "coverage" && <CoveragePanel />}
          {activeTab === "curation" && <CurationPanel />}
        </div>
      </div>
    </RequireRole>
  );
}
