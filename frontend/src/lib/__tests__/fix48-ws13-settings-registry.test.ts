import { describe, expect, it } from "vitest";

import { findSettingsItem } from "@/lib/settings-registry";

// Traffit wyłączony na stałe 14.10.2026 — kafelek nie obiecuje nocnego importu.
describe("settings-registry — kafelek „Import z Traffita”", () => {
  it("mówi, że import jest wyłączony, a karta to historia", () => {
    const traffit = findSettingsItem("traffit")!;
    expect(traffit.description).toBe("Wyłączony 14.10.2026 — historia ostatnich importów.");
    expect(traffit.description).not.toMatch(/nocny import przeszedł/);
  });
});
