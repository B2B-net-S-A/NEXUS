/**
 * Kontrakt dostępu do widoków /insights i adresów sprzed przebudowy.
 *
 * Przebudowa 24.09.2026: pięć widoków. Firma (pieniądze) — WYŁĄCZNIE admin
 * i Finanse; Head of Recruitment nie widzi kwot (decyzja Artura). Lustro po
 * stronie API to `BoardReader` na `/api/insights/board` i `/clients/ranking`
 * — zmiana listy ról tutaj bez zmiany tam robi split-brain (#1215).
 */
import { describe, expect, it } from "vitest";

import {
  DEFAULT_INSIGHTS_TAB,
  FIRMA_ROLES,
  LEGACY_ANCHORS,
  LEGACY_TAB_ALIASES,
  getDefaultTabForUser,
  getVisibleInsightTabIds,
  resolveInsightsLocation,
  type TabId,
} from "@/components/insights/InsightsView";
import { REPORTS, visibleReports } from "@/lib/insights-reports";

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
  "trainee",
] as const;

const user = (
  role: string,
  extra: { roles?: string[]; capabilities?: string[] } = {},
): NonNullable<AuthUser> =>
  ({
    id: 1,
    email: `${role}@example.com`,
    name: role,
    role,
    ...extra,
  }) as NonNullable<AuthUser>;

const ALL_TABS: TabId[] = ["rywalizacja", "moj-miesiac", "zespol", "firma", "raporty"];

describe("widoki Insights per rola", () => {
  it.each(ALL_ROLES)("rola %s widzi Rywalizację, Zespół i Raporty", (role) => {
    const tabs = getVisibleInsightTabIds(user(role));
    expect(tabs).toEqual(expect.arrayContaining(["rywalizacja", "zespol", "raporty"]));
    expect(tabs[0]).toBe("rywalizacja");
  });

  it("Firmę widzą wyłącznie admin i Finanse", () => {
    expect(FIRMA_ROLES).toEqual(["admin", "finance"]);
    for (const role of ALL_ROLES) {
      const sees = getVisibleInsightTabIds(user(role)).includes("firma");
      expect(sees, role).toBe(role === "admin" || role === "finance");
    }
  });

  it("Head of Recruitment NIE widzi Firmy (decyzja 24.09.2026)", () => {
    expect(getVisibleInsightTabIds(user("head_of_recruitment"))).not.toContain(
      "firma",
    );
  });

  it("hybryda HoR + Finanse widzi Firmę — przez rolę Finanse", () => {
    expect(
      getVisibleInsightTabIds(
        user("head_of_recruitment", { roles: ["finance"] }),
      ),
    ).toContain("firma");
  });

  it("Mój miesiąc mają role z własnymi KPI (lustro backendu)", () => {
    for (const role of ["recruiter", "sourcer", "tac", "delivery_lead"]) {
      expect(getVisibleInsightTabIds(user(role))).toContain("moj-miesiac");
    }
    for (const role of ["admin", "finance", "head_of_recruitment", "user"]) {
      expect(getVisibleInsightTabIds(user(role))).not.toContain("moj-miesiac");
    }
  });

  it("przed hydracją auth pokazuje wszystkie widoki", () => {
    expect(getVisibleInsightTabIds(null)).toEqual(ALL_TABS);
  });

  it("domyślny widok to Rywalizacja dla każdego", () => {
    expect(DEFAULT_INSIGHTS_TAB).toBe("rywalizacja");
    for (const role of ALL_ROLES) {
      expect(getDefaultTabForUser(user(role))).toBe("rywalizacja");
    }
  });
});

describe("raporty per rola", () => {
  const ids = (role: string, extra = {}) =>
    visibleReports(user(role, extra)).map((r) => r.id);

  it("ranking klientów z kwotami — tylko admin i Finanse", () => {
    expect(ids("admin")).toContain("ranking-klientow");
    expect(ids("finance")).toContain("ranking-klientow");
    expect(ids("head_of_recruitment")).not.toContain("ranking-klientow");
    expect(ids("recruiter")).not.toContain("ranking-klientow");
  });

  it("rekrutacje bez ruchu — tylko z view_team_kpi", () => {
    expect(
      ids("head_of_recruitment", { capabilities: ["view_team_kpi"] }),
    ).toContain("bez-ruchu");
    expect(ids("recruiter")).not.toContain("bez-ruchu");
  });

  it("nic nie znika: każdy raport ma pytanie i okno", () => {
    for (const report of REPORTS) {
      expect(report.question.length, report.id).toBeGreaterThan(10);
      expect(report.window.length, report.id).toBeGreaterThan(0);
    }
  });
});

