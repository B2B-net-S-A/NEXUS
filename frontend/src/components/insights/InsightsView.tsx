"use client";

import { useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Landmark, Lock, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore, type UserRole } from "@/store/auth";
import {
  BodyLeasingPanel,
  DEFAULT_CHAPTER,
  isChapterId,
  type ChapterId,
} from "@/components/insights/BodyLeasingPanel";
import { RadaNadzorczaPanel } from "@/components/insights/RadaNadzorczaPanel";

export type TabId = "body-leasing" | "rada";

type TabDef = {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  roles: UserRole[] | null;
};

/**
 * Role, które widzą zakładkę Rada.
 *
 * Decyzja Artura z 21.09.2026 zawęża D7 (2026-08-31) WYŁĄCZNIE dla Rady:
 * pieniądze firmy, rok do roku i ranking klientów z MRR widzą admin, Finanse
 * i Head of Recruitment. Body Leasing zostaje otwarte dla każdej roli.
 *
 * Lustro po stronie API to `BoardReader` (`backend/app/api/deps.py`) na
 * `/api/insights/board`, `/board/yoy` i `/clients/ranking`. Bez niego front
 * chowałby zakładkę, której API i tak by nie odmówiło — split-brain, który
 * ugryzł przy Talent Radarze (#1215).
 */
export const RADA_ROLES: UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
];

// Dwie zakładki zamiast trzech (21.09.2026): Rekrutacja i Delivery Lead
// połączone w „Body Leasing" z trzema rozdziałami, Rada osobno.
const TABS: TabDef[] = [
  { id: "body-leasing", label: "Body Leasing", icon: Users, roles: null },
  { id: "rada", label: "Rada", icon: Landmark, roles: RADA_ROLES },
];

/**
 * Stare identyfikatory zakładek → nowa zakładka i rozdział.
 *
 * Wszystkie żyją w linkach, których nie kontrolujemy: zakładki przeglądarki,
 * notatki zespołu, przekierowania `/dynareporter/*`. Bez mapy trafiałyby
 * w gałąź „nieznany tab" i lądowały na domyślnym rozdziale — link do
 * rankingu Delivery Leadów otwierałby Ligę Mistrzów bez słowa wyjaśnienia.
 */
export const LEGACY_TAB_ALIASES: Record<
  string,
  { tab: TabId; chapter?: ChapterId }
> = {
  rekrutacja: { tab: "body-leasing", chapter: "wyniki" },
  "delivery-lead": { tab: "body-leasing", chapter: "klienci" },
  klienci: { tab: "body-leasing", chapter: "klienci" },
  zarzad: { tab: "rada" },
};

/**
 * Stare kotwice sekcji → rozdział, w którym dziś mieszkają.
 *
 * `#liga` na starej zakładce Rekrutacja to dziś rozdział Rywalizacja, a
 * `#zrodla` — Wyniki. Bez tej mapy link z kotwicą otwierałby rozdział
 * z aliasu, w którym takiej sekcji nie ma, i przewijanie nie robiłoby nic.
 */
export const LEGACY_ANCHOR_CHAPTER: Record<string, ChapterId> = {
  liga: "rywalizacja",
  "sciezka-rozwoju": "rywalizacja",
  podsumowanie: "wyniki",
  lejek: "wyniki",
  zespol: "wyniki",
  trendy: "wyniki",
  placementy: "wyniki",
  zrodla: "wyniki",
  integracje: "wyniki",
  ranking: "klienci",
  "hit-ratio": "klienci",
  "hiring-managerowie": "klienci",
};

type AuthUser = ReturnType<typeof useAuthStore.getState>["user"];

export const DEFAULT_INSIGHTS_TAB: TabId = "body-leasing";

export function getDefaultTabForUser(_user: AuthUser): TabId {
  return DEFAULT_INSIGHTS_TAB;
}

/**
 * Zakładki widoczne dla użytkownika.
 *
 * Przed hydracją auth store (`user === null`) zwraca pełną listę: brak
 * użytkownika to „jeszcze nie wiemy", nie „nie wolno" — inaczej pierwsze
 * wejście na `?tab=rada` przepisałoby adres na Body Leasing, zanim store
 * zdąży powiedzieć, że to admin.
 */
export function getVisibleInsightTabIds(user: AuthUser): TabId[] {
  return TABS.filter(
    (tab) => !user || !tab.roles || hasRole(user, ...tab.roles),
  ).map((tab) => tab.id);
}

export function isTabId(v: string | null): v is TabId {
  return v === "body-leasing" || v === "rada";
}

/**
 * Rozstrzyga, którą zakładkę (i rozdział) pokazać dla wartości z URL-a.
 *
 * `rewrite: true` znaczy „adres w pasku mówi co innego niż ekran" i musi
 * skończyć się podmianą URL-a. `chapter` jest ustawiony tylko wtedy, gdy
 * alias go wskazuje — wtedy zapisujemy go do `?ch=`.
 *
 * Funkcja jest czysta, żeby dało się ją przetestować bez montowania widoku.
 */
