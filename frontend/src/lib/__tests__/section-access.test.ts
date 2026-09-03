import { describe, expect, it } from "vitest";

import {
  ALL_USER_ROLES,
  ROLE_SECTION_ACCESS,
  canMutateSection,
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

  it("prefers the backend effective map over the static legacy matrix", () => {
    const recruiterWithException = {
      role: "recruiter" as const,
      effective_section_access: {
        sourcing: "read" as const,
        pipeline: "write" as const,
        delivery: "write" as const,
        insights: "none" as const,
        finance: "none" as const,
        system_admin: "none" as const,
      },
    };

    expect(sectionAccessForUser(recruiterWithException, "delivery")).toBe(
      "write",
    );
    expect(sectionAccessForUser(recruiterWithException, "insights")).toBe(
      "none",
    );
  });

  it("fails closed for a missing section in an effective backend map", () => {
    expect(
      sectionAccessForUser(
        {
          role: "admin",
          effective_section_access: { sourcing: "write" },
        },
        "system_admin",
      ),
    ).toBe("none");
  });

  it("allows UI mutations only with write access outside impersonation", () => {
    const writer = {
      role: "recruiter" as const,
      effective_section_access: { sourcing: "write" as const },
    };
    const reader = {
      role: "recruiter" as const,
      effective_section_access: { sourcing: "read" as const },
    };

    expect(canMutateSection(writer, "sourcing")).toBe(true);
    expect(canMutateSection(reader, "sourcing")).toBe(false);
    expect(canMutateSection(writer, "sourcing", true)).toBe(false);
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
