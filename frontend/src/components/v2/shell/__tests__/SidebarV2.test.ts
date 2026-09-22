import { describe, expect, it } from "vitest";

import { isNavItemActive, visibleNavSections } from "@/components/v2/shell/SidebarV2";
import { visibleNavHrefs, visiblePrimaryNav } from "@/lib/nav-registry";
import type { UserRole } from "@/store/auth";

// Czysta funkcja zamiast renderu — sidebar ciągnie `next/navigation`,
// react-query, `api` i `useUiStore`, a przedmiotem testu jest wyłącznie zbiór
// pozycji, które dana rola w ogóle dostaje. Od rekrutacji v3 menu to szyna
// + panel „Więcej": „kto co widzi" pytamy o SUMĘ (`visibleNavHrefs`), a to,
// co stoi na szynie, ma osobną asercję niżej.
function hrefs(role: UserRole): string[] {
  return visibleNavHrefs(
    { role, roles: [role] },
    { contactQueueEnabled: false },
  ).sort();
}

describe("visibleNavSections", () => {
  // Sedno naprawy: `finance` dostawała OSOBNE, czteropozycyjne drzewo
  // (Dashboard · Finanse · Pomoc · Ustawienia), mimo że każda lista `roles`
  // w `NAV_SECTIONS` już ją wymienia — menu było jedyną warstwą odcinającą
  // rolę, którą backend przepuszcza wszędzie tam, gdzie recruitera.
  it("finance ma pełne moduły business-read i własny moduł Finanse", () => {
    const finance = hrefs("finance");
    const recruiter = hrefs("recruiter");

    expect(finance).toEqual(
      expect.arrayContaining([
        "/candidates",
        "/jobs",
        "/clients",
        "/contracts",
        "/insights",
        "/finance",
      ]),
    );
    expect(recruiter).not.toContain("/contracts");
    expect(recruiter).not.toContain("/cortex"); // Cortex ukryty w UI (21.09.2026)
  });

  it("moduł Finanse zostaje zamknięty przed rolami operacyjnymi", () => {
    // Bramka sekcji wyliczona z domyślnej polityki nadal blokuje recruitera.
    expect(hrefs("recruiter")).not.toContain("/finance");
    expect(hrefs("admin")).toContain("/finance");
  });

  it("respektuje indywidualne nadanie i odebranie sekcji z backendu", () => {
    const recruiterWithFinance = visibleNavSections(
      {
        role: "recruiter",
        roles: ["recruiter"],
        effective_section_access: {
          sourcing: "write",
          pipeline: "write",
          delivery: "none",
          insights: "read",
          finance: "read",
          system_admin: "none",
        },
      },
      { contactQueueEnabled: false },
    ).flatMap((section) => section.items.map((item) => item.href));

    const deliveryLeadWithoutDelivery = visibleNavSections(
      {
        role: "delivery_lead",
        roles: ["delivery_lead"],
        effective_section_access: {
          sourcing: "write",
          pipeline: "write",
          delivery: "none",
          insights: "read",
          finance: "none",
          system_admin: "none",
        },
      },
      { contactQueueEnabled: false },
    ).flatMap((section) => section.items.map((item) => item.href));

    expect(recruiterWithFinance).toContain("/finance");
    expect(deliveryLeadWithoutDelivery).not.toContain("/clients");
    expect(deliveryLeadWithoutDelivery).not.toContain("/contracts");
  });

  it("ukrywa Generator Umów B2B po indywidualnym odebraniu funkcji", () => {
    const href = "/contracts/b2b-generator";
    const hidden = visibleNavSections(
      {
        role: "talent_community_manager",
        roles: ["talent_community_manager"],
        effective_action_access: { b2b_contract_generator: "none" },
      },
      { contactQueueEnabled: false },
    ).flatMap((section) => section.items.map((item) => item.href));
    const visible = visibleNavSections(
      {
        role: "talent_community_manager",
        roles: ["talent_community_manager"],
        effective_action_access: { b2b_contract_generator: "view" },
      },
      { contactQueueEnabled: false },
    ).flatMap((section) => section.items.map((item) => item.href));

    expect(hidden).not.toContain(href);
    expect(visible).toContain(href);
  });

  it.each([
    "sourcer",
    "recruiter",
    "tac",
    "head_of_recruitment",
  ] as UserRole[])("%s nie widzi sekcji Delivery ani Finansów", (role) => {
    const visible = hrefs(role);
    expect(visible).toEqual(
      expect.arrayContaining(["/candidates", "/jobs", "/insights"]),
    );
    for (const route of [
      "/clients",
      "/contracts",
      "/finance",
    ]) {
      expect(visible).not.toContain(route);
    }
  });

  it("TCM widzi biznes bez Finansów, a Delivery bez akcji zapisu", () => {
    const tcm = hrefs("talent_community_manager");
    expect(tcm).toEqual(
      expect.arrayContaining([
        "/candidates",
        "/jobs",
        "/clients",
        "/contracts",
        "/insights",
      ]),
    );
    expect(tcm).not.toContain("/finance");
  });

  it("Delivery Lead widzi Delivery, ale nie globalny moduł Finansów", () => {
    const dl = hrefs("delivery_lead");
    expect(dl).toEqual(
      expect.arrayContaining([
        "/clients",
        "/contracts",
      ]),
    );
    expect(dl).not.toContain("/finance");
  });

  it("viewer `user` nie dostaje powierzchni kandydackich", () => {
    const viewer = hrefs("user");

    expect(viewer).not.toContain("/candidates");
    expect(viewer).not.toContain("/clients");
    expect(viewer).toContain("/jobs");
    expect(viewer).toContain("/insights");
    expect(viewer).not.toContain("/cortex");
    expect(viewer).not.toContain("/finance");
  });

  it("nie zwraca sekcji bez ani jednej widocznej pozycji", () => {
    for (const role of ["user", "finance", "recruiter"] as UserRole[]) {
      for (const section of visibleNavSections(
        { role, roles: [role] },
        { contactQueueEnabled: false },
      )) {
        expect(section.items.length).toBeGreaterThan(0);
      }
    }
  });

  it("kolejka telefonów wisi na fladze funkcji, nie tylko na roli", () => {
    const withQueue = visibleNavSections(
      { role: "recruiter", roles: ["recruiter"] },
      { contactQueueEnabled: true },
    ).flatMap((s) => s.items.map((i) => i.href));

    expect(withQueue).toContain("/candidates/contact-queue");
    const tcmWithQueue = visibleNavSections(
      {
        role: "talent_community_manager",
        roles: ["talent_community_manager"],
      },
      { contactQueueEnabled: true },
    ).flatMap((s) => s.items.map((i) => i.href));
    expect(tcmWithQueue).toContain("/candidates/contact-queue");
    expect(hrefs("recruiter")).not.toContain("/candidates/contact-queue");
  });
});

