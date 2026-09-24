"use client";

import { useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  FileText,
  Landmark,
  Lock,
  Trophy,
  UserRound,
  Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  isReportId,
  visibleReports,
  type ReportId,
} from "@/lib/insights-reports";
import { hasRole, useAuthStore, type UserRole } from "@/store/auth";
import { FirmaView } from "@/components/insights/views/FirmaView";
import { MojMiesiacView } from "@/components/insights/views/MojMiesiacView";
import { RaportyView } from "@/components/insights/views/RaportyView";
import { RywalizacjaView } from "@/components/insights/views/RywalizacjaView";
import { ZespolView } from "@/components/insights/views/ZespolView";

export type TabId = "rywalizacja" | "moj-miesiac" | "zespol" | "firma" | "raporty";

type TabDef = {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  roles: UserRole[] | null;
};

/**
 * Role, które widzą widok Firma (pieniądze firmy: przychód, marża, ranking
 * klientów z kwotami).
 *
 * Decyzja Artura z 24.09.2026: Head of Recruitment zajmuje się rekrutacją
 * i NIE widzi pieniędzy — do tego dnia zakładka Rada była otwarta także dla
 * niego. Lustro po stronie API to `BoardReader` (`backend/app/api/deps.py`)
 * na `/api/insights/board` i `/clients/ranking`; bez niego front chowałby
 * widok, którego API i tak by nie odmówiło (split-brain z #1215).
 */
export const FIRMA_ROLES: UserRole[] = ["admin", "finance"];

/**
 * Role z własnymi KPI rekrutacyjnymi — lustro `_OPERATIONAL_ROLES`
 * w `backend/app/services/kpi_panel.py` (`/api/kpis/me/panel` → `applies`).
 */
export const PERSONAL_ROLES: UserRole[] = [
  "recruiter",
  "sourcer",
  "tac",
  "delivery_lead",
];

// Pięć widoków zamiast dwóch zakładek z rozdziałami (24.09.2026). Kolejność =
// kolejność pytań: kto wygrywa → jak mi idzie → jak idzie zespołowi → ile
// zarabia firma → reszta. Rywalizacja jest pierwsza dla każdego (Artur:
// „Liga Mistrzów i wyścigi miesięczne — bardzo ważne").
const TABS: TabDef[] = [
  { id: "rywalizacja", label: "Rywalizacja", icon: Trophy, roles: null },
  { id: "moj-miesiac", label: "Mój miesiąc", icon: UserRound, roles: PERSONAL_ROLES },
  { id: "zespol", label: "Zespół", icon: Users, roles: null },
  { id: "firma", label: "Firma", icon: Landmark, roles: FIRMA_ROLES },
  { id: "raporty", label: "Raporty", icon: FileText, roles: null },
];

type Target = { tab: TabId; report?: ReportId };

/**
 * Stare identyfikatory zakładek → nowy widok (albo raport).
 *
 * Żyją w linkach, których nie kontrolujemy: zakładki przeglądarki, notatki
 * zespołu, przekierowania `/dynareporter/*`, stare maile raportowe. Bez mapy
 * link do rankingu Delivery Leadów otwierałby Rywalizację bez słowa.
 * Klucze czyta też `backend/tests/test_client_tab_links.py`.
 */
export const LEGACY_TAB_ALIASES: Record<string, Target> = {
  "body-leasing": { tab: "rywalizacja" },
  rekrutacja: { tab: "zespol" },
  "delivery-lead": { tab: "raporty", report: "portfele-dl" },
  klienci: { tab: "raporty", report: "portfele-dl" },
  rada: { tab: "firma" },
  zarzad: { tab: "firma" },
};

/** Rozdziały dawnej zakładki Body Leasing (`?ch=`). */
export const LEGACY_CHAPTERS: Record<string, Target> = {
  rywalizacja: { tab: "rywalizacja" },
  wyniki: { tab: "zespol" },
  klienci: { tab: "raporty", report: "portfele-dl" },
};

