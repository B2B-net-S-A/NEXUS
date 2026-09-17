/**
 * Widoczność widełek wynagrodzenia (`salary_min`/`salary_max`) w
 * `CreateJobModal` — lustro backendowej bramki
 * `_assert_delivery_lead_finance_write` (`backend/app/api/jobs.py`): DL/TCM
 * bez roli admina nie mogą tworzyć ani zmieniać pól budżetu rekrutacyjnego.
 */
import { describe, expect, it } from "vitest";

import { canManageRecruitmentBudget } from "@/lib/job-budget-access";
import type { User, UserRole } from "@/store/auth";

function withRole(role: UserRole, extra: UserRole[] = []): Pick<
  User,
  "role" | "roles"
> {
  return { role, roles: extra.length ? [role, ...extra] : [role] };
}

describe("canManageRecruitmentBudget", () => {
  it("dopuszcza admina", () => {
    expect(canManageRecruitmentBudget(withRole("admin"))).toBe(true);
  });

  it.each<UserRole>(["delivery_lead", "talent_community_manager"])(
    "odmawia roli %s bez admina",
    (role) => {
      expect(canManageRecruitmentBudget(withRole(role))).toBe(false);
    },
  );

  it.each<UserRole>([
    "tac",
    "recruiter",
    "sourcer",
    "finance",
    "head_of_recruitment",
    "user",
  ])("dopuszcza rolę %s (bramka dotyczy wyłącznie DL/TCM)", (role) => {
    expect(canManageRecruitmentBudget(withRole(role))).toBe(true);
  });

  it("dopuszcza DL-a, gdy admin jest rolą dodatkową", () => {
    // Konta multi-role trzymają uprawnienie w `roles[]` — bramka czytająca
    // wyłącznie `role` odmówiłaby adminowi z rolą główną DL.
    expect(
      canManageRecruitmentBudget({ role: "delivery_lead", roles: ["admin"] }),
    ).toBe(true);
  });

  it("odmawia TCM-a, gdy `roles` niesie tylko nieuprawnione wartości", () => {
    expect(
      canManageRecruitmentBudget({
        role: "talent_community_manager",
        roles: ["talent_community_manager", "recruiter"],
      }),
    ).toBe(false);
  });

  it("odmawia, gdy nie ma zalogowanego użytkownika", () => {
    expect(canManageRecruitmentBudget(null)).toBe(false);
    expect(canManageRecruitmentBudget(undefined)).toBe(false);
  });
});
