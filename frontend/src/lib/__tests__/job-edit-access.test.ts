import { describe, expect, it } from "vitest";

import { hasCapability } from "@/lib/capabilities";
import {
  canEditJobContent,
  hasFullJobEditFallback,
  jobEditScope,
} from "@/lib/job-edit-access";
import type { UserRole } from "@/store/auth";

import { accessSnapshot } from "./fixtures/access-snapshot";

const write = { canWritePipeline: true };

describe("jobEditScope — kto edytuje rekrutację (22.09.2026)", () => {
  it("pełna edycja dla capability `job.update`", () => {
    expect(jobEditScope({ can_edit: true }, { ...write, canManageJob: true })).toBe("full");
    // Starszy backend bez pola — reguła sprzed zmiany.
    expect(jobEditScope({}, { ...write, canManageJob: true })).toBe("full");
  });

  it("rekruter prowadzący i współpracownicy: treść z `can_edit`", () => {
    expect(jobEditScope({ can_edit: true }, { ...write, canManageJob: false })).toBe(
      "content",
    );
  });

  it("brak pola nie poszerza uprawnień", () => {
    expect(jobEditScope({}, { ...write, canManageJob: false })).toBe("none");
    expect(jobEditScope(null, { ...write, canManageJob: false })).toBe("none");
  });

  it("jawne `can_edit: false` i brak zapisu Pipeline wygrywają zawsze", () => {
    expect(jobEditScope({ can_edit: false }, { ...write, canManageJob: true })).toBe(
      "none",
    );
    expect(
      jobEditScope({ can_edit: true }, { canWritePipeline: false, canManageJob: true }),
    ).toBe("none");
  });
});

describe("canEditJobContent — Profil Championa", () => {
  it("pole z serwera wygrywa z regułą zapasową", () => {
    expect(canEditJobContent({ can_edit: true }, { ...write, fallback: false })).toBe(true);
    expect(canEditJobContent({ can_edit: false }, { ...write, fallback: true })).toBe(false);
  });

  it("bez pola — reguła zapasowa wołającego", () => {
    expect(canEditJobContent({}, { ...write, fallback: true })).toBe(true);
    expect(canEditJobContent(undefined, { ...write, fallback: false })).toBe(false);
  });

  it("bez zapisu Pipeline nigdy", () => {
    expect(
      canEditJobContent({ can_edit: true }, { canWritePipeline: false, fallback: true }),
    ).toBe(false);
  });
});

describe("hasFullJobEditFallback — reguła zapasowa pełnej edycji", () => {
  const ALL_ROLES: UserRole[] = [
    "admin",
    "finance",
    "head_of_recruitment",
    "delivery_lead",
    "talent_community_manager",
    "recruiter",
    "user",
    "trainee",
  ];

  it("domyślnie admin i Delivery Lead (uprawnienie) — żadna rola z samego tytułu", () => {
    expect(ALL_ROLES.filter((role) => hasFullJobEditFallback({ role })).sort()).toEqual(
      ["admin", "delivery_lead"].sort(),
    );
    expect(hasFullJobEditFallback(null)).toBe(false);
  });

  it("idzie za uprawnieniem do rekrutacji; rekruter bez uprawnienia jej nie ma", () => {
    expect(
      hasFullJobEditFallback(accessSnapshot("recruiter", { grant: ["recruitment_manage"] })),
    ).toBe(true);
    expect(
      hasFullJobEditFallback(
        accessSnapshot("delivery_lead", { revoke: ["recruitment_manage"] }),
      ),
    ).toBe(false);
    // Pełna redakcja z tytułu roli TAC zniknęła 02.10.2026 razem z rolą.
    expect(hasFullJobEditFallback(accessSnapshot("recruiter"))).toBe(false);
  });

  it("to tytuł do `job.update` bez sufitu sekcji — sufit dokłada wołający", () => {
    const readOnlyPipeline = accessSnapshot("delivery_lead", {
      sectionCaps: { pipeline: "read" },
    });
    expect(hasFullJobEditFallback(readOnlyPipeline)).toBe(true);
    expect(hasCapability(readOnlyPipeline, "job.update")).toBe(false);
    expect(
      canEditJobContent(
        {},
        { canWritePipeline: false, fallback: hasFullJobEditFallback(readOnlyPipeline) },
      ),
    ).toBe(false);
  });
});