export function resolveInsightsTab(
  rawTab: string | null,
  allowed: readonly TabId[] = ["body-leasing", "rada"],
): {
  tab: TabId;
  rewrite: boolean;
  chapter?: ChapterId;
} {
  const ok = (t: TabId) => allowed.includes(t);
  if (isTabId(rawTab) && ok(rawTab)) return { tab: rawTab, rewrite: false };
  const alias = rawTab ? LEGACY_TAB_ALIASES[rawTab] : undefined;
  if (alias && ok(alias.tab)) {
    return alias.chapter
      ? { tab: alias.tab, rewrite: true, chapter: alias.chapter }
      : { tab: alias.tab, rewrite: true };
  }
  const fallback = ok(DEFAULT_INSIGHTS_TAB)
    ? DEFAULT_INSIGHTS_TAB
    : (allowed[0] ?? DEFAULT_INSIGHTS_TAB);
  return { tab: fallback, rewrite: true };
}

/**
 * Rozdział z URL-a z uwzględnieniem starej kotwicy.
 *
 * Kolejność: jawne `?ch=` → rozdział starej kotwicy (`#zrodla`) → rozdział
 * z aliasu zakładki → domyślny. Kotwica wygrywa z aliasem, bo jest
 * dokładniejsza: `?tab=rekrutacja#liga` znaczy Ligę, nie Wyniki.
 */
export function resolveChapter(
  rawChapter: string | null,
  hash: string,
  aliasChapter?: ChapterId,
): ChapterId {
  if (isChapterId(rawChapter)) return rawChapter;
  const anchor = decodeURIComponent(hash.replace(/^#/, ""));
  const fromAnchor = anchor ? LEGACY_ANCHOR_CHAPTER[anchor] : undefined;
  return fromAnchor ?? aliasChapter ?? DEFAULT_CHAPTER;
}

export function InsightsView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);

  const visibleTabIds = useMemo(() => getVisibleInsightTabIds(user), [user]);
  const visibleTabs = useMemo(
    () => TABS.filter((t) => visibleTabIds.includes(t.id)),
    [visibleTabIds],
  );

  const rawTab = searchParams.get("tab");
  const activeTab: TabId = useMemo(
    () => resolveInsightsTab(rawTab, visibleTabIds).tab,
    [rawTab, visibleTabIds],
  );

  // Po hydracji auth store: URL ma nieść dokładnie to, co widać na ekranie.
  // `replace`, nie `push` — korekta adresu nie jest krokiem nawigacji.
  useEffect(() => {
    if (!hydrated || !user) return;
    const { tab, rewrite, chapter } = resolveInsightsTab(rawTab, visibleTabIds);
    const hash = typeof window === "undefined" ? "" : window.location.hash;
    const params = new URLSearchParams(searchParams.toString());
    let changed = rewrite;
    params.set("tab", tab);
    if (tab === "body-leasing") {
      const rawChapter = searchParams.get("ch");
      const ch = resolveChapter(rawChapter, hash, chapter);
      if (rawChapter !== ch) {
        params.set("ch", ch);
        changed = true;
      }
    } else if (params.has("ch")) {
      params.delete("ch");
      changed = true;
    }
    if (!changed) return;
    router.replace(`/insights?${params.toString()}${hash}`, { scroll: false });
  }, [hydrated, user, rawTab, visibleTabIds, router, searchParams]);

  const handleTabChange = (next: TabId) => {
    // Zakładki mają różne domyślne okresy — przeniesiony okres Body Leasing
    // (miesiąc) udawałby, że to wybór Rady (kwartał).
    const params = new URLSearchParams();
    params.set("tab", next);
    router.push(`/insights?${params.toString()}`, { scroll: false });
  };

  const radaLocked = !visibleTabIds.includes("rada");

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-border">
        <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
          <h1 className="text-2xl font-bold tracking-tight text-foreground pb-3">
            Insights
          </h1>
          <nav className="flex gap-6" aria-label="Zakładki Insights">
            {visibleTabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => handleTabChange(tab.id)}
                  className={cn(
                    "pb-3 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap inline-flex items-center gap-2",
                    activeTab === tab.id
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground hover:border-border",
                  )}
                  aria-current={activeTab === tab.id ? "page" : undefined}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                  {tab.roles ? (
                    <Lock
                      className="w-3 h-3 opacity-70"
                      aria-label="Zakładka z ograniczonym dostępem"
                    />
                  ) : null}
                </button>
              );
            })}
          </nav>
        </div>
        {radaLocked ? null : (
          <p className="pb-3 text-xs text-muted-foreground">
            Rada: widzą admin, Finanse i Head of Recruitment
          </p>
        )}
      </div>

      <div>
        {activeTab === "body-leasing" && <BodyLeasingPanel />}
        {activeTab === "rada" && <RadaNadzorczaPanel />}
      </div>
    </div>
  );
}
