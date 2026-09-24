import { describe, expect, it } from "vitest";

import {
  ORDER_PERIOD_REVERSED_MESSAGE,
  duplicateOrderError,
  orderPeriodError,
} from "@/lib/order-period";

describe("orderPeriodError", () => {
  it("koniec przed startem to błąd (ticket OIT/0569/2026/ITVM)", () => {
    expect(orderPeriodError("2027-01-01", "2026-12-31")).toBe(
      ORDER_PERIOD_REVERSED_MESSAGE,
    );
  });
  it("poprawny, jednodniowy albo niepełny okres przechodzi", () => {
    expect(orderPeriodError("2026-10-01", "2026-12-31")).toBeNull();
    expect(orderPeriodError("2026-10-01", "2026-10-01")).toBeNull();
    expect(orderPeriodError("2026-10-01", "")).toBeNull();
    expect(orderPeriodError(null, "2026-12-31")).toBeNull();
    expect(orderPeriodError("1.10.2026", "2026-12-31")).toBeNull();
  });
});

describe("duplicateOrderError", () => {
  const existing = [
    {
      id: 630,
      title: "OIT/0569/2026/ITVM",
      status: "active",
      start_date: "2026-10-01",
      end_date: "2026-12-31",
    },
    {
      id: 584,
      title: "OIT/0513/2026/ITVM",
      status: "active",
      start_date: "2026-09-07",
      end_date: "2026-09-30",
    },
  ];

  it("ten sam numer i nachodzący okres to duplikat", () => {
    expect(
      duplicateOrderError(" oit/0569/2026/itvm ", "2026-10-01", "2026-12-31", existing),
    ).toContain("OIT/0569/2026/ITVM");
  });
  it("inny numer, rozłączny okres, anulowane i edytowane zamówienie — nie", () => {
    expect(
      duplicateOrderError("OIT/0600/2026/ITVM", "2026-10-01", "2026-12-31", existing),
    ).toBeNull();
    expect(
      duplicateOrderError("OIT/0569/2026/ITVM", "2027-01-01", "2027-03-31", existing),
    ).toBeNull();
    expect(
      duplicateOrderError("OIT/0569/2026/ITVM", "2026-10-01", "2026-12-31", [
        { ...existing[0], status: "cancelled" },
      ]),
    ).toBeNull();
    expect(
      duplicateOrderError("OIT/0569/2026/ITVM", "2026-10-01", "2026-12-31", existing, 630),
    ).toBeNull();
  });
  it("pusty numer nie jest duplikatem", () => {
    expect(duplicateOrderError("", "2026-10-01", "2026-12-31", existing)).toBeNull();
  });
});
