import { describe, expect, it } from "vitest";

import {
  ALL_USER_ROLES,
  ROLE_SECTION_ACCESS,
  hasSectionAccess,
  rolesWithSectionAccess,
  sectionAccessForUser,
} from "@/lib/section-access";

describe("central section access matrix", () => {
  it("has an explicit policy for every role", () => {
    expect(Object.keys(ROLE_SECTION_ACCESS).sort()).toEqual(
      [...ALL_USER_ROLES].sort(),
    );
  });

  it.each(["sourcer", "recruiter", "tac", "head_of_recruitment"] as const)(
    "%s has no Delivery or Finance section",
    (role) => {
      expect(sectionAccessForUser({ role }, "delivery")).toBe("none");
      expect(sectionAccessForUser({ role }, "finance")).toBe("none");
      expect(hasSectionAccess({ role }, "sourcing")).toBe(true);
      expect(hasSectionAccess({ role }, "pipeline")).toBe(true);
      expect(hasSectionAccess({ role }, "insights")).toBe(true);
    },
  );

  it("gives TCM all business sections except Finance and read-only Delivery", () => {
    const user = { role: "talent_community_manager" as const };
    expect(sectionAccessForUser(user, "sourcing")).toBe("write");
    expect(sectionAccessForUser(user, "pipeline")).toBe("write");
    expect(sectionAccessForUser(user, "delivery")).toBe("read");
    expect(sectionAccessForUser(user, "insights")).toBe("read");
    expect(sectionAccessForUser(user, "finance")).toBe("none");
    expect(hasSectionAccess(user, "delivery", "write")).toBe(false);
  });

  it("keeps Delivery Lead in Delivery but outside the global Finance module", () => {
    const user = { role: "delivery_lead" as const };
    expect(sectionAccessForUser(user, "delivery")).toBe("write");
    expect(sectionAccessForUser(user, "finance")).toBe("none");
  });

  it("resolves multi-role access as a union", () => {
    const hybrid = {
      role: "recruiter" as const,
      roles: ["recruiter", "talent_community_manager"] as const,
    };
    expect(sectionAccessForUser(hybrid, "delivery")).toBe("read");
    expect(sectionAccessForUser(hybrid, "finance")).toBe("none");
  });

  it("derives route allowlists from the same matrix", () => {
    expect(rolesWithSectionAccess("delivery").sort()).toEqual(
      ["admin", "delivery_lead", "finance", "talent_community_manager"].sort(),
    );
    expect(rolesWithSectionAccess("finance").sort()).toEqual(
      ["admin", "finance"].sort(),
    );
  });

  it("preserves the legacy viewer's existing Pipeline and Insights reads", () => {
    const viewer = { role: "user" as const };
    expect(sectionAccessForUser(viewer, "pipeline")).toBe("read");
    expect(sectionAccessForUser(viewer, "insights")).toBe("read");
    expect(sectionAccessForUser(viewer, "delivery")).toBe("none");
  });
});
