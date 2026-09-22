import { describe, expect, it } from "vitest";

import { canEditJobContent, jobEditScope } from "@/lib/job-edit-access";

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
  it("pole z serwera wygrywa z lustrem ról", () => {
    expect(canEditJobContent({ can_edit: true }, { ...write, fallback: false })).toBe(true);
    expect(canEditJobContent({ can_edit: false }, { ...write, fallback: true })).toBe(false);
  });

  it("bez pola — dotychczasowe lustro (admin + DL)", () => {
    expect(canEditJobContent({}, { ...write, fallback: true })).toBe(true);
    expect(canEditJobContent(undefined, { ...write, fallback: false })).toBe(false);
  });

  it("bez zapisu Pipeline nigdy", () => {
    expect(
      canEditJobContent({ can_edit: true }, { canWritePipeline: false, fallback: true }),
    ).toBe(false);
  });
});
