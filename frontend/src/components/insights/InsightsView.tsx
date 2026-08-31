"use client";

import { useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BarChart3, Building2, Briefcase } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore, type UserRole } from "@/store/auth";
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

// Decyzja D7 (Artur, 2026-08-31): /insights widzi KAŻDA zalogowana rola —
// łącznie z kwotami i danymi imiennymi. Konsekwencję zgłoszono i została
// potwierdzona; patrz docs/insights-dynareporter-migration-plan.md §0 D7.
//
// `roles: null` we wszystkich trzech NIE jest przeoczeniem. Zawężenie
// którejkolwiek zakładki wymaga zmiany TEJ decyzji, nie cichej poprawki tutaj,
// i musi iść w parze z guardem backendu — inaczej robi się split-brain: albo
// front chowa sekcję, której API i tak by nie odmówiło, albo menu jest
// widoczne, a klik kończy się 403 (tak ugryzło przy Talent Radarze, #1215).
const TABS: TabDef[] = [
  { id: "rekrutacja", label: "Rekrutacja", icon: BarChart3, roles: null },
  { id: "klienci", label: "Klienci & Delivery", icon: Building2, roles: null },
  { id: "zarzad", label: "Zarząd", icon: Briefcase, roles: null },
];

type AuthUser = ReturnType<typeof useAuthStore.getState>["user"];

// Jedna zakładka domyślna dla wszystkich (D7). Rozgałęzianie po roli nie ma
// już czego chronić, a dawało dwóm osobom różny ekran pod tym samym linkiem.
export const DEFAULT_INSIGHTS_TAB: TabId = "rekrutacja";

// Sygnatury zostają (konsumuje je test kontraktowy InsightsAccess.test.ts),
// ale przestają zależeć od roli. Parametr jest celowo nieużywany — gdy ktoś
// będzie chciał go znów użyć, zobaczy tę uwagę i decyzję D7 nad TABS.
export function getDefaultTabForUser(_user: AuthUser): TabId {
  return DEFAULT_INSIGHTS_TAB;
}

export function getVisibleInsightTabIds(_user: AuthUser): TabId[] {
  return TABS.map((tab) => tab.id);
}

function isTabId(v: string | null): v is TabId {
  return v === "rekrutacja" || v === "klienci" || v === "zarzad";
}

export function InsightsView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);

  const visibleTabs = useMemo(
    () => TABS.filter((t) => getVisibleInsightTabIds(user).includes(t.id)),
    [user],
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
  // jeśli ma nieznane `?tab=X` → korekta na domyślną.
  useEffect(() => {
    if (!hydrated || !user) return;

    if (!rawTab) {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", getDefaultTabForUser(user));
      router.replace(`/insights?${params.toString()}`, { scroll: false });
      return;
    }

    if (!isTabId(rawTab) || !visibleTabs.some((t) => t.id === rawTab)) {
      // Nieznany `?tab=` (literówka, stary link) — korygujemy na domyślną.
      // Świadomie BEZ komunikatu o braku dostępu: po D7 żadna rola nie jest
      // odcięta, więc taki toast kłamałby o przyczynie.
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", getDefaultTabForUser(user));
      router.replace(`/insights?${params.toString()}`);
    }
  }, [hydrated, user, rawTab, visibleTabs, router, searchParams]);

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
                    : "border-transparent text-muted-foreground hover:text-foreground hover:border-border",
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
