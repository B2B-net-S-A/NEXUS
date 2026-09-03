import { describe, expect, it } from "vitest";

import {
  actionAccessForRoles,
  actionAccessForUser,
  hasActionAccess,
} from "@/lib/action-access";

const ACTION = "b2b_contract_generator" as const;

describe("action access", () => {
  it("preserves existing operators and keeps TCM view-only by default", () => {
    expect(actionAccessForRoles(["recruiter"], ACTION)).toBe("manage");
    expect(actionAccessForRoles(["delivery_lead"], ACTION)).toBe("manage");
    expect(
      actionAccessForRoles(["talent_community_manager"], ACTION),
    ).toBe("view");
  });

  it("uses the strongest role in a multi-role account", () => {
    expect(
      actionAccessForRoles(
        ["talent_community_manager", "recruiter"],
        ACTION,
      ),
    ).toBe("manage");
  });

  it("treats an authoritative per-user snapshot as a replacement", () => {
    const user = {
      role: "talent_community_manager" as const,
      roles: ["talent_community_manager" as const],
      effective_action_access: { b2b_contract_generator: "generate" as const },
    };

    expect(actionAccessForUser(user, ACTION)).toBe("generate");
    expect(hasActionAccess(user, ACTION, "view")).toBe(true);
    expect(hasActionAccess(user, ACTION, "generate")).toBe(true);
    expect(hasActionAccess(user, ACTION, "manage")).toBe(false);
  });

  it("fails closed when the authoritative snapshot omits the action", () => {
    expect(
      actionAccessForUser(
        {
          role: "recruiter",
          roles: ["recruiter"],
          effective_action_access: {},
        },
        ACTION,
      ),
    ).toBe("none");
  });
});
