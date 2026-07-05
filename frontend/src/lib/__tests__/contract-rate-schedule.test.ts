import { describe, it, expect } from "vitest";
import {
  OPEN_ENDED_LABEL,
  isoMinusOneDay,
  formatEffectiveTo,
  type RateScheduleRow,
} from "@/lib/contract-rate-schedule";

const row = (rate: string, effectiveFrom: string): RateScheduleRow => ({
  rate,
  effectiveFrom,
});

describe("isoMinusOneDay", () => {
  it("subtracts one day across a month boundary", () => {
    expect(isoMinusOneDay("2026-07-01")).toBe("2026-06-30");
  });

  it("subtracts one day across a year boundary", () => {
    expect(isoMinusOneDay("2026-01-01")).toBe("2025-12-31");
  });

  it("handles non-leap February", () => {
    expect(isoMinusOneDay("2026-03-01")).toBe("2026-02-28");
  });

  it("handles leap February", () => {
    expect(isoMinusOneDay("2024-03-01")).toBe("2024-02-29");
  });

  it("returns empty string for invalid input", () => {
    expect(isoMinusOneDay("")).toBe("");
    expect(isoMinusOneDay("nonsense")).toBe("");
    expect(isoMinusOneDay("2026-13-01")).toBe("");
  });
});

describe("formatEffectiveTo", () => {
  it("a single stage is open-ended", () => {
    const rows = [row("150", "2026-01-01")];
    expect(formatEffectiveTo(rows, "2026-01-01", 0)).toBe(OPEN_ENDED_LABEL);
  });

  it("sequential stages derive 'do' from the next stage start (matches ticket preview)", () => {
    const rows = [
      row("150", "2026-01-01"),
      row("165", "2026-07-01"),
      row("180", "2027-01-01"),
    ];
    expect(formatEffectiveTo(rows, "2026-01-01", 0)).toBe("2026-06-30");
    expect(formatEffectiveTo(rows, "2026-01-01", 1)).toBe("2026-12-31");
    expect(formatEffectiveTo(rows, "2026-01-01", 2)).toBe(OPEN_ENDED_LABEL);
  });

  it("first stage with empty 'od' falls back to the contract start date", () => {
    const rows = [row("150", ""), row("165", "2026-07-01")];
    expect(formatEffectiveTo(rows, "2026-01-01", 0)).toBe("2026-06-30");
    expect(formatEffectiveTo(rows, "2026-01-01", 1)).toBe(OPEN_ENDED_LABEL);
  });

  it("is robust to out-of-order rows (picks the chronologically nearest later start)", () => {
    const rows = [row("165", "2026-07-01"), row("150", "2026-01-01")];
    expect(formatEffectiveTo(rows, "2026-01-01", 0)).toBe(OPEN_ENDED_LABEL);
    expect(formatEffectiveTo(rows, "2026-01-01", 1)).toBe("2026-06-30");
  });

  it("ignores rows without a rate when computing the end date", () => {
    const rows = [row("150", "2026-01-01"), row("", "2026-07-01")];
    expect(formatEffectiveTo(rows, "2026-01-01", 0)).toBe(OPEN_ENDED_LABEL);
  });

  it("returns empty string for an unknown index", () => {
    expect(formatEffectiveTo([row("150", "2026-01-01")], "2026-01-01", 5)).toBe(
      "",
    );
  });
});