describe("szyna vs „Więcej”", () => {
  const primary = (role: UserRole) =>
    visiblePrimaryNav({ role, roles: [role] }, { contactQueueEnabled: true }).map(
      (item) => item.href,
    );

  it("rzadziej używane moduły NIE stoją na szynie, ale nadal są w menu", () => {
    for (const href of [
      "/cv-generator",
      "/contracts/b2b-generator",
      "/help",
      "/settings",
    ]) {
      expect(primary("recruiter")).not.toContain(href);
      expect(hrefs("recruiter")).toContain(href);
    }
  });

  it("viewer `user` ma na szynie tylko to, do czego ma dostęp", () => {
    expect(primary("user")).toEqual([
      "/dashboard",
      "/jobs",
      "/calendar",
      "/insights",
    ]);
  });
});

describe("SIDEBAR_VERTICAL_LAYOUT (UAT B57)", () => {
  it("nie zawiera klas zależnych od stanu — pozycje ikon są te same po rozwinięciu", async () => {
    const { SIDEBAR_VERTICAL_LAYOUT } = await import("@/components/v2/shell/SidebarV2");
    expect(SIDEBAR_VERTICAL_LAYOUT.navSpacing).toBe(SIDEBAR_VERTICAL_LAYOUT.itemSpacing);
    expect(SIDEBAR_VERTICAL_LAYOUT.sectionSlot).toMatch(/\bh-\d+\b/);
    // Odstęp między grupami jest stały (bez wariantów per stan).
    expect(SIDEBAR_VERTICAL_LAYOUT.groupSpacing).toMatch(/^mb-\d+$/);
  });

  it("re-eksportuje TEN SAM kontrakt, którego używa nagłówek grupy", async () => {
    const sidebar = await import("@/components/v2/shell/SidebarV2");
    const more = await import("@/components/v2/shell/SidebarMore");
    expect(sidebar.SIDEBAR_VERTICAL_LAYOUT).toBe(more.SIDEBAR_VERTICAL_LAYOUT);
  });
});

describe("Wyszukiwarka i Talent Radar = tryby ekranu „Kandydaci” (21.09.2026)", () => {
  it("nie stoją w menu żadnej roli", () => {
    const roles: UserRole[] = ["admin", "head_of_recruitment", "delivery_lead", "talent_community_manager", "tac", "recruiter", "finance", "sourcer", "user"];
    for (const role of roles) {
      const items = hrefs(role);
      expect(items).not.toContain("/candidates/search");
      expect(items).not.toContain("/talent-radar");
    }
  });

  it("na wyszukiwarce świeci się „Kandydaci” (nie ma już własnej pozycji)", () => {
    expect(isNavItemActive("/candidates/search", "/candidates")).toBe(true);
    expect(isNavItemActive("/candidates", "/candidates?mode=search")).toBe(true);
    expect(isNavItemActive("/candidates/contact-queue", "/candidates")).toBe(false);
    expect(isNavItemActive("/candidates/123", "/candidates")).toBe(true);
    expect(isNavItemActive("/candidates/searchable", "/candidates")).toBe(true);
  });
});