/**
 * Stare kotwice sekcji → widok albo raport, w którym ta treść dziś mieszka.
 * Kotwica jest dokładniejsza niż alias: `?tab=rekrutacja#zrodla` znaczy
 * raport „Źródła”, nie widok Zespół.
 */
export const LEGACY_ANCHORS: Record<string, Target> = {
  liga: { tab: "rywalizacja" },
  wyscigi: { tab: "rywalizacja" },
  "hall-of-fame": { tab: "raporty", report: "hall-of-fame" },
  "sciezka-rozwoju": { tab: "raporty", report: "sciezka" },
  wynik: { tab: "zespol" },
  podsumowanie: { tab: "zespol" },
  lejek: { tab: "zespol" },
  zespol: { tab: "zespol" },
  aktywnosc: { tab: "zespol" },
  etapy: { tab: "raporty", report: "lejek-etapy" },
  trendy: { tab: "raporty", report: "rok-do-roku" },
  "rok-do-roku": { tab: "raporty", report: "rok-do-roku" },
  prepy: { tab: "raporty", report: "prepy" },
  praca: { tab: "raporty", report: "placementy" },
  placementy: { tab: "raporty", report: "placementy" },
  doplyw: { tab: "raporty", report: "doplyw" },
  zrodla: { tab: "raporty", report: "doplyw" },
  integracje: { tab: "raporty", report: "doplyw" },
  "podsumowanie-klientow": { tab: "raporty", report: "portfele-dl" },
  portfele: { tab: "raporty", report: "portfele-dl" },
  "hit-ratio": { tab: "raporty", report: "portfele-dl" },
  "hiring-managerowie": { tab: "raporty", report: "portfele-dl" },
  kpi: { tab: "firma" },
  ranking: { tab: "firma" },
  klienci: { tab: "firma" },
};

type AuthUser = ReturnType<typeof useAuthStore.getState>["user"];

export const DEFAULT_INSIGHTS_TAB: TabId = "rywalizacja";

export function getDefaultTabForUser(_user: AuthUser): TabId {
  return DEFAULT_INSIGHTS_TAB;
}

/**
 * Widoki widoczne dla użytkownika. Przed hydracją auth store (`user ===
 * null`) — pełna lista: brak użytkownika to „jeszcze nie wiemy", nie „nie
 * wolno". Inaczej pierwsze wejście na `?tab=firma` przepisałoby adres, zanim
 * store powie, że to admin.
 */
export function getVisibleInsightTabIds(user: AuthUser): TabId[] {
  return TABS.filter(
    (tab) => !user || !tab.roles || hasRole(user, ...tab.roles),
  ).map((tab) => tab.id);
}

export function isTabId(v: string | null): v is TabId {
  return TABS.some((tab) => tab.id === v);
}

export interface InsightsLocationInput {
  tab: string | null;
  ch?: string | null;
  report?: string | null;
  hash?: string;
}

export interface InsightsLocation {
  tab: TabId;
  report: ReportId | null;
  /** Adres w pasku mówi co innego niż ekran — trzeba go podmienić. */
  rewrite: boolean;
  /** Stara kotwica nie istnieje w nowym układzie — zdjąć ją z adresu. */
  dropHash: boolean;
}

/**
 * Rozstrzyga, który widok (i raport) pokazać dla adresu — nowego albo
 * sprzed przebudowy. Czysta funkcja: testowalna bez montowania widoku.
 */
