import { describe, expect, it } from "vitest";

import {
  answeredShare,
  averageLabel,
  formatWhen,
  percentLabel,
  takeLabel,
} from "../portal-tabs-model";

describe("portal-tabs-model", () => {
  it("brak danych to kreska, nie zero", () => {
    expect(averageLabel(null)).toBe("—");
    expect(percentLabel(null)).toBe("—");
    expect(takeLabel(null)).toBe("—");
    expect(answeredShare(0, 0)).toBe("—");
  });

  it("formatuje liczby po polsku", () => {
    expect(averageLabel(4.25)).toBe("4,3 / 5");
    expect(percentLabel(68)).toBe("68%");
    expect(answeredShare(1, 2)).toBe("50%");
    expect(takeLabel(34)).toBe("34 min");
    expect(takeLabel(70)).toBe("1 h 10 min");
    expect(takeLabel(120)).toBe("2 h");
  });

  it("pokazuje czas w strefie firmy", () => {
    expect(formatWhen("2026-11-02T14:00:00Z")).toContain("15:00");
  });
});
