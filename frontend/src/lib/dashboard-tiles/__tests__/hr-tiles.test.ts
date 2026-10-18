import { describe, expect, it } from "vitest";

import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";
import type { HrConfig, HrModuleKey } from "@/lib/api/hr";
import {
  HR_TILE_TYPES,
  TILE_TEMPLATES,
  hrTileGate,
  isTemplateOffered,
  templateAvailability,
} from "@/lib/dashboard-tiles/catalog";
import { recommendedTemplates, roleDefaultTiles } from "@/lib/dashboard-tiles/role-layouts";
import type { User, UserRole } from "@/store/auth";

function user(role: UserRole, extra: Partial<User> = {}): User {
  return {
    id: 1,
    email: "x@example.com",
    name: "X",
    role,
    roles: [role],
    is_active: true,
    ...extra,
  } as User;
}

const ALL_MODULES: HrModuleKey[] = [
  "people",
  "leave",
  "time",
  "payroll",
  "lifecycle",
  "care",
  "cases",
  "equipment",
];

function hr(
  open: Partial<Record<HrModuleKey, boolean>> = {},
  me: Partial<HrConfig["me"]> = {},
): HrConfig {
  const modules = Object.fromEntries(ALL_MODULES.map((key) => [key, open[key] ?? false])) as Record<
    HrModuleKey,
    boolean
  >;
  return {
    modules,
    open_modules: modules,
    me: {
      has_profile: false,
      employment_status: null,
      is_manager: false,
      direct_reports: 0,
      is_admin: false,
      people_admin: false,
      payroll: false,
      equipment: false,
      cases: false,
      ...me,
    },
  };
}

const template = (key: string) => TILE_TEMPLATES.find((t) => t.key === key)!;
const ON = { leave: true, time: true, equipment: true };

describe("kafelki „Ludzi w NEXUSIE” w katalogu", () => {
  it("cztery typy mają szablony w kategorii „Czas i ludzie”", () => {
    for (const type of HR_TILE_TYPES) {
      expect(template(type).category).toBe("people");
    }
  });

  it("bez stanu modułów (zapytanie trwa albo padło) kafelków nie ma", () => {
    for (const type of HR_TILE_TYPES) {
      expect(hrTileGate(type, undefined)).toBe("hidden");
      expect(isTemplateOffered(template(type), null)).toBe(false);
    }
    // Pozostałe kafelki stan modułów nie obchodzi.
    expect(hrTileGate("my_tasks", undefined)).toEqual({ ok: true });
  });

  it("wyłączony moduł = kafelka nie ma w katalogu (a nie „brak dostępu”)", () => {
    const off = hr({}, { has_profile: true, is_manager: true, equipment: true });
    for (const type of HR_TILE_TYPES) expect(hrTileGate(type, off)).toBe("hidden");
    // „Mój czas” i „Do akceptacji” żyją, gdy działa urlop ALBO czas pracy.
    expect(hrTileGate("hr_my_time", hr({ time: true }, { has_profile: true }))).toEqual({ ok: true });
    expect(hrTileGate("hr_approvals", hr({ leave: true }, { is_manager: true }))).toEqual({ ok: true });
    // Zastępstwa wynikają z urlopów, sprzęt — z modułu sprzętu.
    expect(hrTileGate("hr_substitution", hr({ time: true }))).toBe("hidden");
    expect(hrTileGate("equipment_tasks", hr({ leave: true, time: true }))).toBe("hidden");
  });

  it("„Mój czas” wymaga kartoteki, „Do akceptacji” — przełożonego, Kadr albo admina", () => {
    const noProfile = hrTileGate("hr_my_time", hr(ON));
    expect(noProfile).toEqual({ ok: false, reason: "Dla osób z kartoteką pracownika — założą ją Kadry" });
    expect(hrTileGate("hr_approvals", hr(ON, { has_profile: true }))).toEqual({
      ok: false,
      reason: "Dla przełożonych i Kadr",
    });
    for (const me of [{ is_manager: true }, { people_admin: true }, { is_admin: true }]) {
      expect(hrTileGate("hr_approvals", hr(ON, me))).toEqual({ ok: true });
    }
  });

  it("„Sprzęt do zrobienia” idzie za uprawnieniem „Sprzęt” (lustro bramki /api/equipment)", () => {
    const config = hr(ON);
    const reception = user("recruiter", { effective_action_access: permissionSnapshot("equipment") });
    const recruiter = user("recruiter", { effective_action_access: permissionSnapshot() });
    expect(templateAvailability(template("equipment_tasks"), reception, config).ok).toBe(true);
    const denied = templateAvailability(template("equipment_tasks"), recruiter, config);
    expect(denied.ok).toBe(false);
    expect(denied.ok ? "" : denied.reason).toMatch(/^Wymaga uprawnienia „Sprzęt/);
  });

  it("templateAvailability bez stanu modułów odmawia kafelkom modułu ze zdaniem", () => {
    const result = templateAvailability(template("hr_substitution"), user("recruiter"));
    expect(result).toEqual({ ok: false, reason: "Moduł „Ludzi w NEXUSIE” jest wyłączony" });
  });
});

describe("kafelki „Ludzi” w układzie roli", () => {
  const keys = (u: User, config?: HrConfig) =>
    recommendedTemplates(u, { hr: config }).templates.map((t) => t.key);

  it("Pracownik z kartoteką dostaje „Mój czas”", () => {
    expect(keys(user("employee"), hr(ON, { has_profile: true }))).toEqual(["hr_my_time"]);
  });

  it("bez stanu modułów albo przy wyłączonych modułach układ ich nie ma", () => {
    expect(keys(user("employee"))).toEqual([]);
    expect(keys(user("employee"), hr({}, { has_profile: true }))).toEqual([]);
  });

  it("osoba z uprawnieniem „Sprzęt” dostaje „Sprzęt do zrobienia” na końcu układu roli", () => {
    const reception = user("recruiter", { effective_action_access: permissionSnapshot("equipment") });
    const withModule = keys(reception, hr(ON, { equipment: true }));
    expect(withModule[withModule.length - 1]).toBe("equipment_tasks");
    expect(withModule.slice(0, -1)).toEqual(keys(user("recruiter"), hr(ON)));
    // Moduł sprzętu wyłączony — kafelka nie ma.
    expect(keys(reception, hr({ leave: true }))).not.toContain("equipment_tasks");
  });

  it("administrator (ma „Sprzęt” z urzędu) nie dostaje kafelka recepcji", () => {
    expect(keys(user("admin"), hr(ON, { is_admin: true, equipment: true }))).not.toContain(
      "equipment_tasks",
    );
  });

  it("pozostałe kafelki modułu nie trafiają do układów ról — są do wyboru w katalogu", () => {
    for (const role of ["recruiter", "delivery_lead", "head_of_recruitment", "finance"] as UserRole[]) {
      const placed = keys(user(role), hr(ON, { has_profile: true, is_manager: true }));
      expect(placed).not.toContain("hr_substitution");
      expect(placed).not.toContain("hr_approvals");
      expect(placed).not.toContain("hr_my_time");
    }
  });

  it("kafelek z układu leży na siatce", () => {
    const tiles = roleDefaultTiles(user("employee"), { hr: hr(ON, { has_profile: true }) });
    expect(tiles).toHaveLength(1);
    expect(tiles[0]).toMatchObject({ type: "hr_my_time", x: 0, y: 0, w: 6, h: 3 });
  });
});
