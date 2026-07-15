import { describe, expect, it } from "vitest";

import {
  criteriaSaveState,
  hourlyPlnSalaryFields,
  normalizeMindyHistory,
  uopInputHash,
} from "@/lib/ai-feature-safety";

describe("AI feature safety guards", () => {
  it("never maps a monthly salary into hourly rate fields", () => {
    expect(
      hourlyPlnSalaryFields({
        min: 20_000,
        max: 25_000,
        currency: "PLN",
        period: "month",
        employment_type: "uop",
      }),
    ).toBeNull();
    expect(
      hourlyPlnSalaryFields({
        min: 140,
        max: 170,
        currency: "PLN",
        period: "hour",
        employment_type: "b2b",
      }),
    ).toEqual({ min: "140", max: "170" });
  });

  it("blocks criteria save during loading/errors and confirms an empty set", () => {
    expect(
      criteriaSaveState({ loading: true, saving: false, error: null, count: 2, emptyConfirmed: false }),
    ).toBe("blocked");
    expect(
      criteriaSaveState({ loading: false, saving: false, error: "failed", count: 2, emptyConfirmed: false }),
    ).toBe("blocked");
    expect(
      criteriaSaveState({ loading: false, saving: false, error: null, count: 0, emptyConfirmed: false }),
    ).toBe("confirm-empty");
  });

  it("uses the backend-compatible UoP input hash", async () => {
    await expect(uopInputHash("  Zakres usług.  ", "PL")).resolves.toBe(
      "d4aa7ee82494edfa882375f0ceaf33e5352b08b12a936586049db3c02df1ed75",
    );
  });

  it("drops expired MINDY history and caps valid history at 20 messages", () => {
    expect(normalizeMindyHistory({ expiresAt: 99, messages: [] }, 100)).toEqual([]);
    const messages = Array.from({ length: 25 }, (_, index) => ({
      role: index % 2 ? ("assistant" as const) : ("user" as const),
      content: String(index),
    }));
    const normalized = normalizeMindyHistory({ expiresAt: 101, messages }, 100);
    expect(normalized).toHaveLength(20);
    expect(normalized[0].content).toBe("5");
  });
});