export function resolveInsightsLocation(
  input: InsightsLocationInput,
  allowedTabs: readonly TabId[] = TABS.map((t) => t.id),
  allowedReports: readonly ReportId[] | null = null,
): InsightsLocation {
  const anchor = decodeURIComponent((input.hash ?? "").replace(/^#/, ""));
  let target: Target;
  let rewrite = false;
  let dropHash = false;

  if (isTabId(input.tab)) {
    target = {
      tab: input.tab,
      report:
        input.tab === "raporty" && isReportId(input.report)
          ? input.report
          : undefined,
    };
    if (input.report && !target.report) rewrite = true;
  } else {
    rewrite = true;
    const fromAnchor = anchor ? LEGACY_ANCHORS[anchor] : undefined;
    const fromChapter =
      input.tab === "body-leasing" && input.ch
        ? LEGACY_CHAPTERS[input.ch]
        : undefined;
    const fromAlias = input.tab ? LEGACY_TAB_ALIASES[input.tab] : undefined;
    target = fromAnchor ?? fromChapter ??
      fromAlias ?? { tab: DEFAULT_INSIGHTS_TAB };
    dropHash = Boolean(anchor);
  }
  if (input.ch) rewrite = true;

  if (!allowedTabs.includes(target.tab)) {
    rewrite = true;
    // Pieniądze bez uprawnień: najbliższa rzecz bez kwot to rok do roku.
    target =
      target.tab === "firma" && allowedTabs.includes("raporty")
        ? { tab: "raporty", report: "rok-do-roku" }
        : { tab: allowedTabs[0] ?? DEFAULT_INSIGHTS_TAB };
  }
  if (target.report && allowedReports && !allowedReports.includes(target.report)) {
    rewrite = true;
    target = { tab: target.tab };
  }
  return {
    tab: target.tab,
    report: target.report ?? null,
    rewrite,
    dropHash,
  };
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
  const allowedReports = useMemo(
    () => (user ? visibleReports(user).map((r) => r.id) : null),
    [user],
  );

  const rawTab = searchParams.get("tab");
  const rawCh = searchParams.get("ch");
  const rawReport = searchParams.get("report");
  const location = useMemo(
    () =>
      resolveInsightsLocation(
        {
          tab: rawTab,
          ch: rawCh,
          report: rawReport,
          hash: typeof window === "undefined" ? "" : window.location.hash,
        },
        visibleTabIds,
        allowedReports,
      ),
    [rawTab, rawCh, rawReport, visibleTabIds, allowedReports],
  );

  // Po hydracji: URL ma nieść dokładnie to, co widać. `replace`, nie `push`
  // — korekta adresu nie jest krokiem nawigacji.
  useEffect(() => {
    if (!hydrated || !user || !location.rewrite) return;
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", location.tab);
    params.delete("ch");
    if (location.report) params.set("report", location.report);
    else params.delete("report");
    const hash =
      location.dropHash || typeof window === "undefined"
        ? ""
        : window.location.hash;
    router.replace(`/insights?${params.toString()}${hash}`, { scroll: false });
  }, [hydrated, user, location, router, searchParams]);

  const handleTabChange = (next: TabId) => {
    // Widoki mają różne domyślne okresy — przeniesiony okres jednego
    // udawałby wybór w drugim.
    router.push(`/insights?tab=${next}`, { scroll: false });
  };

  const firmaVisible = visibleTabIds.includes("firma");

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-border">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-8 gap-y-2">
          <h1 className="pb-3 text-2xl font-bold tracking-tight text-foreground">
            Insights
          </h1>
          <nav
            className="flex max-w-full gap-5 overflow-x-auto"
            aria-label="Widoki Insights"
          >
            {visibleTabs.map((tab) => {
              const Icon = tab.icon;
              const active = location.tab === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => handleTabChange(tab.id)}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 pb-3 text-sm font-semibold transition-colors",
                    active
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:border-border hover:text-foreground",
                  )}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon className="h-4 w-4" />
                  {tab.label}
                  {tab.id === "firma" ? (
                    <Lock
                      className="h-3 w-3 opacity-70"
                      aria-label="Widok z ograniczonym dostępem"
                    />
                  ) : null}
                </button>
              );
            })}
          </nav>
        </div>
        {firmaVisible ? (
          <p className="pb-3 text-xs text-muted-foreground">
            Firma: widzą admin i Finanse
          </p>
        ) : null}
      </div>

      <div>
        {location.tab === "rywalizacja" && <RywalizacjaView />}
        {location.tab === "moj-miesiac" && <MojMiesiacView />}
        {location.tab === "zespol" && <ZespolView />}
        {location.tab === "firma" && <FirmaView />}
        {location.tab === "raporty" && <RaportyView reportId={location.report} />}
      </div>
    </div>
  );
}
