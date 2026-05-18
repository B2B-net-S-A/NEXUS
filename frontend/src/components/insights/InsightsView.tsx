"use client";

import { useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BarChart3, Building2, Briefcase } from "lucide-react";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore, type UserRole } from "@/store/auth";
import { useToast } from "@/components/Toast";
import { RekrutacjaPanel } from "@/components/insights/RekrutacjaPanel";
import { KlienciPanel } from "@/components/insights/KlienciPanel";
import { ZarzadPanel } from "@/components/insights/ZarzadPanel";

type TabId = "rekrutacja" | "klienci" | "zarzad";

type TabDef = {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  roles: UserRole[] | null;
};

const TABS: TabDef[] = [
  { id: "rekrutacja", label: "Rekrutacja", icon: BarChart3, roles: null },
  {
    id: "klienci",
    label: "Klienci & Delivery",
    icon: Building2,
    roles: ["admin", "head_of_recruitment"],
  },
  {
    id: "zarzad",
    label: "Zarząd",
    icon: Briefcase,
    roles: ["admin", "delivery_lead", "tac"],
  },
];

type AuthUser = ReturnType<typeof useAuthStore.getState>["user"];

function getDefaultTabForUser(user: AuthUser): TabId {
  if (hasRole(user, "admin", "head_of_recruitment")) return "klienci";
  return "rekrutacja";
}

function isTabId(v: string | null): v is TabId {
  return v === "rekrutacja" || v === "klienci" || v === "zarzad";
}

export function InsightsView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const toast = useToast();

  const visibleTabs = useMemo(
    () => TABS.filter((t) => !t.roles || hasRole(user, ...t.roles)),
    [user]
  );

  const rawTab = searchParams.get("tab");
  const requestedTab = isTabId(rawTab) ? rawTab : null;

  const activeTab: TabId = useMemo(() => {
    if (requestedTab && visibleTabs.some((t) => t.id === requestedTab)) {
      return requestedTab;
    }
    return getDefaultTabForUser(user);
  }, [requestedTab, visibleTabs, user]);

  // Po hydration auth store: jeśli URL nie ma `?tab=` → wstaw default,
  // jeśli ma `?tab=X` ale user nie ma uprawnień → toast + redirect.
  useEffect(() => {
    if (!hydrated || !user) return;

    if (!rawTab) {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", getDefaultTabForUser(user));
      router.replace(`/insights?${params.toString()}`, { scroll: false });
      return;
    }

    if (!isTabId(rawTab) || !visibleTabs.some((t) => t.id === rawTab)) {
      toast.showError("Brak dostępu do tej zakładki");
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", getDefaultTabForUser(user));
      router.replace(`/insights?${params.toString()}`);
    }
  }, [hydrated, user, rawTab, visibleTabs, router, searchParams, toast]);

  const handleTabChange = (next: TabId) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", next);
    router.push(`/insights?${params.toString()}`, { scroll: false });
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Insights</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Analityka, raporty i dashboardy w jednym miejscu
        </p>
      </div>

      <div className="border-b border-border">
        <nav className="flex gap-6" aria-label="Tabs">
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
        {activeTab === "rekrutacja" && <RekrutacjaPanel />}
        {activeTab === "klienci" && <KlienciPanel />}
        {activeTab === "zarzad" && <ZarzadPanel />}
      </div>
    </div>
  );
}
