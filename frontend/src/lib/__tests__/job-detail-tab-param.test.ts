/**
 * `?tab=` z URL-a → `JobDetailTab` na `/jobs/{id}`.
 *
 * Regresja (przegląd 17.09.2026): `CreateJobModal` przekierowywał na
 * `?tab=champion-profile`, a strona rozumiała tylko `?tab=champion` — DL
 * zapisujący rekrutację lądował na pustym Pipeline. `createdJobUrl` (PR 2)
 * już generuje poprawny link, ale stare zakładki przeglądarki i
 * powiadomienia sprzed tej zmiany nadal noszą `champion-profile`.
 */
import { describe, expect, it } from "vitest";

import { resolveJobDetailTab } from "@/lib/job-detail-tab-param";

describe("resolveJobDetailTab", () => {
  it("tłumaczy `champion-profile` (stare linki) na `champion`", () => {
    expect(resolveJobDetailTab("champion-profile")).toBe("champion");
  });

  it("tłumaczy `similar` (powiadomienie „Podobny request”) na `ai-matching`", () => {
    expect(resolveJobDetailTab("similar")).toBe("ai-matching");
  });

  it.each(["chat", "champion", "screening", "cv", "interviews", "contract"])(
    "przepuszcza literał `JobDetailTab` %s tożsamościowo",
    (tab) => {
      expect(resolveJobDetailTab(tab)).toBe(tab);
    },
  );

  it("zwraca `null` dla braku parametru — strona zostaje na domyślnej zakładce", () => {
    expect(resolveJobDetailTab(null)).toBeNull();
    expect(resolveJobDetailTab(undefined)).toBeNull();
    expect(resolveJobDetailTab("")).toBeNull();
  });

  it("zwraca `null` dla nieznanego parametru zamiast zgadywać", () => {
    expect(resolveJobDetailTab("nonsense")).toBeNull();
  });
});
