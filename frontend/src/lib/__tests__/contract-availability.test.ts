import { describe, expect, it } from "vitest";

import {
  availabilityContractNote,
  contractAvailability,
  contractAvailabilityOrigin,
  contractAvailabilityText,
  contractDateText,
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
    expect(contractDateText(a!)).toBe("od 01.12.2026");
    expect(contractDateText(a!, "short")).toBe("od 01.12");
  });

  it("recruiter screens say the order is active, with no date", () => {
    const a = contractAvailability(marker(), "2026-09-01", TODAY);

    expect(contractAvailabilityText(a!)).toBe("Aktywne zamówienie");
    expect(contractAvailabilityText(a!, "short")).toBe("aktywne zamówienie");
    const origin = contractAvailabilityOrigin(a!);
    expect(origin.tone).toBe("contract");
    expect(origin.text).toBe("Z kontraktu: aktywne zamówienie w Bank Przykładowy. Nie dzwoń z nowym projektem.");
  });

  it("a later date from the candidate does not reveal the order end", () => {
    const a = contractAvailability(marker(), "2026-12-15", TODAY);

    expect(a).toMatchObject({ kind: "date", date: "2026-12-15", basis: "profile" });
    expect(contractAvailabilityText(a!)).toBe("Aktywne zamówienie");
    expect(contractAvailabilityOrigin(a!).text).not.toContain("30.11");
  });

  it("says when orders already ended and the contract goes on", () => {
    const a = contractAvailability(marker({ free_from: "2026-10-01" }), null, TODAY);

    expect(a).toMatchObject({ kind: "date", ordersEnded: true, workEnd: "2026-09-30" });
    expect(contractDateText(a!)).toBe("Zamówienia skończyły się 30.09.2026");
    expect(contractAvailabilityText(a!)).toBe("Bez aktywnego zamówienia");
    expect(contractAvailabilityText(a!, "short")).toBe("bez zamówienia");
  });

  it("has no date without an order end", () => {
    const a = contractAvailability(
      marker({ free_from: null, free_from_basis: "no_end_date" }),
      "2026-09-01",
      TODAY,
    );

    expect(contractDateText(a!)).toBe("Bez daty końca zamówienia");
    expect(contractAvailabilityText(a!)).toBe("Aktywne zamówienie");
  });

  it("a contract with no order at all is not an active order", () => {
    const a = contractAvailability(
      marker({ free_from: null, free_from_basis: "no_end_date", no_current_order: true }),
      null,
      TODAY,
    );

    expect(contractAvailabilityText(a!)).toBe("Bez aktywnego zamówienia");
    expect(contractAvailabilityOrigin(a!).text).toContain("bez trwającego zamówienia");
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

    expect(contractDateText(a!)).toBe("Zaczyna u nas 03.11.2026");
    expect(contractAvailabilityText(a!)).toBe("Zaczyna u nas");
  });

  it("stays out of the way without a live contract", () => {
    expect(contractAvailability(null, "2026-09-01", TODAY)).toBeNull();
    expect(
      contractAvailability(
        marker({ free_from: null, free_from_basis: null }),
        "2026-09-01",
        TODAY,
      ),
    ).toBeNull();
    expect(hidesAvailabilityStatus(marker())).toBe(true);
    expect(hidesAvailabilityStatus(null)).toBe(false);
  });
});

describe("availabilityContractNote (D6, S4)", () => {
  const hidden = "status „Czy szuka pracy” jest ukryty";

  it("says the status is hidden until the end of the engagement", () => {
    const note = availabilityContractNote(marker());

    expect(note).toContain("Pracuje u nas do 30.11.2026 (Bank Przykładowy)");
    expect(note).toContain(hidden);
    expect(note).toContain("Delivery Lead (Anna Nowak)");
  });

  it("says it in every phase of a live contract", () => {
    const noEnd = availabilityContractNote(
      marker({ free_from: null, free_from_basis: "no_end_date" }),
    );
    const starting = availabilityContractNote(
      marker({
        phase: "starting",
        free_from: null,
        free_from_basis: "starting",
        clients: [
          {
            client_id: 7,
            client_name: "Bank Przykładowy",
            phase: "starting",
            starts_on: "2026-11-03",
            delivery_lead_name: "Anna Nowak",
          },
        ],
      }),
    );

    expect(noEnd).toContain(hidden);
    expect(starting).toContain("Zaczyna u nas 03.11.2026");
    expect(starting).toContain(hidden);
  });

  it("is absent without a contract", () => {
    expect(availabilityContractNote(null)).toBeNull();
    expect(availabilityContractNote(marker({ free_from: null, free_from_basis: null }))).toBeNull();
  });
});
