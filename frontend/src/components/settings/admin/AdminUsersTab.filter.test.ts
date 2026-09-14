import { describe, expect, it } from "vitest";

import { filterAdminUsers } from "./AdminUsersTab";
import type { AdminUser } from "./types";

function user(overrides: Partial<AdminUser>): AdminUser {
  return {
    id: 1,
    email: "osoba@example.com",
    name: "Osoba",
    role: "recruiter",
    roles: ["recruiter"],
    recruiter_role: null,
    is_active: true,
    activity_count: 0,
    last_activity: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// UAT M11-B02: lista użytkowników bez wyszukiwarki i filtra roli.
describe("filterAdminUsers", () => {
  const users = [
    user({ id: 1, name: "Łukasz Żółw", email: "l.zolw@example.com" }),
    user({
      id: 2,
      name: "Anna Test",
      email: "anna@example.com",
      role: "delivery_lead",
      roles: ["delivery_lead", "tac"],
    }),
    user({ id: 3, name: "Beata Nieaktywna", email: "b@example.com", is_active: false }),
  ];

  it("szuka po imieniu i e-mailu bez względu na polskie znaki", () => {
    const all = { status: "all" as const, role: "all" };
    expect(filterAdminUsers(users, { ...all, search: "lukasz zol" }).map((u) => u.id)).toEqual([1]);
    expect(filterAdminUsers(users, { ...all, search: "ANNA@" }).map((u) => u.id)).toEqual([2]);
  });

  it("filtr roli uwzględnia role dodatkowe i łączy się ze statusem", () => {
    expect(
      filterAdminUsers(users, { status: "all", role: "tac", search: "" }).map((u) => u.id),
    ).toEqual([2]);
    expect(
      filterAdminUsers(users, { status: "active", role: "recruiter", search: "" }).map(
        (u) => u.id,
      ),
    ).toEqual([1]);
  });
});
