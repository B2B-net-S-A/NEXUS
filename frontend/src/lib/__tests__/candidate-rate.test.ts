import { describe, expect, it } from "vitest";

import {
  hourlyText,
  rateFromContextLine,
  rateFromText,
  rateReasonLabel,
  rateSecondLine,
  rateSourceLabel,
  thisJobRateText,
  toAmount,
} from "@/lib/candidate-rate";

describe("candidate-rate", () => {
  it("formats hourly amounts the Polish way", () => {
    expect(hourlyText("80.00")).toBe("80 zł/h");
    expect(hourlyText(125.19)).toBe("125,19 zł/h");
    expect(hourlyText(null)).toBeNull();
    expect(toAmount("0")).toBeNull();
  });

  it("marks a stale rate with its year", () => {
    expect(rateFromText({ rate_from_hourly: 80 })).toBe("od 80 zł/h");
    expect(
      rateFromText({
        rate_from_hourly: 140,
        rate_from_stale: true,
        rate_from_at: "2023-06-15T10:00:00Z",
      }),
    ).toBe("od 140 zł/h · z 2023");
    expect(rateFromText({ rate_from_hourly: null })).toBeNull();
  });

  it("shows the latest rate only when it differs from the minimum", () => {
    expect(
      rateSecondLine({
        rate_from_hourly: 80,
        rate_latest_hourly: 140,
        rate_latest_at: "2026-06-16T10:00:00Z",
        rate_observation_count: 7,
      }),
    ).toBe("ostatnio 140 zł/h (06.2026) · 7 stawek");
    expect(
      rateSecondLine({ rate_from_hourly: 80, rate_latest_hourly: "80.00" }),
    ).toBeNull();
  });

  it("describes the rate for this recruitment", () => {
    expect(thisJobRateText("135.00")).toBe("W tej rekrutacji: 135 zł/h");
    expect(thisJobRateText(null)).toBe("W tej rekrutacji: nie pytano");
  });

  it("builds the context line with role and month", () => {
    expect(
      rateFromContextLine({
        amount: "80",
        at: "2025-08-29T10:00:00Z",
        job_title: "DevOps / Admin",
      }),
    ).toBe("Stawka od 80 zł/h · DevOps / Admin, 08.2025");
    expect(rateFromContextLine(null)).toBeNull();
  });

  it("names sources and reasons", () => {
    expect(rateSourceLabel("card")).toBe("Screening (z notatki)");
    expect(rateSourceLabel("profile_something_new")).toBe("Profil");
    // Wpis DL-a „X/Y” — źródło ma polską nazwę, nie surowe „note”.
    expect(rateSourceLabel("note")).toBe("Notatka Delivery Leada");
    expect(rateReasonLabel("excluded", "Anna Nowak")).toBe(
      "wyłączona przez: Anna Nowak",
    );
    expect(rateReasonLabel("superseded")).toBe("niższa niż późniejsze minimum");
  });
});

describe("list rate cell", () => {
  it("keeps the second line short and the full text in the tooltip", async () => {
    const { rateCellSecondLine, rateCellText } = await import(
      "@/components/v2/candidates/candidate-row-format"
    );
    const row = {
      rate_from_hourly: 125,
      rate_latest_hourly: 160,
      rate_latest_at: "2026-09-20T10:00:00Z",
      rate_observation_count: 3,
    };
    expect(rateCellText(row)).toBe("od 125 zł/h");
    expect(rateCellSecondLine(row)).toEqual({
      text: "ostatnio 160 zł/h",
      title: "ostatnio 160 zł/h (09.2026) · 3 stawki",
    });
    expect(rateCellText({ expected_rate_hourly: 160 })).toBe("160 zł/h");
    // Stawka w EUR nie wchodzi do „Stawki od”, ale lista ją pokazuje.
    expect(
      rateCellText({
        rate_from_hourly: null,
        expected_rate_hourly: 40,
        expected_rate_currency: "EUR",
      }),
    ).toBe("40 EUR/h");
  });
});
