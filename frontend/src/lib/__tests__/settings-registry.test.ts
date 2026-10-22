import { describe, expect, it } from "vitest";

import {
  LEGACY_SETTINGS_TABS,
  SETTINGS_ITEMS,
  canSeeSettingsItem,
  findSettingsItem,
  findSettingsItemByRoute,
  groupedAreaItems,
  listedSettingsAreas,
  listedSettingsItems,
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
    const listed = (hrProgram: boolean) =>
      SETTINGS_ITEMS.filter((i) => !i.hidden && canSeeSettingsItem(f as never, i, { hrProgram }))
        .map((i) => i.id)
        .sort();
    // „Płace” (17.10.2026) — Finanse mają to uprawnienie z roli (D2), ale tylko
    // przy włączonym programie „Ludzie w NEXUSIE” (18.10.2026).
    // Outlook jest od 20.10.2026 częścią ekranu „Moje konto” (`my-notifications`),
    // a pod adresem `?item=outlook` dalej otwiera się Finansom.
    expect(listed(false)).toEqual(["assign", "contracts", "history", "my-notifications", "rates"]);
    expect(listed(true)).toEqual(["assign", "contracts", "history", "my-notifications", "payroll", "rates"]);
    expect(canSeeSettingsItem(f as never, findSettingsItem("outlook")!)).toBe(true);
  });

  it("Szablony maili: każdy z capability candidate.write, nie tylko admin (U10)", () => {
    expect(can(user("recruiter", { sourcing: "write" }), "mail")).toBe(true);
    expect(can(user("head_of_recruitment", { sourcing: "write" }), "mail")).toBe(true);
    expect(can(user("recruiter", { sourcing: "read" }), "mail")).toBe(false);
    expect(can(user("user", { sourcing: "write" }), "mail")).toBe(false);
    // Finanse: middleware `/settings/templates` = NON_FINANCE_ROLES.
    expect(can(user("finance", { sourcing: "write" }), "mail")).toBe(false);
  });

  it("„Nazwy z rozmów do przejrzenia”: osobna pozycja dla TCM, tylko przy włączonym programie", () => {
    const tcm = accessSnapshot("talent_community_manager");
    const listed = (on: boolean) =>
      listedSettingsItems(tcm, { hrProgram: on }).map((i) => i.id);
    expect(listed(true)).toContain("skills-review");
    expect(listed(false)).not.toContain("skills-review");
    // Admin i HoR mają ją w Słowniku umiejętności — nie dublujemy pozycji.
    expect(
      listedSettingsItems(accessSnapshot("admin"), { hrProgram: true }).map((i) => i.id),
    ).not.toContain("skills-review");
    expect(resolveSettingsView(tcm, { item: "skills-review" }, { hrProgram: true }).kind).toBe("item");
    expect(resolveSettingsView(tcm, { item: "skills-review" }).kind).toBe("home");
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

  it("„rola” prowadzi też do Powiadomień, a obie pozycje powiadomień nadal się otwierają", () => {
    // Prośba administratora brzmiała „która rola dostaje które powiadomienie”.
    expect(searchSettingsItems(admin as never, "rola").map((i) => i.id)).toContain("notifications");
    expect(item("notifications").description).toMatch(/Która rola dostaje/);
    // Link z dzwonka i stare zakładki przeglądarki wskazują `my-notifications`.
    const mine = resolveSettingsView(user("recruiter", {}) as never, { item: "my-notifications" });
    expect(mine.kind === "item" && mine.area.id).toBe("me");
    expect(resolveSettingsView(user("recruiter", {}) as never, { item: "notifications" }).kind).toBe("home");
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

  it("od 17.10.2026 ukryta: nie ma jej na liście ani w wyszukiwarce, adres działa", () => {
    const admin = user("admin", {}) as never;
    expect(listedSettingsItems(admin).map((i) => i.id)).not.toContain("trainee-rules");
    expect(searchSettingsItems(admin, "praktykant")).toEqual([]);
    expect(item("trainee-rules").hidden).toBe(true);
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

  it("od 21.10.2026 w „Integracjach”: z menu ukryte, po nazwie portalu znajduje się „Integracje”", () => {
    const admin = user("admin", { system_admin: "write" });
    expect(item("job-boards").hidden).toBe(true);
    expect(searchSettingsItems(admin as never, "rocketjobs").map((i) => i.id)).toEqual(["integrations"]);
  });
});

describe("settings-registry — „Jakość QC” (D6, 13.10.2026)", () => {
  it("widzi ją wyłącznie admin z dostępem do Systemu, obok kosztów AI", () => {
    expect(can(user("admin", { system_admin: "write" }), "qc-quality")).toBe(true);
    expect(can(user("admin", { system_admin: "none" }), "qc-quality")).toBe(false);
    for (const role of ["head_of_recruitment", "delivery_lead", "recruiter", "finance"]) {
      expect(can(user(role, { system_admin: "write" }), "qc-quality")).toBe(false);
    }
    expect(item("qc-quality").area).toBe("sys");
    const ids = SETTINGS_ITEMS.map((i) => i.id);
    expect(ids.indexOf("qc-quality")).toBe(ids.indexOf("ai") + 1);
  });

  it("podstrona `/settings/ai/…` należy do najdłuższej pasującej trasy", () => {
    expect(findSettingsItemByRoute("/settings/ai/qc-quality")?.id).toBe("qc-quality");
    expect(findSettingsItemByRoute("/settings/ai")?.id).toBe("ai");
    expect(findSettingsItemByRoute("/settings/ai/inne")?.id).toBe("ai");
  });

  it("znajduje się po „trafność” i „nieprawda”", () => {
    const admin = user("admin", { system_admin: "write" });
    expect(searchSettingsItems(admin as never, "trafność").map((i) => i.id)).toEqual(["qc-quality"]);
    expect(searchSettingsItems(admin as never, "nieprawda").map((i) => i.id)).toEqual(["qc-quality"]);
  });
});

describe("settings-registry — „Klucze API” (konta serwisowe, 14.10.2026)", () => {
  it("widzi je wyłącznie admin z dostępem do Systemu (lustro AdminUser)", () => {
    expect(can(user("admin", { system_admin: "write" }), "api-keys")).toBe(true);
    expect(can(user("admin", { system_admin: "none" }), "api-keys")).toBe(false);
    for (const role of ["head_of_recruitment", "delivery_lead", "recruiter", "finance"]) {
      expect(can(user(role, { system_admin: "write" }), "api-keys")).toBe(false);
    }
  });

  it("ma własną trasę w obszarze System; z menu wchodzi się przez „Integracje” (21.10.2026)", () => {
    expect(item("api-keys").area).toBe("sys");
    expect(item("api-keys").hidden).toBe(true);
    expect(findSettingsItemByRoute("/settings/api-keys")?.id).toBe("api-keys");
    // Trasa z własną stroną nie otwiera się w `?item=`.
    const admin = user("admin", { system_admin: "write" });
    expect(resolveSettingsView(admin as never, { item: "api-keys" }).kind).toBe("home");
  });

  it("po nagłówku, „koncie serwisowym” i „n8n” znajduje się „Integracje”", () => {
    const admin = user("admin", { system_admin: "write" });
    expect(searchSettingsItems(admin as never, "x-api-key").map((i) => i.id)).toEqual(["integrations"]);
    expect(searchSettingsItems(admin as never, "konto serwisowe").map((i) => i.id)).toEqual(["integrations"]);
    expect(searchSettingsItems(admin as never, "n8n").map((i) => i.id)).toEqual(["integrations"]);
    // Samo „klucz” łapie też „Wykluczone placementy” (szukanie po fragmencie).
    expect(searchSettingsItems(admin as never, "klucze api").map((i) => i.id)).toContain("integrations");
  });

  it("„Integracje”: jedna pozycja w grupie, widzi ją tylko admin", () => {
    const admin = user("admin", { system_admin: "write" });
    expect(can(admin, "integrations")).toBe(true);
    expect(can(user("delivery_lead", { system_admin: "write" }), "integrations")).toBe(false);
    const group = listedSettingsItems(admin as never).filter((i) => i.group === "Integracje");
    expect(group.map((i) => i.id)).toEqual(["integrations"]);
  });
});

describe("settings-registry — „Płace” (reguły premii, 17.10.2026)", () => {
  const see = (account: ReturnType<typeof accessSnapshot>) =>
    canSeeSettingsItem(account, item("payroll"), { hrProgram: true });

  it("idzie za uprawnieniem „Płace”, nie za „Kadrami” (lustro require_hr_payroll_admin)", () => {
    expect(see(accessSnapshot("admin"))).toBe(true);
    expect(see(accessSnapshot("finance"))).toBe(true);
    expect(see(accessSnapshot("finance", { revoke: ["payroll"] }))).toBe(false);
    expect(see(accessSnapshot("recruiter", { grant: ["payroll"] }))).toBe(true);
    // Kadry bez „Płac” nie zmieniają reguł premii — mają drogowskaz w „Kadrach”.
    expect(see(accessSnapshot("recruiter", { grant: ["people_admin"] }))).toBe(false);
    expect(see(accessSnapshot("delivery_lead"))).toBe(false);
    expect(see(accessSnapshot("employee"))).toBe(false);
  });

  it("ma własną trasę obok „Kadr” w obszarze Zespół i dostęp", () => {
    expect(item("payroll").area).toBe("team");
    expect(findSettingsItemByRoute("/settings/payroll")?.id).toBe("payroll");
    const ids = SETTINGS_ITEMS.map((i) => i.id);
    expect(ids.indexOf("payroll")).toBe(ids.indexOf("hr") + 1);
    const admin = user("admin", { system_admin: "write" });
    expect(resolveSettingsView(admin as never, { item: "payroll" }).kind).toBe("home");
  });

  it("znajduje się po „premie” i „liga”", () => {
    const finance = accessSnapshot("finance");
    const on = { hrProgram: true };
    expect(searchSettingsItems(finance, "premie", on).map((i) => i.id)).toEqual(["payroll"]);
    expect(searchSettingsItems(finance, "liga", on).map((i) => i.id)).toContain("payroll");
  });
});

describe("settings-registry — wyłączony program „Ludzie w NEXUSIE” (18.10.2026)", () => {
  const HR_ITEMS = ["hr", "payroll", "hr-import"];

  it("nikt, także admin, nie widzi pozycji programu bez włączonego programu", () => {
    const admin = accessSnapshot("admin");
    for (const id of HR_ITEMS) {
      expect(canSeeSettingsItem(admin, item(id))).toBe(false);
      expect(canSeeSettingsItem(admin, item(id), { hrProgram: false })).toBe(false);
      expect(canSeeSettingsItem(admin, item(id), { hrProgram: true })).toBe(true);
    }
    const listed = listedSettingsItems(admin).map((i) => i.id);
    expect(listed.filter((id) => HR_ITEMS.includes(id))).toEqual([]);
  });

  it("wyszukiwarka ich nie znajduje", () => {
    const admin = accessSnapshot("admin");
    expect(searchSettingsItems(admin, "kadry").map((i) => i.id)).not.toContain("hr");
    expect(searchSettingsItems(admin, "premie").map((i) => i.id)).toEqual([]);
    expect(searchSettingsItems(admin, "compass").map((i) => i.id)).not.toContain("hr-import");
  });
});

describe("settings-registry — Importy w Systemie (20.10.2026)", () => {
  it("admin ma jedną pozycję „Importy”; stare pozycje importów są ukryte, adresy zostają", () => {
    const admin = accessSnapshot("admin");
    const listed = listedSettingsItems(admin).map((i) => i.id);
    expect(listed).toContain("imports");
    expect(listed).not.toContain("register-import");
    expect(listed).not.toContain("contract-docs-sharepoint");
    expect(listed).not.toContain("traffit");
    expect(findSettingsItemByRoute("/settings/contract-docs-sharepoint")?.id).toBe(
      "contract-docs-sharepoint",
    );
    expect(searchSettingsItems(admin, "sharepoint").map((i) => i.id)).toEqual(["imports"]);
    // Import z Compassa zostaje w Zespole i dostępie — widzą go Kadry.
    expect(findSettingsItem("hr-import")?.area).toBe("team");
  });

  it("bez admina pozycji „Importy” nie widać", () => {
    expect(listedSettingsItems(accessSnapshot("finance")).map((i) => i.id)).not.toContain("imports");
    expect(listedSettingsItems(accessSnapshot("delivery_lead")).map((i) => i.id)).not.toContain("imports");
  });
});

describe("settings-registry — grupy w obszarze (lewa kolumna, 20.10.2026)", () => {
  it("każda pozycja z menu ma grupę", () => {
    const missing = SETTINGS_ITEMS.filter((i) => !i.hidden && !i.group).map((i) => i.id);
    expect(missing).toEqual([]);
  });

  it("Rekrutacja: grupy w kolejności rejestru, pozycje w swoich grupach", () => {
    const groups = groupedAreaItems(accessSnapshot("admin"), "rec");
    expect(groups.map((g) => g.name)).toEqual(["Proces", "Klienci", "Teksty", "Wiedza"]);
    expect(groups[0].items.map((i) => i.id)).toEqual([
      "stages",
      "ranking",
      "prep-review",
      "kpi-targets",
    ]);
    expect(groups.find((g) => g.name === "Teksty")!.items.map((i) => i.id)).toEqual([
      "mail",
      "job-ad-blocks",
    ]);
  });

  it("grupa bez widocznej pozycji znika — rekruter widzi w Rekrutacji tylko Teksty", () => {
    const groups = groupedAreaItems(accessSnapshot("recruiter"), "rec");
    expect(groups.map((g) => g.name)).toEqual(["Teksty"]);
    expect(groups[0].items.map((i) => i.id)).toEqual(["mail"]);
  });

  it("pozycje programu „Ludzie w NEXUSIE” wchodzą do grupy tylko przy włączonym programie", () => {
    const admin = accessSnapshot("admin");
    const names = (on: boolean) =>
      groupedAreaItems(admin, "team", { hrProgram: on }).map((g) => g.name);
    expect(names(false)).not.toContain("Ludzie w NEXUSIE");
    expect(names(true)).toContain("Ludzie w NEXUSIE");
  });
});

describe("settings-registry — Listy wyboru ukryte (20.10.2026)", () => {
  it("admin nie widzi „Listy wyboru” w menu ani w wyszukiwarce, adres zostaje", () => {
    const admin = accessSnapshot("admin");
    expect(listedSettingsItems(admin).map((i) => i.id)).not.toContain("dict");
    expect(searchSettingsItems(admin, "powody odrzucenia").map((i) => i.id)).not.toContain("dict");
    expect(findSettingsItemByRoute("/settings/dictionaries")?.id).toBe("dict");
    expect(canSeeSettingsItem(admin, item("dict"))).toBe(true);
  });
});

