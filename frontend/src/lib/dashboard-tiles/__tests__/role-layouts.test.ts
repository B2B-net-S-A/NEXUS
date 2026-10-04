import { describe, expect, it } from "vitest";

import { templateAvailability } from "@/lib/dashboard-tiles/catalog";
import { GRID_COLUMNS } from "@/lib/dashboard-tiles/layout";
import {
  announcedTile,
  recommendedTemplates,
  roleDefaultTiles,
  roleLayoutLabel,
  stableTileId,
} from "@/lib/dashboard-tiles/role-layouts";
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

const keysOf = (u: User) => recommendedTemplates(u).templates.map((t) => t.key);

describe("układ pulpitu dla roli", () => {
  it("rekruter: moje rekrutacje, „Dziś”, requesty z mojej kategorii, moi ludzie, tydzień", () => {
    expect(keysOf(user("recruiter"))).toEqual([
      "my_recruitments",
      "today_cycle",
      "request_board_my_category",
      "my_people",
      "my_week",
    ]);
    expect(roleLayoutLabel(user("recruiter"))).toBe("Rekruter");
  });

  it("Delivery Lead: sprawy klientów, kontrakty i requesty, w których jest DL-em", () => {
    const keys = keysOf(user("delivery_lead"));
    expect(keys[0]).toBe("my_clients_alerts");
    expect(keys).toContain("request_board_my_lead");
    expect(keys).toContain("today_cycle");
  });

  it("Head of Recruitment: „Gdzie stoi”, lejek zespołu i pełna tablica requestów", () => {
    const keys = keysOf(user("head_of_recruitment"));
    expect(keys).toEqual(expect.arrayContaining(["team_signals", "team_funnel_week", "request_board"]));
    expect(keys).not.toContain("my_recruitments");
  });

  it("DL + rekruter: suma układów z jedną tablicą requestów (zakres DL wygrywa)", () => {
    const u = user("delivery_lead", { roles: ["delivery_lead", "recruiter"] });
    const templates = recommendedTemplates(u).templates;
    const boards = templates.filter((t) => t.type === "request_board");
    expect(boards.map((t) => t.key)).toEqual(["request_board_my_lead"]);
    expect(new Set(templates.map((t) => t.key)).size).toBe(templates.length);
    expect(roleLayoutLabel(u)).toBe("Delivery Lead + Rekruter");
  });

  it("Head z rolą rekrutera nie dostaje kafelków pracy rekrutera", () => {
    const u = user("head_of_recruitment", { roles: ["head_of_recruitment", "recruiter"] });
    expect(keysOf(u)).not.toContain("my_recruitments");
    expect(roleLayoutLabel(u)).toBe("Head of Recruitment");
  });

  it("podgląd (bez roli z układem) dostaje kalendarz i notatkę", () => {
    expect(keysOf(user("user"))).toEqual(["calendar_today", "note"]);
    expect(roleLayoutLabel(user("user"))).toBeNull();
  });

  it("układ nigdy nie zawiera kafelka niedostępnego dla konta", () => {
    for (const role of ["admin", "finance", "head_of_recruitment", "delivery_lead", "talent_community_manager", "recruiter", "user"] as UserRole[]) {
      const u = user(role);
      for (const t of recommendedTemplates(u).templates) {
        expect(templateAvailability(t, u).ok).toBe(true);
      }
    }
  });

  it("kafelki leżą na siatce bez nachodzenia i mają stałe id", () => {
    const u = user("delivery_lead");
    const tiles = roleDefaultTiles(u);
    for (const t of tiles) expect(t.x + t.w).toBeLessThanOrEqual(GRID_COLUMNS);
    for (let i = 0; i < tiles.length; i += 1) {
      for (let j = i + 1; j < tiles.length; j += 1) {
        const a = tiles[i];
        const b = tiles[j];
        const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
        expect(overlap).toBe(false);
      }
    }
    expect(roleDefaultTiles(u).map((t) => t.id)).toEqual(tiles.map((t) => t.id));
    expect(stableTileId("role:a")).not.toBe(stableTileId("role:b"));
    expect(stableTileId("role:a")).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$/);
  });
});

describe("announcedTile", () => {
  it("ogłasza „Requesty i obłożenie” osobie z ułożonym pulpitem bez tego kafelka", () => {
    const admin = user("admin");
    expect(announcedTile(admin, [{ type: "note" }], new Set())?.type).toBe("request_board");
    expect(announcedTile(admin, [{ type: "request_board" }], new Set())).toBeNull();
    expect(announcedTile(admin, [{ type: "note" }], new Set(["request_board"]))).toBeNull();
  });

  it("rekruterowi z tablicą ogłasza „Dziś”", () => {
    const u = user("recruiter");
    expect(announcedTile(u, [{ type: "request_board" }], new Set())?.type).toBe("today_cycle");
  });

  it("nie ogłasza kafelka roli, której nie jest polecany", () => {
    expect(announcedTile(user("finance"), [{ type: "note" }], new Set())).toBeNull();
  });
});
