import { describe, expect, it } from "vitest";

import { createdJobUrl } from "@/lib/job-create-landing";

describe("createdJobUrl", () => {
  it("ląduje na zakładce Championa", () => {
    expect(createdJobUrl(501, { hasDescription: false })).toBe(
      "/jobs/501?tab=champion",
    );
  });

  it("dokłada `&intake=1`, gdy rekrutacja ma opis do podania AI", () => {
    expect(createdJobUrl(501, { hasDescription: true })).toBe(
      "/jobs/501?tab=champion&intake=1",
    );
  });

  it("bez opisu NIE otwiera panelu intake — byłby pusty do wypełnienia ręcznie", () => {
    expect(createdJobUrl(9, { hasDescription: false })).not.toContain(
      "intake=1",
    );
  });
});
