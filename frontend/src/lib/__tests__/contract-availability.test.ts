import { describe, expect, it } from "vitest";

import {
  contractAvailability,
  contractAvailabilityCountdown,
  contractAvailabilityOrigin,
  contractAvailabilityText,
  hidesAvailabilityStatus,
} from "@/lib/contract-availability";
import type { EmploymentMarker } from "@/lib/employment-marker";

const TODAY = "2026-10-15";

function marker(over: Partial<EmploymentMarker> = {}): EmploymentMarker {
  return {
    phase: "working",
    source: "contract",
    clients: [
      {
        client_id: 7,
        client_name: "Bank Przykładowy",
        phase: "working",
        order_end_date: "2026-11-30",
        delivery_lead_name: "Anna Nowak",
      },
    ],
    free_from: "2026-12-01",
    free_from_basis: "work_end",
    ...over,
  };
}

describe("contractAvailability", () => {
  it("ignores the screening date from before the contract", () => {
    const a = contractAvailability(marker(), "2026-09-01", TODAY);

    expect(a).toMatchObject({ kind: "date", date: "2026-12-01", basis: "contract" });
    expect(contractAvailabilityText(a!)).toBe("od 01.12.2026");
    expect(contractAvailabilityText(a!, "short")).toBe("od 01.12");
    const origin = contractAvailabilityOrigin(a!);
    expect(origin.tone).toBe("contract");
    expect(origin.text).toContain("dzień po końcu zamówienia w Bank Przykładowy (30.11.2026)");
    expect(origin.text).toContain("W profilu: od 01.09.2026");
  });

  it("takes a later date the candidate gave", () => {
    const a = contractAvailability(marker(), "2026-12-15", TODAY);

    expect(a).toMatchObject({ kind: "date", date: "2026-12-15", basis: "profile" });
    expect(contractAvailabilityOrigin(a!).tone).toBe("notes");
  });

  it("counts days in the ending phase", () => {
    const a = contractAvailability(
      marker({ phase: "ending", free_from: "2026-11-01" }),
      null,
      TODAY,
    );

    expect(contractAvailabilityCountdown(a!)).toBe("za 17 dni");
  });

  it("says when orders already ended and the contract goes on", () => {
    const a = contractAvailability(marker({ free_from: "2026-10-01" }), null, TODAY);

    expect(a).toMatchObject({ kind: "date", ordersEnded: true, workEnd: "2026-09-30" });
    expect(contractAvailabilityText(a!)).toBe("Zamówienia skończyły się 30.09.2026");
  });

  it("has no date without an order end", () => {
    const a = contractAvailability(
      marker({ free_from: null, free_from_basis: "no_end_date" }),
      "2026-09-01",
      TODAY,
    );

    expect(contractAvailabilityText(a!)).toBe("Bez daty końca zamówienia");
    expect(contractAvailabilityText(a!, "short")).toBe("bez daty końca");
    expect(contractAvailabilityOrigin(a!).text).toContain("termin zna Delivery");
  });

  it("names the start of a future contract", () => {
    const a = contractAvailability(
      marker({
        phase: "starting",
        free_from: null,
        free_from_basis: "starting",
        clients: [{ client_name: "Bank Przykładowy", phase: "starting", starts_on: "2026-11-03" }],
      }),
      null,
      TODAY,
    );

    expect(contractAvailabilityText(a!)).toBe("Zaczyna u nas 03.11.2026");
  });

  it("stays out of the way without a live contract", () => {
    expect(contractAvailability(null, "2026-09-01", TODAY)).toBeNull();
    expect(
      contractAvailability(
        marker({ source: "pipeline", free_from: null, free_from_basis: null }),
        "2026-09-01",
        TODAY,
      ),
    ).toBeNull();
    expect(hidesAvailabilityStatus(marker({ source: "conflict" }))).toBe(false);
    expect(hidesAvailabilityStatus(marker())).toBe(true);
    expect(hidesAvailabilityStatus(null)).toBe(false);
  });
});
