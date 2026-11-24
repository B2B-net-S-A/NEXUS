import { afterEach, describe, expect, it, vi } from "vitest";

import {
  availabilityContractNote,
  contractAvailability,
  contractAvailabilityOrigin,
  contractAvailabilityText,
  contractDateText,
  hidesAvailabilityStatus,
  localIsoDay,
  type ContractAvailability,
} from "@/lib/contract-availability";
import type { EmploymentMarker } from "@/lib/employment-marker";

function marker(overrides: Partial<EmploymentMarker> = {}): EmploymentMarker {
  return {
    phase: "working",
    source: "contract",
    clients: [{ client_id: 5, client_name: "Firma Testowa", phase: "working" }],
    free_from: "2027-01-01",
    free_from_basis: "work_end",
    ...overrides,
  };
}

afterEach(() => vi.useRealTimers());

describe("localIsoDay", () => {
  it("bez argumentu bierze dziś (sylwester w Warszawie)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 11, 31, 23, 59));
    expect(localIsoDay()).toBe("2026-12-31");
  });
});

describe("contractAvailability — brzegi", () => {
  it("brak znacznika, inne źródło albo brak podstawy: null", () => {
    expect(contractAvailability(null, null)).toBeNull();
    expect(contractAvailability(undefined, null)).toBeNull();
    expect(contractAvailability(marker({ free_from_basis: null }), null)).toBeNull();
    expect(
      contractAvailability({ ...marker(), source: "profile" as "contract" }, null),
    ).toBeNull();
    expect(hidesAvailabilityStatus(null)).toBe(false);
    expect(hidesAvailabilityStatus(marker())).toBe(true);
  });

  it("klient bez nazwy: „Klient #id”; bez id i nazwy pomijany; nikt — null", () => {
    expect(
      contractAvailability(
        marker({
          clients: [
            { client_id: 7, client_name: "  ", phase: "working" },
            { client_id: null, client_name: null, phase: "working" },
          ],
        }),
        null,
        "2026-11-24",
      )?.clientName,
    ).toBe("Klient #7");
    expect(
      contractAvailability(
        marker({ clients: [{ client_id: null, client_name: "", phase: "working" }] }),
        null,
        "2026-11-24",
      )?.clientName,
    ).toBeNull();
  });

  it("start bez dat: data null; kilka dat — najwcześniejsza", () => {
    expect(
      contractAvailability(
        marker({ free_from_basis: "starting", clients: [{ client_id: 1, phase: "starting" }] }),
        null,
      ),
    ).toMatchObject({ kind: "starting", date: null });
    expect(
      contractAvailability(
        marker({
          free_from_basis: "starting",
          clients: [
            { client_id: 1, phase: "starting", starts_on: "2027-02-01" },
            { client_id: 2, phase: "starting", starts_on: "2027-01-04T00:00:00" },
          ],
        }),
        null,
      ),
    ).toMatchObject({ kind: "starting", date: "2027-01-04" });
  });

  it("podstawa „work_end” bez daty: jak bez daty końca", () => {
    expect(contractAvailability(marker({ free_from: null }), null)?.kind).toBe("no_end_date");
  });

  it("faza kończąca: dni do terminu przez granicę roku", () => {
    const a = contractAvailability(marker({ phase: "ending" }), null, "2026-12-25");
    expect(a).toMatchObject({
      kind: "date",
      date: "2027-01-01",
      workEnd: "2026-12-31",
      basis: "contract",
      ordersEnded: false,
      daysLeft: 7,
    });
  });

  it("faza kończąca, data z profilu późniejsza: liczy dni do daty z profilu", () => {
    const a = contractAvailability(marker({ phase: "ending" }), "2027-01-10", "2026-12-31");
    expect(a).toMatchObject({ basis: "profile", date: "2027-01-10", daysLeft: 10 });
  });

  it("zamówienia skończyły się dziś: ordersEnded, bez liczenia dni", () => {
    const a = contractAvailability(marker({ phase: "ending" }), null, "2027-01-01");
    expect(a).toMatchObject({ ordersEnded: true, daysLeft: null });
  });

  it("data z profilu wcześniejsza niż koniec pracy się nie liczy", () => {
    expect(contractAvailability(marker(), "2026-09-01", "2026-11-24")).toMatchObject({
      basis: "contract",
      date: "2027-01-01",
      profileDate: "2026-09-01",
    });
  });
});

const base = { clientName: null, deliveryLead: null, profileDate: null, noCurrentOrder: false };
const starting = (date: string | null): ContractAvailability => ({ ...base, kind: "starting", date });
const dated = (over: Partial<Extract<ContractAvailability, { kind: "date" }>> = {}): ContractAvailability => ({
  ...base,
  kind: "date",
  date: "2027-01-01",
  basis: "contract",
  workEnd: "2026-12-31",
  ordersEnded: false,
  daysLeft: null,
  ...over,
});

