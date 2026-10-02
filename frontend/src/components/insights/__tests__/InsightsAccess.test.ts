/**
 * Kontrakt dostępu do widoków /insights i adresów sprzed przebudowy.
 *
 * Przebudowa 24.09.2026: pięć widoków. Firma (pieniądze) — WYŁĄCZNIE
 * z uprawnieniem „Moduł Finanse” (domyślnie administrator i Finanse); Head of
 * Recruitment domyślnie nie widzi kwot (decyzja Artura). Lustro po stronie API
 * to `BoardReader` na `/api/insights/board` i `/clients/ranking`, który pyta
 * o to samo uprawnienie — inna reguła tutaj niż tam robi split-brain (#1215).
 */
import { describe, expect, it } from "vitest";

import {
  DEFAULT_INSIGHTS_TAB,
  FIRMA_PERMISSION,
  LEGACY_ANCHORS,
  LEGACY_TAB_ALIASES,
  getDefaultTabForUser,
  getVisibleInsightTabIds,
  resolveInsightsLocation,
  type TabId,
} from "@/components/insights/InsightsView";
import { REPORTS, reportById, seesBoardTrend, visibleReports } from "@/lib/insights-reports";
import type { Permission } from "@/lib/permissions";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";

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

/**
 * Konto testowe. Bez `granted` profil nie niesie migawki uprawnień, więc liczą
 * się domyślne uprawnienia ról; z `granted` niesie pełną migawkę — dokładnie
 * te uprawnienia (z zależnościami), niezależnie od roli.
 */
const user = (
  role: string,
  extra: { roles?: string[]; capabilities?: string[]; granted?: Permission[] } = {},
): NonNullable<AuthUser> => {
  const { granted, ...rest } = extra;
  return {
    id: 1,
    email: `${role}@example.com`,
    name: role,
    role,
    ...rest,
    ...(granted ? { effective_action_access: permissionSnapshot(...granted) } : {}),
  } as NonNullable<AuthUser>;
};

const ALL_TABS: TabId[] = ["rywalizacja", "moj-miesiac", "zespol", "firma", "raporty"];

describe("widoki Insights per rola", () => {
  it.each(ALL_ROLES)("rola %s widzi Rywalizację, Zespół i Raporty", (role) => {
    const tabs = getVisibleInsightTabIds(user(role));
    expect(tabs).toEqual(expect.arrayContaining(["rywalizacja", "zespol", "raporty"]));
    expect(tabs[0]).toBe("rywalizacja");
  });

  it("Firma idzie za uprawnieniem „Moduł Finanse” — domyślnie mają je administrator i Finanse", () => {
    expect(FIRMA_PERMISSION).toBe("finance_module");
    for (const role of ALL_ROLES) {
      const sees = getVisibleInsightTabIds(user(role)).includes("firma");
      expect(sees, role).toBe(role === "admin" || role === "finance");
    }
  });

  it("Head of Recruitment domyślnie NIE widzi Firmy (decyzja 24.09.2026)", () => {
    expect(getVisibleInsightTabIds(user("head_of_recruitment"))).not.toContain(
      "firma",
    );
  });

  it("hybryda HoR + Finanse widzi Firmę — rola Finanse ma uprawnienie domyślnie", () => {
    expect(
      getVisibleInsightTabIds(
        user("head_of_recruitment", { roles: ["finance"] }),
      ),
    ).toContain("firma");
  });

  it.each(["head_of_recruitment", "recruiter", "delivery_lead"])(
    "%s z nadanym „Modułem Finanse” widzi Firmę",
    (role) => {
      expect(
        getVisibleInsightTabIds(user(role, { granted: ["finance_module"] })),
      ).toContain("firma");
    },
  );

  it("Finanse z wyłączonym „Modułem Finanse” nie widzą Firmy mimo roli", () => {
    expect(
      getVisibleInsightTabIds(
        user("finance", { granted: ["delivery_view", "amounts_view"] }),
      ),
    ).not.toContain("firma");
  });

  it("sam podgląd kwot („Stawki i kwoty: podgląd”) nie otwiera Firmy", () => {
    // Delivery Lead widzi kwoty swoich klientów, a pieniędzy firmy — nie.
    expect(getVisibleInsightTabIds(user("delivery_lead"))).not.toContain("firma");
    expect(
      getVisibleInsightTabIds(user("recruiter", { granted: ["amounts_view"] })),
    ).not.toContain("firma");
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

  it("ranking klientów z kwotami — za uprawnieniem „Moduł Finanse”", () => {
    // Domyślni posiadacze: administrator i Finanse.
    expect(ids("admin")).toContain("ranking-klientow");
    expect(ids("finance")).toContain("ranking-klientow");
    expect(ids("head_of_recruitment")).not.toContain("ranking-klientow");
    expect(ids("recruiter")).not.toContain("ranking-klientow");
    // Nadane rekruterowi — widzi; wyłączone Finansom — nie widzą.
    expect(ids("recruiter", { granted: ["finance_module"] })).toContain(
      "ranking-klientow",
    );
    expect(
      ids("finance", { granted: ["delivery_view", "amounts_view"] }),
    ).not.toContain("ranking-klientow");
  });

  it("dopiski raportów o pieniądzach nazywają uprawnienie, nie role", () => {
    expect(reportById("ranking-klientow").note).toBe("uprawnienie „Moduł Finanse”");
    expect(reportById("rok-do-roku").note).toBe("kwoty z uprawnieniem „Moduł Finanse”");
    for (const id of ["ranking-klientow", "rok-do-roku"] as const) {
      expect(reportById(id).note).not.toMatch(/admin i Finanse/);
    }
  });

  it("tabele rok do roku Rady: „Moduł Finanse” albo Head of Recruitment (bez kwot)", () => {
    expect(seesBoardTrend(user("admin"))).toBe(true);
    expect(seesBoardTrend(user("finance"))).toBe(true);
    // HoR wchodzi rolą — kwoty redaguje mu serwer.
    expect(seesBoardTrend(user("head_of_recruitment"))).toBe(true);
    expect(seesBoardTrend(user("recruiter", { granted: ["finance_module"] }))).toBe(true);
    // Sama rola Finanse bez uprawnienia nie wystarcza; reszta ról też nie.
    expect(
      seesBoardTrend(user("finance", { granted: ["delivery_view", "amounts_view"] })),
    ).toBe(false);
    expect(seesBoardTrend(user("delivery_lead"))).toBe(false);
    expect(seesBoardTrend(user("recruiter"))).toBe(false);
    expect(seesBoardTrend(null)).toBe(false);
    // Raport zostaje widoczny dla każdego — bez tabel Rady ma statystyki roczne.
    expect(ids("recruiter")).toContain("rok-do-roku");
  });

  it("rekrutacje bez ruchu — tylko z view_team_kpi", () => {
    expect(
      ids("head_of_recruitment", { capabilities: ["view_team_kpi"] }),
    ).toContain("bez-ruchu");
    expect(ids("recruiter")).not.toContain("bez-ruchu");
  });

  it("propozycje AI — admin, HoR i Delivery Lead", () => {
    expect(ids("admin")).toContain("propozycje-ai");
    expect(ids("head_of_recruitment")).toContain("propozycje-ai");
    expect(ids("delivery_lead")).toContain("propozycje-ai");
    expect(ids("recruiter")).not.toContain("propozycje-ai");
    expect(ids("finance")).not.toContain("propozycje-ai");
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
