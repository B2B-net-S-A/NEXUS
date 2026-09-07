/**
 * Kontrakt RBAC zakładek /insights — decyzja D7 (Artur, 2026-08-31) — oraz
 * kontrakt identyfikatorów zakładek po przejściu na układ DynaReportera.
 *
 * Każda zalogowana rola widzi WSZYSTKIE trzy zakładki. Ten test istnieje po to,
 * żeby cichy refaktor nie przywrócił listy ról: to jest dokładnie ta klasa
 * regresji, która ugryzła przy Talent Radarze (#1215), gdzie link był widoczny,
 * a klik kończył się 403 — bo jedno z pięciu luster listy ról przeżyło sweep.
 *
 * Jeśli ten test zaczyna przeszkadzać, zmień decyzję w
 * docs/insights-dynareporter-migration-plan.md §0 D7 — i zmień razem z nią
 * guard backendu, nie samo lustro we froncie.
 */
import { describe, expect, it } from "vitest";

import {
  DEFAULT_INSIGHTS_TAB,
  LEGACY_TAB_ALIASES,
  getDefaultTabForUser,
  getVisibleInsightTabIds,
  resolveInsightsTab,
} from "@/components/insights/InsightsView";

type AuthUser = Parameters<typeof getVisibleInsightTabIds>[0];

// Pełny enum ról z backend/app/models/user.py — łącznie z legacy `user`.
const ALL_ROLES = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "finance",
  "tac",
  "recruiter",
  "sourcer",
  "user",
] as const;

const user = (role: string): AuthUser =>
  ({ id: 1, email: `${role}@example.com`, name: role, role }) as AuthUser;

describe("dostęp do zakładek Insights (D7)", () => {
  it.each(ALL_ROLES)("rola %s widzi wszystkie trzy zakładki", (role) => {
    expect(getVisibleInsightTabIds(user(role))).toEqual([
      "rekrutacja",
      "delivery-lead",
      "rada",
    ]);
  });

  it.each(ALL_ROLES)("rola %s ma tę samą zakładkę domyślną", (role) => {
    expect(getDefaultTabForUser(user(role))).toBe(DEFAULT_INSIGHTS_TAB);
  });

  it("domyślna zakładka to Rekrutacja — jedna dla wszystkich", () => {
    // Rozgałęzianie po roli dawało dwóm osobom różny ekran pod tym samym linkiem.
    expect(DEFAULT_INSIGHTS_TAB).toBe("rekrutacja");
  });

  it("brak usera też nie zawęża listy", () => {
    // Stan przed hydracją auth store — nie może udawać braku uprawnień.
    expect(getVisibleInsightTabIds(null as unknown as AuthUser)).toHaveLength(
      3,
    );
  });
});

describe("identyfikator zakładki w URL-u", () => {
  it.each(["rekrutacja", "delivery-lead", "rada"] as const)(
    "znany identyfikator %s przechodzi bez przepisywania adresu",
    (tab) => {
      expect(resolveInsightsTab(tab)).toEqual({ tab, rewrite: false });
    },
  );

  it.each([
    ["klienci", "delivery-lead"],
    ["zarzad", "rada"],
  ] as const)(
    "stary link ?tab=%s otwiera %s, a nie zakładkę domyślną",
    (legacy, expected) => {
      // Bez tej mapy stary link trafiał w gałąź „nieznany tab" i cicho lądował
      // na Rekrutacji — czyli link do kokpitu zarządu otwierał co innego.
      expect(resolveInsightsTab(legacy)).toEqual({
        tab: expected,
        rewrite: true,
      });
    },
  );

  it("każdy alias wskazuje na istniejącą zakładkę", () => {
    // Literówka w mapie dałaby przekierowanie w nicość — i to bez błędu,
    // bo `activeTab` renderuje wtedy pustkę zamiast panelu.
    const known = getVisibleInsightTabIds(user("admin"));
    for (const target of Object.values(LEGACY_TAB_ALIASES)) {
      expect(known).toContain(target);
    }
  });

  it("brak parametru i literówka wracają na zakładkę domyślną", () => {
    expect(resolveInsightsTab(null)).toEqual({
      tab: DEFAULT_INSIGHTS_TAB,
      rewrite: true,
    });
    expect(resolveInsightsTab("rekrutcja")).toEqual({
      tab: DEFAULT_INSIGHTS_TAB,
      rewrite: true,
    });
  });

  it("zakładka spoza listy dozwolonych nie zostaje aktywna", () => {
    // Pod D7 lista jest pełna, więc ta gałąź nie odpala się w produkcji. Test
    // pilnuje, że filtr NIE zniknie przy refaktorze: bez niego zawężenie
    // `getVisibleInsightTabIds` dałoby aktywną zakładkę bez przycisku w pasku,
    // czyli pusty kontener treści udający utratę danych.
    expect(resolveInsightsTab("rada", ["rekrutacja"])).toEqual({
      tab: "rekrutacja",
      rewrite: true,
    });
    expect(resolveInsightsTab("zarzad", ["rekrutacja", "delivery-lead"])).toEqual(
      { tab: "rekrutacja", rewrite: true },
    );
  });
});
