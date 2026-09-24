/**
 * Kontrakt dostępu do zakładek /insights i identyfikatorów w URL-u.
 *
 * Decyzja D7 (2026-08-31) otworzyła Insights dla każdej roli. Decyzja Artura
 * z 21.09.2026 zawęża ją WYŁĄCZNIE dla zakładki Rada: admin, Finanse i Head of
 * Recruitment. Lustro po stronie API to `BoardReader` na `/api/insights/board`,
 * `/board/yoy` i `/clients/ranking` — zmiana listy ról tutaj bez zmiany tam
 * robi split-brain (menu bez danych albo dane bez menu, #1215).
 */
import { describe, expect, it } from "vitest";

import {
  DEFAULT_INSIGHTS_TAB,
  LEGACY_ANCHOR_CHAPTER,
  LEGACY_TAB_ALIASES,
  RADA_ROLES,
  getDefaultTabForUser,
  getVisibleInsightTabIds,
  resolveChapter,
  resolveInsightsTab,
} from "@/components/insights/InsightsView";
import { CHAPTERS, DEFAULT_CHAPTER } from "@/components/insights/BodyLeasingPanel";

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

const user = (role: string, roles?: string[]): AuthUser =>
  ({
    id: 1,
    email: `${role}@example.com`,
    name: role,
    role,
    ...(roles ? { roles } : {}),
  }) as AuthUser;

describe("dostęp do zakładek Insights", () => {
  it.each(ALL_ROLES)("rola %s widzi Body Leasing", (role) => {
    expect(getVisibleInsightTabIds(user(role))).toContain("body-leasing");
  });

  it.each(["admin", "finance", "head_of_recruitment"] as const)(
    "rola %s widzi Radę",
    (role) => {
      expect(getVisibleInsightTabIds(user(role))).toEqual([
        "body-leasing",
        "rada",
      ]);
    },
  );

  it.each([
    "delivery_lead",
    "talent_community_manager",
    "tac",
    "recruiter",
    "sourcer",
    "user",
    // Praktykant (0373) i tak nie wejdzie na /insights — middleware zawraca
    // go na „Telefony na dziś”; tu tylko pilnujemy, że Rada nie jest dla niego.
    "trainee",
  ] as const)("rola %s NIE widzi Rady", (role) => {
    expect(getVisibleInsightTabIds(user(role))).toEqual(["body-leasing"]);
  });

  it("dodatkowa rola HoR przy głównej roli rekrutera otwiera Radę", () => {
    // `hasRole` patrzy na wszystkie role konta, nie tylko na główną.
    expect(
      getVisibleInsightTabIds(user("recruiter", ["recruiter", "head_of_recruitment"])),
    ).toContain("rada");
  });

  it("lista ról Rady to dokładnie lustro BoardReader", () => {
    expect([...RADA_ROLES].sort()).toEqual(
      ["admin", "finance", "head_of_recruitment"].sort(),
    );
  });

  it("przed hydracją (brak usera) lista nie jest zawężana", () => {
    // Brak usera to „jeszcze nie wiemy" — inaczej `?tab=rada` admina zostałby
    // przepisany na Body Leasing, zanim store zdąży się wczytać.
    expect(getVisibleInsightTabIds(null as unknown as AuthUser)).toHaveLength(2);
  });

  it.each(ALL_ROLES)("rola %s ma tę samą zakładkę domyślną", (role) => {
    expect(getDefaultTabForUser(user(role))).toBe(DEFAULT_INSIGHTS_TAB);
  });

  it("domyślna zakładka to Body Leasing, domyślny rozdział to Rywalizacja", () => {
    expect(DEFAULT_INSIGHTS_TAB).toBe("body-leasing");
    expect(DEFAULT_CHAPTER).toBe("rywalizacja");
  });
});

describe("identyfikator zakładki w URL-u", () => {
  it.each(["body-leasing", "rada"] as const)(
    "znany identyfikator %s przechodzi bez przepisywania adresu",
    (tab) => {
      expect(resolveInsightsTab(tab)).toEqual({ tab, rewrite: false });
    },
  );

  it.each([
    ["rekrutacja", "body-leasing", "wyniki"],
    ["delivery-lead", "body-leasing", "klienci"],
    ["klienci", "body-leasing", "klienci"],
  ] as const)(
    "stary link ?tab=%s otwiera %s / rozdział %s",
    (legacy, tab, chapter) => {
      expect(resolveInsightsTab(legacy)).toEqual({ tab, rewrite: true, chapter });
    },
  );

  it("stary link ?tab=zarzad otwiera Radę", () => {
    expect(resolveInsightsTab("zarzad")).toEqual({ tab: "rada", rewrite: true });
  });

  it("każdy alias wskazuje na istniejącą zakładkę i rozdział", () => {
    const known = getVisibleInsightTabIds(user("admin"));
    const chapters = CHAPTERS.map((c) => c.id);
    for (const target of Object.values(LEGACY_TAB_ALIASES)) {
      expect(known).toContain(target.tab);
      if (target.chapter) expect(chapters).toContain(target.chapter);
    }
    for (const chapter of Object.values(LEGACY_ANCHOR_CHAPTER)) {
      expect(chapters).toContain(chapter);
    }
  });

  it("brak parametru i literówka wracają na zakładkę domyślną", () => {
    expect(resolveInsightsTab(null)).toEqual({
      tab: DEFAULT_INSIGHTS_TAB,
      rewrite: true,
    });
    expect(resolveInsightsTab("bodyleasing")).toEqual({
      tab: DEFAULT_INSIGHTS_TAB,
      rewrite: true,
    });
  });

  it("Rada spoza listy dozwolonych nie zostaje aktywna", () => {
    // Rekruter wchodzący w link `?tab=rada` ląduje na Body Leasing, a nie
    // w pustym kontenerze udającym utratę danych.
    expect(resolveInsightsTab("rada", ["body-leasing"])).toEqual({
      tab: "body-leasing",
      rewrite: true,
    });
    expect(resolveInsightsTab("zarzad", ["body-leasing"])).toEqual({
      tab: "body-leasing",
      rewrite: true,
    });
  });
});

describe("rozdział w URL-u", () => {
  it("jawne ?ch= wygrywa", () => {
    expect(resolveChapter("klienci", "#liga", "wyniki")).toBe("klienci");
  });

  it("stara kotwica wygrywa z rozdziałem aliasu", () => {
    // `?tab=rekrutacja#liga` znaczy Ligę, a nie Wyniki.
    expect(resolveChapter(null, "#liga", "wyniki")).toBe("rywalizacja");
    expect(resolveChapter(null, "#zrodla", undefined)).toBe("wyniki");
  });

  it("bez kotwicy decyduje alias, a bez aliasu — rozdział domyślny", () => {
    expect(resolveChapter(null, "", "klienci")).toBe("klienci");
    expect(resolveChapter(null, "", undefined)).toBe(DEFAULT_CHAPTER);
    expect(resolveChapter("literowka", "#nieznana", undefined)).toBe(
      DEFAULT_CHAPTER,
    );
  });
});