describe("resolveInsightsLocation — nowe adresy", () => {
  it("znany widok zostaje bez przepisywania", () => {
    expect(resolveInsightsLocation({ tab: "zespol" })).toEqual({
      tab: "zespol",
      report: null,
      rewrite: false,
      dropHash: false,
    });
  });

  it("raport zostaje przy widoku Raporty", () => {
    expect(
      resolveInsightsLocation({ tab: "raporty", report: "doplyw" }),
    ).toMatchObject({ tab: "raporty", report: "doplyw", rewrite: false });
  });

  it("nieznany raport przepisuje adres na listę", () => {
    expect(
      resolveInsightsLocation({ tab: "raporty", report: "nie-ma" }),
    ).toMatchObject({ tab: "raporty", report: null, rewrite: true });
  });

  it("brak parametru = Rywalizacja", () => {
    expect(resolveInsightsLocation({ tab: null })).toMatchObject({
      tab: "rywalizacja",
      rewrite: true,
    });
  });

  it("Firma bez uprawnień → rok do roku bez kwot", () => {
    expect(
      resolveInsightsLocation(
        { tab: "firma" },
        ["rywalizacja", "zespol", "raporty"],
      ),
    ).toMatchObject({ tab: "raporty", report: "rok-do-roku", rewrite: true });
  });

  it("raport spoza uprawnień → lista raportów", () => {
    expect(
      resolveInsightsLocation(
        { tab: "raporty", report: "ranking-klientow" },
        ALL_TABS,
        ["rok-do-roku"],
      ),
    ).toMatchObject({ tab: "raporty", report: null, rewrite: true });
  });
});

describe("resolveInsightsLocation — adresy sprzed 24.09.2026", () => {
  it.each([
    [{ tab: "body-leasing", ch: "rywalizacja" }, "rywalizacja", null],
    [{ tab: "body-leasing", ch: "wyniki" }, "zespol", null],
    [{ tab: "body-leasing", ch: "klienci" }, "raporty", "portfele-dl"],
    [{ tab: "body-leasing" }, "rywalizacja", null],
    [{ tab: "rekrutacja" }, "zespol", null],
    [{ tab: "delivery-lead" }, "raporty", "portfele-dl"],
    [{ tab: "klienci" }, "raporty", "portfele-dl"],
    [{ tab: "rada" }, "firma", null],
    [{ tab: "zarzad" }, "firma", null],
  ] as const)("%j → %s / %s", (input, tab, report) => {
    expect(resolveInsightsLocation(input)).toMatchObject({
      tab,
      report,
      rewrite: true,
    });
  });

  it("kotwica wygrywa z aliasem: #zrodla to raport Źródła", () => {
    expect(
      resolveInsightsLocation({ tab: "rekrutacja", hash: "#zrodla" }),
    ).toMatchObject({ tab: "raporty", report: "doplyw", dropHash: true });
  });

  it("rada#klienci (stary link MRR z DynaReportera) → Firma", () => {
    expect(
      resolveInsightsLocation({ tab: "rada", hash: "#klienci" }),
    ).toMatchObject({ tab: "firma" });
  });

  it("rada dla Head of Recruitment → rok do roku bez kwot", () => {
    expect(
      resolveInsightsLocation(
        { tab: "rada" },
        getVisibleInsightTabIds(user("head_of_recruitment")),
      ),
    ).toMatchObject({ tab: "raporty", report: "rok-do-roku" });
  });

  it("parametr ch przy nowym widoku jest zdejmowany z adresu", () => {
    expect(
      resolveInsightsLocation({ tab: "zespol", ch: "wyniki" }),
    ).toMatchObject({ tab: "zespol", rewrite: true });
  });

  it("aliasy i kotwice wskazują tylko istniejące raporty", () => {
    const known = new Set(REPORTS.map((r) => r.id));
    for (const target of [
      ...Object.values(LEGACY_TAB_ALIASES),
      ...Object.values(LEGACY_ANCHORS),
    ]) {
      if (target.report) expect(known.has(target.report), target.report).toBe(true);
    }
  });

  it("stare klucze zakładek, których używa backend, są w aliasach", () => {
    expect(Object.keys(LEGACY_TAB_ALIASES)).toEqual(
      expect.arrayContaining(["rekrutacja", "delivery-lead", "rada", "klienci", "zarzad"]),
    );
  });
});
