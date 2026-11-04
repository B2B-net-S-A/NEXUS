import { describe, expect, it } from "vitest";

import { isClientTimeout } from "@/lib/http-timeouts";

describe("isClientTimeout", () => {
  it("rozpoznaje przekroczenie czasu po stronie przeglądarki", () => {
    expect(
      isClientTimeout(Object.assign(new Error("timeout of 30000ms exceeded"), { code: "ECONNABORTED" })),
    ).toBe(true);
    expect(isClientTimeout({ code: "ETIMEDOUT" })).toBe(true);
  });

  it("odpowiedź serwera i zwykły błąd to nie przekroczenie czasu", () => {
    expect(isClientTimeout({ response: { status: 500 } })).toBe(false);
    expect(isClientTimeout(new Error("Network Error"))).toBe(false);
    expect(isClientTimeout(null)).toBe(false);
    expect(isClientTimeout(undefined)).toBe(false);
  });
});
