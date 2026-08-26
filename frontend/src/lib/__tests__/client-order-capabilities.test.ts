import { describe, expect, it } from "vitest";

import { hasMixedOrderTypes } from "@/lib/client-order-capabilities";

describe("hasMixedOrderTypes", () => {
  it("włącza ten sam wariant dla Lotte Wedel", () => {
    expect(hasMixedOrderTypes({ lotte_wedel_order_types_enabled: true })).toBe(
      true,
    );
  });

  it("zachowuje wariant Cyfrowego Polsatu", () => {
    expect(
      hasMixedOrderTypes({ cyfrowy_polsat_order_types_enabled: true }),
    ).toBe(true);
  });

  it("nie rozszerza wariantu na pozostałych klientów", () => {
    expect(hasMixedOrderTypes({})).toBe(false);
    expect(hasMixedOrderTypes(null)).toBe(false);
  });
});
