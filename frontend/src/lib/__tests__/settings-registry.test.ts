import { describe, expect, it } from "vitest";

import {
  LEGACY_SETTINGS_TABS,
  SETTINGS_ITEMS,
  canSeeSettingsItem,
  findSettingsItem,
  findSettingsItemByRoute,
  listedSettingsAreas,
  resolveSettingsView,
  searchSettingsItems,
} from "@/lib/settings-registry";

type U = { role: string; roles: string[]; effective_section_access: Record<string, string> };
const user = (role: string, access: Record<string, string>): U => ({
  role,
  roles: [role],
  effective_section_access: access,
});
const item = (id: string) => findSettingsItem(id)!;
// Rejestr przyjmuje użytkownika w kształcie store'u; testy budują minimalny.
const can = (u: U, id: string) => canSeeSettingsItem(u as never, item(id));

describe("settings-registry — widoczność jak przed przebudową", () => {
  it.each([
    ["admin", { finance: "write" }, true],
    ["finance", { finance: "write" }, true],
    ["finance", { finance: "none" }, false],
    ["delivery_lead", { finance: "write" }, false],
    ["recruiter", { finance: "write" }, false],
  ])("Historia usunięć: %s %j → %s", (role, access, expected) => {
    expect(can(user(role, access), "history")).toBe(expected);
  });

  it.each([
    ["admin", { sourcing: "write" }, true],
    ["delivery_lead", { sourcing: "read" }, true],
    ["head_of_recruitment", { sourcing: "write" }, true],
    ["delivery_lead", { sourcing: "none" }, false],
    ["recruiter", { sourcing: "write" }, false],
    ["finance", { sourcing: "write" }, false],
  ])("Konflikty (pod adresem): %s %j → %s", (role, access, expected) => {
    expect(can(user(role, access), "conflicts")).toBe(expected);
  });

  it("Reguły CV: DL z zapisem Delivery tak, bez zapisu nie, Finanse nigdy", () => {
    expect(can(user("delivery_lead", { delivery: "write" }), "cv")).toBe(true);
    expect(can(user("delivery_lead", { delivery: "read" }), "cv")).toBe(false);
    expect(can(user("finance", { delivery: "write" }), "cv")).toBe(false);
  });

  it("Finanse bez admina widzą swoje powierzchnie i Outlooka (U6, 22.09)", () => {
    const f = user("finance", { finance: "write", insights: "read" });
    const listed = SETTINGS_ITEMS.filter((i) => !i.hidden && canSeeSettingsItem(f as never, i)).map((i) => i.id);
    expect(listed.sort()).toEqual(["assign", "contracts", "history", "outlook", "rates"]);
  });

  it("Szablony maili: każdy z capability candidate.write, nie tylko admin (U10)", () => {
    expect(can(user("recruiter", { sourcing: "write" }), "mail")).toBe(true);
    expect(can(user("head_of_recruitment", { sourcing: "write" }), "mail")).toBe(true);
    expect(can(user("recruiter", { sourcing: "read" }), "mail")).toBe(false);
    expect(can(user("user", { sourcing: "write" }), "mail")).toBe(false);
    // Finanse: middleware `/settings/templates` = NON_FINANCE_ROLES.
    expect(can(user("finance", { sourcing: "write" }), "mail")).toBe(false);
  });

  it("Słownik umiejętności: admin i HoR z zapisem Sourcing (lustro /api/skills-admin)", () => {
    expect(can(user("admin", { sourcing: "write" }), "skills")).toBe(true);
    expect(can(user("head_of_recruitment", { sourcing: "write" }), "skills")).toBe(true);
    expect(can(user("head_of_recruitment", { sourcing: "read" }), "skills")).toBe(false);
    expect(can(user("delivery_lead", { sourcing: "write" }), "skills")).toBe(false);
    expect(can(user("recruiter", { sourcing: "write" }), "skills")).toBe(false);
    expect(item("skills").area).toBe("rec");
  });

  it("rekruter ma jeden obszar", () => {
    const r = user("recruiter", { pipeline: "write" });
    expect(listedSettingsAreas(r as never).map((a) => a.id)).toEqual(["me"]);
  });

  it("Powiadomienia są dostępne tylko dla admina z dostępem do Systemu", () => {
    expect(can(user("admin", { system_admin: "write" }), "notifications")).toBe(true);
    expect(can(user("admin", { system_admin: "none" }), "notifications")).toBe(false);
    expect(can(user("recruiter", { system_admin: "write" }), "notifications")).toBe(false);
    expect(can(user("finance", { system_admin: "write" }), "notifications")).toBe(false);
  });
});

describe("settings-registry — nawigacja", () => {
  const admin = user("admin", { system_admin: "write", finance: "write", sourcing: "write", pipeline: "write", delivery: "write", insights: "read" });

  it("każde stare `?tab=` prowadzi do istniejącej pozycji", () => {
    for (const id of Object.values(LEGACY_SETTINGS_TABS)) {
      expect(findSettingsItem(id)).toBeDefined();
    }
  });

  it("pozycja z własną trasą nie otwiera się w `?item=`", () => {
    expect(resolveSettingsView(admin as never, { item: "cv" }).kind).toBe("home");
  });

  it("`?item=` wygrywa z `?tab=`", () => {
    const view = resolveSettingsView(admin as never, { item: "mail", tab: "historia" });
    expect(view.kind === "item" && view.item.id).toBe("mail");
  });

  it("podstrona trasy znajduje swoją pozycję", () => {
    expect(findSettingsItemByRoute("/settings/cv-rules")?.id).toBe("cv");
    expect(findSettingsItemByRoute("/settings/linkedin-metrics")).toBeUndefined();
  });

  it("wyszukiwanie ignoruje polskie znaki i wielkość liter", () => {
    expect(searchSettingsItems(admin as never, "USUNIĘCIA").map((i) => i.id)).toEqual(["history"]);
    expect(searchSettingsItems(admin as never, "   ")).toEqual([]);
  });

  it("wyszukuje nadawcę maili w sekcji Powiadomienia", () => {
    expect(searchSettingsItems(admin as never, "nadawca").map((i) => i.id)).toEqual(["notifications"]);
    const view = resolveSettingsView(admin as never, { item: "notifications" });
    expect(view.kind === "item" && view.area.id).toBe("sys");
  });
});

describe("settings-registry — lista telefonów praktykantów (0374)", () => {
  it("widzą ją admin i Head of Recruitment, nikt inny", () => {
    expect(can(user("admin", {}), "trainee-rules")).toBe(true);
    expect(can(user("head_of_recruitment", {}), "trainee-rules")).toBe(true);
    for (const role of ["delivery_lead", "recruiter", "sourcer", "finance", "trainee"]) {
      expect(can(user(role, {}), "trainee-rules")).toBe(false);
    }
  });

  it("ma własną trasę w obszarze Rekrutacja", () => {
    expect(item("trainee-rules").area).toBe("rec");
    expect(findSettingsItemByRoute("/settings/trainee-rules")?.id).toBe("trainee-rules");
  });
});
