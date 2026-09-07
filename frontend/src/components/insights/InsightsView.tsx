"use client";

import { useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BarChart3, Landmark, Target } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuthStore, type UserRole } from "@/store/auth";
import { RekrutacjaPanel } from "@/components/insights/RekrutacjaPanel";
import { DeliveryLeadPanel } from "@/components/insights/DeliveryLeadPanel";
import { RadaNadzorczaPanel } from "@/components/insights/RadaNadzorczaPanel";

export type TabId = "rekrutacja" | "delivery-lead" | "rada";

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
//
// Trójka zakładek jest lustrem DynaReportera (Rekrutacja / Delivery Lead /
// Rada Nadzorcza), bo zespół zna tamten podział i tamtą kolejność sekcji.
// Skutek dla zawartości, o którym trzeba pamiętać przy dokładaniu sekcji:
// ranking klientów i MRR mieszkają w RADZIE (to pytanie o pieniądze firmy),
// a Delivery Lead odpowiada za obsadę i hit ratio.
const TABS: TabDef[] = [
  { id: "rekrutacja", label: "Rekrutacja", icon: BarChart3, roles: null },
  { id: "delivery-lead", label: "Delivery Lead", icon: Target, roles: null },
  { id: "rada", label: "Rada Nadzorcza", icon: Landmark, roles: null },
];

/**
 * Stare identyfikatory zakładek → nowe.
 *
 * `?tab=klienci` i `?tab=zarzad` żyją w linkach, których nie kontrolujemy:
 * w zakładkach przeglądarki, w notatkach zespołu i na stronie `/dynareporter`.
 * Bez tej mapy trafiałyby w gałąź „nieznany tab" i lądowały na Rekrutacji —
 * czyli link do kokpitu zarządu po cichu otwierałby coś innego, bez słowa
 * wyjaśnienia. Mapowanie przepisuje URL na nowy identyfikator, więc kolejne
 * odświeżenie i udostępnienie linku niosą już aktualny adres.
 */
export const LEGACY_TAB_ALIASES: Record<string, TabId> = {
  klienci: "delivery-lead",
  zarzad: "rada",
};

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

export function isTabId(v: string | null): v is TabId {
  return v === "rekrutacja" || v === "delivery-lead" || v === "rada";
}

/**
 * Rozstrzyga, którą zakładkę pokazać dla wartości z URL-a.
 *
 * Zwraca też `rewrite`: `true` znaczy „adres w pasku mówi co innego niż ekran"
 * i musi skończyć się podmianą URL-a. Trzy różne przyczyny są tu celowo
 * rozdzielone od siebie, bo prowadzą do różnych adresów końcowych: brak
 * parametru (wstaw domyślny), stary identyfikator (przepisz na nowy),
 * literówka (wróć na domyślny).
 *
 * Funkcja jest czysta, żeby dało się ją przetestować bez montowania widoku —
 * to ta sama lekcja co przy martwych przyciskach paska okresu (PR #1316):
 * test kończący się na argumencie callbacka nie dowodzi, że nawigacja działa.
 */
export function resolveInsightsTab(
  rawTab: string | null,
  /**
   * Zakładki, które wolno pokazać. Pod D7 to zawsze komplet, ale parametr
   * ZOSTAJE: gdyby ktoś kiedyś zawęził `getVisibleInsightTabIds`, bez tego
   * filtra `activeTab` wskazywałby zakładkę, której nie ma w pasku — a wtedy
   * kontener treści renderuje pustkę i wygląda to jak utrata danych, nie jak
   * brak dostępu.
   */
  allowed: readonly TabId[] = ["rekrutacja", "delivery-lead", "rada"],
): {
  tab: TabId;
  rewrite: boolean;
} {
  const ok = (t: TabId) => allowed.includes(t);
  if (isTabId(rawTab) && ok(rawTab)) return { tab: rawTab, rewrite: false };
  const alias = rawTab ? LEGACY_TAB_ALIASES[rawTab] : undefined;
  if (alias && ok(alias)) return { tab: alias, rewrite: true };
  const fallback = ok(DEFAULT_INSIGHTS_TAB)
    ? DEFAULT_INSIGHTS_TAB
    : (allowed[0] ?? DEFAULT_INSIGHTS_TAB);
  return { tab: fallback, rewrite: true };
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

  const visibleTabIds = useMemo(
    () => visibleTabs.map((t) => t.id),
    [visibleTabs],
  );

  const rawTab = searchParams.get("tab");
  const activeTab: TabId = useMemo(
    () => resolveInsightsTab(rawTab, visibleTabIds).tab,
    [rawTab, visibleTabIds],
  );

  // Po hydration auth store: URL ma nieść dokładnie to, co widać na ekranie —
  // brakujący `?tab=`, stary identyfikator i literówkę doprowadzamy do postaci
  // kanonicznej. `replace`, nie `push`: korekta adresu nie jest krokiem
  // nawigacji, więc nie może zapychać przycisku Wstecz.
  useEffect(() => {
    if (!hydrated || !user) return;
    const { tab, rewrite } = resolveInsightsTab(rawTab, visibleTabIds);
    if (!rewrite) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", tab);
    router.replace(`/insights?${params.toString()}`, { scroll: false });
  }, [hydrated, user, rawTab, visibleTabIds, router, searchParams]);

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
        {activeTab === "delivery-lead" && <DeliveryLeadPanel />}
        {activeTab === "rada" && <RadaNadzorczaPanel />}
      </div>
    </div>
  );
}
