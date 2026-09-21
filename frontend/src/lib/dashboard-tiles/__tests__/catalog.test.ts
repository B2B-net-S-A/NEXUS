import { describe, expect, it } from "vitest";

import { TILE_TYPES } from "@/lib/api/userDashboard";
import {
  TILE_DEFINITIONS,
  TILE_TEMPLATES,
  recommendedTemplates,
  templateAvailability,
} from "@/lib/dashboard-tiles/catalog";
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

const template = (key: string) => TILE_TEMPLATES.find((t) => t.key === key)!;

describe("katalog kafelków", () => {
  it("każdy typ ma definicję, a każdy szablon wskazuje istniejący typ", () => {
    for (const type of TILE_TYPES) expect(TILE_DEFINITIONS[type]?.type).toBe(type);
    for (const t of TILE_TEMPLATES) expect(TILE_TYPES).toContain(t.type);
  });

  it("klucze szablonów są unikalne", () => {
    const keys = TILE_TEMPLATES.map((t) => t.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("rekruter nie dodaje kafelków kwot ani nadzoru zespołu — widzi powód", () => {
    const recruiter = user("recruiter");
    const margin = templateAvailability(template("margin_monthly"), recruiter);
    expect(margin.ok).toBe(false);
    expect(margin.ok ? "" : margin.reason).toMatch(/Kwoty/);
    expect(templateAvailability(template("contact_oversight"), recruiter).ok).toBe(false);
    expect(templateAvailability(template("cv_sent_week"), recruiter).ok).toBe(true);
  });

  it("odebrana sekcja wyłącza kafelek tej sekcji", () => {
    const noPipeline = user("recruiter", {
      effective_section_access: {
        sourcing: "read",
        pipeline: "none",
        delivery: "none",
        insights: "read",
        finance: "none",
        system_admin: "none",
      },
    } as Partial<User>);
    const result = templateAvailability(template("my_recruitments"), noPipeline);
    expect(result.ok).toBe(false);
  });
});

describe("polecane na pusty pulpit", () => {
  it("rekruter dostaje swoje cztery kafelki", () => {
    const { roleLabel, templates } = recommendedTemplates(user("recruiter"));
    expect(roleLabel).toBe("Rekruter");
    expect(templates.map((t) => t.key)).toEqual([
      "cv_sent_week",
      "my_recruitments",
      "my_next_steps",
      "calendar_today",
    ]);
  });

  it("Delivery Lead dostaje sprawy klientów i zamówienia", () => {
    const keys = recommendedTemplates(user("delivery_lead")).templates.map((t) => t.key);
    expect(keys).toContain("my_clients_alerts");
    expect(keys).toContain("orders_ending");
  });

  it("polecenia nigdy nie zawierają kafelka niedostępnego dla konta", () => {
    for (const role of ["admin", "finance", "head_of_recruitment", "delivery_lead", "tac", "user"] as UserRole[]) {
      const u = user(role);
      for (const t of recommendedTemplates(u).templates) {
        expect(templateAvailability(t, u).ok).toBe(true);
      }
    }
  });
});
