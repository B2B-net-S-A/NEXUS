/**
 * Kontrakt dostępu do widoków /insights i adresów sprzed przebudowy.
 *
 * Przebudowa 24.09.2026: pięć widoków. Firma (pieniądze) — WYŁĄCZNIE
 * z uprawnieniem „Wyniki firmy” (domyślnie administrator); Head of
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
  "recruiter",
  "user",
  "trainee",
  "board",
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

const ALL_TABS: TabId[] = ["rywalizacja", "moj-miesiac", "zespol", "rytm", "firma", "zrodla", "zasady", "raporty"];

describe("widoki Insights per rola", () => {
  it.each(ALL_ROLES)("rola %s widzi Rywalizację, Zespół i Raporty", (role) => {
    const tabs = getVisibleInsightTabIds(user(role));
    expect(tabs).toEqual(expect.arrayContaining(["rywalizacja", "zespol", "raporty"]));
    // Rada nadzorcza: Rywalizacja zostaje, ale ostatnia (decyzja 22.10.2026).
    expect(tabs[0]).toBe(role === "board" ? "firma" : "rywalizacja");
  });

  it("Rytm dnia widzą tylko Head of Recruitment i admin (29.10.2026)", () => {
    for (const role of ALL_ROLES) {
      const sees = getVisibleInsightTabIds(user(role)).includes("rytm");
      expect(sees, role).toBe(role === "admin" || role === "head_of_recruitment");
    }
  });

  it("Rada nadzorcza bez widoku w adresie ląduje na Firmie", () => {
    const tabs = getVisibleInsightTabIds(user("board"));
    expect(resolveInsightsLocation({ tab: null, ch: null, report: null, hash: "" }, tabs).tab).toBe(
      "firma",
    );
    expect(
      resolveInsightsLocation(
        { tab: null, ch: null, report: null, hash: "" },
        getVisibleInsightTabIds(user("recruiter")),
      ).tab,
    ).toBe("rywalizacja");
  });

  it("Rada nadzorcza: Firma pierwsza, Rywalizacja ostatnia", () => {
    expect(getVisibleInsightTabIds(user("board"))).toEqual([
      "firma",
      "zespol",
      "raporty",
      "rywalizacja",
    ]);
  });

  it("Firma idzie za uprawnieniem „Wyniki firmy” — domyślnie ma je administrator", () => {
    expect(FIRMA_PERMISSION).toBe("company_results");
    for (const role of ALL_ROLES) {
      const sees = getVisibleInsightTabIds(user(role)).includes("firma");
      // Rada nadzorcza (0490) wchodzi rolą; Finanse pracują na pojedynczych
      // rekordach (decyzja Artura 02.11.2026).
      expect(sees, role).toBe(role === "admin" || role === "board");
    }
  });

  it("Head of Recruitment domyślnie NIE widzi Firmy (decyzja 24.09.2026)", () => {
    expect(getVisibleInsightTabIds(user("head_of_recruitment"))).not.toContain(
      "firma",
    );
  });

  it("sam „Moduł Finanse” nie otwiera Firmy", () => {
    expect(
      getVisibleInsightTabIds(user("recruiter", { granted: ["finance_module"] })),
    ).not.toContain("firma");
  });

  it.each(["head_of_recruitment", "recruiter", "delivery_lead"])(
    "%s z nadanymi „Wynikami firmy” widzi Firmę",
    (role) => {
      expect(
        getVisibleInsightTabIds(user(role, { granted: ["company_results"] })),
      ).toContain("firma");
    },
  );

  it("Finanse z nadanymi „Wynikami firmy” widzą Firmę", () => {
    expect(
      getVisibleInsightTabIds(user("finance", { granted: ["company_results"] })),
    ).toContain("firma");
  });

  it("sam podgląd kwot („Stawki i kwoty: podgląd”) nie otwiera Firmy", () => {
    // Delivery Lead widzi kwoty swoich klientów, a pieniędzy firmy — nie.
    expect(getVisibleInsightTabIds(user("delivery_lead"))).not.toContain("firma");
    expect(
      getVisibleInsightTabIds(user("recruiter", { granted: ["amounts_view"] })),
    ).not.toContain("firma");
  });

  it("Mój miesiąc mają role z własnymi KPI (lustro backendu)", () => {
    for (const role of ["recruiter", "delivery_lead"]) {
      expect(getVisibleInsightTabIds(user(role))).toContain("moj-miesiac");
    }
    for (const role of ["admin", "finance", "head_of_recruitment", "user"]) {
      expect(getVisibleInsightTabIds(user(role))).not.toContain("moj-miesiac");
    }
  });

  it("przed hydracją auth pokazuje wszystkie widoki", () => {
    expect(getVisibleInsightTabIds(null)).toEqual(ALL_TABS);
  });

  it("domyślny widok to Rywalizacja dla każdego poza Radą (Firma)", () => {
    expect(DEFAULT_INSIGHTS_TAB).toBe("rywalizacja");
    for (const role of ALL_ROLES) {
      expect(getDefaultTabForUser(user(role))).toBe(role === "board" ? "firma" : "rywalizacja");
    }
  });
});

describe("raporty per rola", () => {
  const ids = (role: string, extra = {}) =>
    visibleReports(user(role, extra)).map((r) => r.id);

  it("ranking klientów z kwotami — za uprawnieniem „Wyniki firmy”", () => {
    // Domyślnie administrator; Rada wchodzi rolą.
    expect(ids("admin")).toContain("ranking-klientow");
    expect(ids("finance")).not.toContain("ranking-klientow");
    expect(ids("board")).toContain("ranking-klientow");
    expect(ids("head_of_recruitment")).not.toContain("ranking-klientow");
    expect(ids("recruiter")).not.toContain("ranking-klientow");
    // Nadane rekruterowi — widzi; sam „Moduł Finanse” — nie.
    expect(ids("recruiter", { granted: ["company_results"] })).toContain(
      "ranking-klientow",
    );
    expect(ids("recruiter", { granted: ["finance_module"] })).not.toContain(
      "ranking-klientow",
    );
  });

  it("dopiski raportów o pieniądzach nazywają uprawnienie i Radę, nie listę ról", () => {
    expect(reportById("ranking-klientow").note).toBe(
      "uprawnienie „Wyniki firmy: podsumowania przychodu i marży” albo Rada nadzorcza",
    );
    expect(reportById("rok-do-roku").note).toBe(
      "kwoty z uprawnieniem „Wyniki firmy: podsumowania przychodu i marży” albo dla Rady nadzorczej",
    );
    for (const id of ["ranking-klientow", "rok-do-roku"] as const) {
      expect(reportById(id).note).not.toMatch(/admin i Finanse/);
    }
  });

  it("tabele rok do roku Rady: „Moduł Finanse” albo Head of Recruitment (bez kwot)", () => {
    expect(seesBoardTrend(user("admin"))).toBe(true);
    expect(seesBoardTrend(user("finance"))).toBe(true);
    // HoR wchodzi rolą — kwoty redaguje mu serwer.
    expect(seesBoardTrend(user("head_of_recruitment"))).toBe(true);
    expect(seesBoardTrend(user("board"))).toBe(true);
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

  it("Rada nadzorcza nie widzi raportów-narzędzi zespołu (22.10.2026)", () => {
    const board = visibleReports(user("board", { capabilities: ["view_team_kpi"] })).map((r) => r.id);
    expect(board).not.toContain("kompetencje");
    expect(board).not.toContain("doplyw");
    expect(board).not.toContain("zamkniecia-hit-ratio");
    // Wynik i listy, do których prowadzą widoki, zostają.
    expect(board).toEqual(
      expect.arrayContaining(["akceptacje-w-toku", "bez-ruchu", "ranking-klientow", "rok-do-roku", "hall-of-fame"]),
    );
    const hor = visibleReports(user("head_of_recruitment", { capabilities: ["view_team_kpi"] })).map((r) => r.id);
    expect(hor).toEqual(expect.arrayContaining(["kompetencje", "doplyw", "zamkniecia-hit-ratio"]));
  });

  it("akceptacje w toku — tylko z view_team_kpi (lista ma klientów i DL)", () => {
    expect(visibleReports(user("recruiter")).map((r) => r.id)).not.toContain("akceptacje-w-toku");
    expect(
      visibleReports(user("delivery_lead", { capabilities: ["view_team_kpi"] })).map((r) => r.id),
    ).toContain("akceptacje-w-toku");
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

  it("kotwica wygrywa z aliasem: #zrodla to zakładka Źródła (03.11.2026)", () => {
    expect(
      resolveInsightsLocation({ tab: "rekrutacja", hash: "#zrodla" }),
    ).toMatchObject({ tab: "zrodla", dropHash: true });
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
