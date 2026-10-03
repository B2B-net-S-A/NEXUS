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

import { accessSnapshot } from "./fixtures/access-snapshot";

// `user(role, access)` to profil bez kompletu uprawnień z serwera: pozycje
// z `gate.permission` liczą się wtedy z domyślnych uprawnień ról.
// `accessSnapshot(...)` to profil po `GET /api/auth/me`.
type U ={ role: string; roles: string[]; effective_section_access: Record<string, string> };
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

  it("Reguły CV: DL z zapisem Delivery tak, bez zapisu nie, Finanse domyślnie nie", () => {
    expect(can(user("delivery_lead", { delivery: "write" }), "cv")).toBe(true);
    expect(can(user("delivery_lead", { delivery: "read" }), "cv")).toBe(false);
    expect(can(user("finance", { delivery: "write" }), "cv")).toBe(false);
  });

  it("Reguły CV idą za uprawnieniem „Klienci: dodawanie i edycja”, nie za rolą", () => {
    const see = (account: ReturnType<typeof accessSnapshot>) =>
      canSeeSettingsItem(account, item("cv"));

    expect(see(accessSnapshot("admin"))).toBe(true);
    expect(see(accessSnapshot("delivery_lead"))).toBe(true);
    // Rekruter z nadanym uprawnieniem widzi pozycję, DL z wyłączonym — nie.
    expect(see(accessSnapshot("recruiter", { grant: ["clients_edit"] }))).toBe(true);
    expect(see(accessSnapshot("delivery_lead", { revoke: ["clients_edit"] }))).toBe(false);
    // Samo „Kontrakty i zamówienia” (zapis w Delivery) to nie reguły CV.
    expect(see(accessSnapshot("finance"))).toBe(false);
    expect(see(accessSnapshot("talent_community_manager"))).toBe(false);
    // Uprawnienie nadane roli Finanse jest decyzją administratora — filtr
    // „Finanse widzą tylko swoje powierzchnie” go nie zasłania.
    expect(see(accessSnapshot("finance", { grant: ["clients_edit"] }))).toBe(true);
    // Stary wyjątek ograniczający sekcję Delivery zostaje sufitem.
    expect(
      see(accessSnapshot("delivery_lead", { sectionCaps: { delivery: "read" } })),
    ).toBe(false);
  });

  it("Historia zdarzeń idzie za „Moduł Finanse” (lustro FinanceModuleUser)", () => {
    const see = (account: ReturnType<typeof accessSnapshot>) =>
      canSeeSettingsItem(account, item("history"));

    expect(see(accessSnapshot("admin"))).toBe(true);
    expect(see(accessSnapshot("finance"))).toBe(true);
    expect(see(accessSnapshot("delivery_lead"))).toBe(false);
    expect(see(accessSnapshot("head_of_recruitment", { grant: ["finance_module"] }))).toBe(
      true,
    );
    expect(see(accessSnapshot("finance", { revoke: ["finance_module"] }))).toBe(false);
  });

  it("Finanse bez admina widzą swoje powierzchnie i Outlooka (U6, 22.09)", () => {
    const f = user("finance", { finance: "write", insights: "read" });
    const listed = SETTINGS_ITEMS.filter((i) => !i.hidden && canSeeSettingsItem(f as never, i)).map((i) => i.id);
    expect(listed.sort()).toEqual(["assign", "contracts", "history", "my-notifications", "outlook", "rates"]);
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

  it("Biblioteka ról: ta sama bramka co słownik (admin i HoR z zapisem Sourcing)", () => {
    expect(can(user("admin", { sourcing: "write" }), "roles")).toBe(true);
    expect(can(user("head_of_recruitment", { sourcing: "write" }), "roles")).toBe(true);
    expect(can(user("head_of_recruitment", { sourcing: "read" }), "roles")).toBe(false);
    expect(can(user("delivery_lead", { sourcing: "write" }), "roles")).toBe(false);
    expect(can(user("recruiter", { sourcing: "write" }), "roles")).toBe(false);
    expect(item("roles").area).toBe("rec");
    expect(item("roles").hidden).toBeFalsy();
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
    for (const role of ["delivery_lead", "recruiter", "finance", "trainee"]) {
      expect(can(user(role, {}), "trainee-rules")).toBe(false);
    }
  });

  it("ma własną trasę w obszarze Rekrutacja", () => {
    expect(item("trainee-rules").area).toBe("rec");
    expect(findSettingsItemByRoute("/settings/trainee-rules")?.id).toBe("trainee-rules");
  });
});

describe("settings-registry — portale ogłoszeniowe (RocketJobs / JustJoin.IT)", () => {
  it("widzi je wyłącznie admin, w obszarze System", () => {
    expect(can(user("admin", {}), "job-boards")).toBe(true);
    for (const role of ["head_of_recruitment", "delivery_lead", "recruiter", "finance"]) {
      expect(can(user(role, {}), "job-boards")).toBe(false);
    }
    expect(item("job-boards").area).toBe("sys");
    expect(item("job-boards").route).toBeUndefined();
  });

  it("znajduje się po nazwie portalu", () => {
    const admin = user("admin", { system_admin: "write" });
    expect(searchSettingsItems(admin as never, "rocketjobs").map((i) => i.id)).toEqual(["job-boards"]);
  });
});
