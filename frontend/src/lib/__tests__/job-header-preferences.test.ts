import { describe, expect, it } from "vitest";

import {
  JOB_HEADER_COLLAPSED_DEFAULT,
  jobHeaderCollapsedKey,
} from "@/lib/job-header-preferences";

describe("job-header-preferences — „Zwiń” nagłówka rekrutacji (K-D5)", () => {
  it("domyślnie rozwinięty", () => {
    expect(JOB_HEADER_COLLAPSED_DEFAULT).toBe(false);
  });

  it("klucz per osoba, nie wspólny dla przeglądarki", () => {
    expect(jobHeaderCollapsedKey(7)).toBe("nexus:job-header-collapsed:7");
    expect(jobHeaderCollapsedKey(8)).not.toBe(jobHeaderCollapsedKey(7));
  });

  it("nie wraca do dawnego klucza z domyślnie zwiniętym nagłówkiem (#1899)", () => {
    expect(jobHeaderCollapsedKey(7)).not.toContain("jobHeaderCollapsed:v3");
  });
});