describe("contractDateText — oba style", () => {
  it("start bez daty i z datą", () => {
    expect(contractDateText(starting(null))).toBe("Zaczyna u nas");
    expect(contractDateText(starting(null), "short")).toBe("zaczyna u nas");
    expect(contractDateText(starting("2027-01-04"))).toBe("Zaczyna u nas 04.01.2027");
    expect(contractDateText(starting("2027-01-04"), "short")).toBe("zaczyna 04.01");
  });
  it("bez daty końca", () => {
    expect(contractDateText({ ...base, kind: "no_end_date" })).toBe("Bez daty końca zamówienia");
    expect(contractDateText({ ...base, kind: "no_end_date" }, "short")).toBe("bez daty końca");
  });
  it("zamówienia skończone i zwykły termin", () => {
    expect(contractDateText(dated({ ordersEnded: true }))).toBe("Zamówienia skończyły się 31.12.2026");
    expect(contractDateText(dated({ ordersEnded: true }), "short")).toBe("zam. do 31.12");
    expect(contractDateText(dated(), "short")).toBe("od 01.01");
  });
});

describe("contractAvailabilityText — krótki styl", () => {
  it("start, bez zamówienia, aktywne", () => {
    expect(contractAvailabilityText(starting(null), "short")).toBe("zaczyna u nas");
    expect(contractAvailabilityText({ ...base, kind: "no_end_date", noCurrentOrder: true }, "short")).toBe(
      "bez zamówienia",
    );
    expect(contractAvailabilityText(dated({ ordersEnded: true }))).toBe("Bez aktywnego zamówienia");
    expect(contractAvailabilityText(dated(), "short")).toBe("aktywne zamówienie");
  });
});

describe("contractAvailabilityOrigin", () => {
  it("start z datą i bez, z klientem i bez", () => {
    expect(contractAvailabilityOrigin({ ...starting("2027-01-04"), clientName: "Firma Testowa" }).text).toBe(
      "Z kontraktu: umowa w Firma Testowa startuje 04.01.2027.",
    );
    expect(contractAvailabilityOrigin(starting(null)).text).toBe(
      "Z kontraktu: umowa jeszcze się nie zaczęła.",
    );
  });
  it("bez daty końca, ale bez trwającego zamówienia", () => {
    expect(contractAvailabilityOrigin({ ...base, kind: "no_end_date", noCurrentOrder: true }).text).toMatch(
      /bez trwającego zamówienia — ustal z Delivery/,
    );
  });
  it("zamówienia skończone, umowa trwa", () => {
    expect(contractAvailabilityOrigin(dated({ ordersEnded: true, clientName: "Firma Testowa" })).text).toBe(
      "Z kontraktu: zamówienia w Firma Testowa skończyły się 31.12.2026, a umowa trwa — ustal z Delivery, czy osoba jest wolna.",
    );
  });
  it("bez zamówienia, termin w przyszłości: dzień po końcu i data z profilu", () => {
    const origin = contractAvailabilityOrigin(dated({ noCurrentOrder: true, profileDate: "2026-09-01" }));
    expect(origin.text).toBe(
      "Z kontraktu: dzień po końcu zamówienia (31.12.2026). W profilu: od 01.09.2026 — wcześniej niż koniec pracy u nas, nie liczy się.",
    );
    expect(contractAvailabilityOrigin(dated({ noCurrentOrder: true })).text).toBe(
      "Z kontraktu: dzień po końcu zamówienia (31.12.2026).",
    );
  });
});

describe("availabilityContractNote", () => {
  it("bez umowy: null", () => {
    expect(availabilityContractNote(null)).toBeNull();
  });
  it("start bez klienta i bez DL", () => {
    const note = availabilityContractNote(
      marker({ free_from_basis: "starting", clients: [{ client_id: null, phase: "starting" }] }),
    );
    expect(note).toMatch(/^Zaczyna u nas\. /);
    expect(note).toMatch(/Termin dostępności ustala Delivery Lead\.$/);
  });
  it("bez daty końca z klientem i DL", () => {
    const note = availabilityContractNote(
      marker({
        free_from_basis: "no_end_date",
        clients: [
          { client_id: 1, client_name: "Firma Testowa", phase: "working", delivery_lead_name: "Anna Przykładowa" },
        ],
      }),
    );
    expect(note).toMatch(/^Pracuje u nas bez daty końca zamówienia \(Firma Testowa\)\./);
    expect(note).toContain("Termin ustala Delivery Lead (Anna Przykładowa)");
  });
});
