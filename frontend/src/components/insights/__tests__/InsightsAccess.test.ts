/**
 * Kontrakt RBAC zakładek /insights — decyzja D7 (Artur, 2026-08-31).
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
  getDefaultTabForUser,
  getVisibleInsightTabIds,
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
      "klienci",
      "zarzad",
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
