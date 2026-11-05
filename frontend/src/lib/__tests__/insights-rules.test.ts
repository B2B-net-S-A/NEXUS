import { describe, expect, it } from "vitest";

import { getVisibleInsightTabIds } from "@/components/insights/InsightsView";
import { isRuleId, lastChangeText, RULE_ROWS, visibleRuleRows } from "@/lib/insights-rules";
import { useAuthStore, type UserRole } from "@/store/auth";

type AuthUser = NonNullable<ReturnType<typeof useAuthStore.getState>["user"]>;

const WRITE_SECTIONS = {
  sourcing: "write",
  pipeline: "write",
  insights: "write",
  delivery: "write",
  finance: "write",
  system_admin: "write",
};

const user = (role: UserRole, extra: Partial<AuthUser> = {}) =>
  ({
    id: 1,
    email: "x@example.test",
    name: "Osoba Testowa",
    role,
    roles: [role],
    effective_section_access: WRITE_SECTIONS,
    ...extra,
  }) as unknown as AuthUser;

const ids = (u: AuthUser) => visibleRuleRows(u).map((row) => row.id);

describe("Insights → Zasady", () => {
  it("zakładkę widzą tylko administrator i Head of Recruitment", () => {
    const roles: UserRole[] = ["admin", "head_of_recruitment", "delivery_lead", "recruiter", "finance", "board"];
    for (const role of roles) {
      expect(getVisibleInsightTabIds(user(role)).includes("zasady"), role).toBe(
        role === "admin" || role === "head_of_recruitment",
      );
    }
  });

  it("zakładka stoi między Źródłami a Raportami", () => {
    const tabs = getVisibleInsightTabIds(user("admin"));
    expect(tabs.indexOf("zasady")).toBe(tabs.indexOf("raporty") - 1);
    expect(tabs.indexOf("zasady")).toBe(tabs.indexOf("zrodla") + 1);
  });

  it("administrator widzi wszystkie dziewięć zasad", () => {
    expect(ids(user("admin"))).toEqual(RULE_ROWS.map((row) => row.id));
  });

  it("Head of Recruitment bez roli admina nie widzi zasad tylko dla administratora", () => {
    const seen = ids(user("head_of_recruitment"));
    expect(seen).toEqual(["przydzial", "blizniaki", "ranking", "prepy", "cele", "aktywnosc"]);
  });

  it("Head of Recruitment bez zapisu Insights nie widzi Celów KPI, jak w Ustawieniach", () => {
    const seen = ids(
      user("head_of_recruitment", {
        effective_section_access: { ...WRITE_SECTIONS, insights: "read" },
      } as Partial<AuthUser>),
    );
    expect(seen).not.toContain("cele");
    expect(seen).toContain("ranking");
  });

  it("adres z nieznaną zasadą nie jest zasadą", () => {
    expect(isRuleId("blizniaki")).toBe(true);
    expect(isRuleId("nie-ma")).toBe(false);
    expect(isRuleId(null)).toBe(false);
  });

  it("brak zmiany to „Nigdy”", () => {
    expect(lastChangeText(null)).toBe("Nigdy");
  });

  it("zmiana bez osoby to automat", () => {
    const at = "2026-10-12T10:00:00Z";
    expect(lastChangeText({ at, by: "Osoba Testowa" })).toMatch(/Osoba Testowa$/);
    expect(lastChangeText({ at, by: null })).toMatch(/automat$/);
  });
});
