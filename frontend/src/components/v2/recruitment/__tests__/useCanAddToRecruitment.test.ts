import { describe, expect, it } from "vitest";

import { CAPABILITY_ROLES, hasCapability } from "@/lib/capabilities";
import { ADD_TO_RECRUITMENT_CAPABILITY } from "@/components/v2/recruitment/useCanAddToRecruitment";
import type { UserRole } from "@/store/auth";

// Lustro `RecruiterPlus` z `backend/app/api/deps.py` — bramka
// `POST /api/jobs/{id}/proposals/bulk`. Jeżeli capability, na której wisi
// „Dodaj do rekrutacji”, zmieni definicję, ten test ma się zapalić.
const RECRUITER_PLUS: UserRole[] = [
  "admin",
  // Head of Recruitment = parytet z rekruterem (#1593, decyzja Artura 17.09).
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "finance",
  "sourcer",
];

describe("useCanAddToRecruitment — bramka jak proposals/bulk", () => {
  it("capability ma dokładnie role RecruiterPlus", () => {
    expect([...CAPABILITY_ROLES[ADD_TO_RECRUITMENT_CAPABILITY]].sort()).toEqual([...RECRUITER_PLUS].sort());
  });

  it("praktykant (0373) nie dodaje do rekrutacji — przekazuje przez „Przekaż rekruterowi”", () => {
    expect(hasCapability({ role: "trainee", roles: ["trainee"] }, ADD_TO_RECRUITMENT_CAPABILITY)).toBe(false);
  });

  it("wymaga zapisu sekcji Pipeline", () => {
    const recruiter = { role: "recruiter" as const, roles: ["recruiter" as const] };
    expect(hasCapability(recruiter, ADD_TO_RECRUITMENT_CAPABILITY)).toBe(true);
    expect(
      hasCapability(
        {
          ...recruiter,
          effective_section_access: { sourcing: "write", pipeline: "read", delivery: "none", insights: "read", finance: "none" },
        },
        ADD_TO_RECRUITMENT_CAPABILITY,
      ),
    ).toBe(false);
    // HoR ma parytet z rekruterem od #1593 — capability, nie wyjątek.
    expect(hasCapability({ role: "head_of_recruitment", roles: ["head_of_recruitment"] }, ADD_TO_RECRUITMENT_CAPABILITY)).toBe(true);
  });
});
