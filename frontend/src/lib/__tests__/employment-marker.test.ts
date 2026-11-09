import { describe, expect, it } from "vitest";
import {
  employedCountLabel,
  markerCallHint,
  markerDetails,
  markerLabel,
  markerTone,
  returnsToMarketLabel,
  worksForUsNow,
  type EmploymentMarker,
  type EmploymentMarkerClient,
} from "@/lib/employment-marker";

function client(overrides: Partial<EmploymentMarkerClient> = {}): EmploymentMarkerClient {
  return {
    client_id: 100,
    client_name: "Bank Przykładowy",
    contract_id: 10,
    phase: "working",
    order_end_date: null,
    starts_on: null,
    delivery_lead_name: null,
    ...overrides,
  };
}

function marker(overrides: Partial<EmploymentMarker> = {}): EmploymentMarker {
  return { phase: "working", source: "contract", elsewhere: null, clients: [client()], ...overrides };
}

describe("markerLabel (decyzja 09.11.2026: bez daty, polecenie dla rekrutera)", () => {
  it("trwające zamówienie: „nie dzwoń”, bez daty i bez klienta", () => {
    expect(markerLabel(marker({ clients: [client({ order_end_date: "2026-12-31" })] }))).toBe(
      "Aktywne zamówienie · nie dzwoń",
    );
    expect(markerLabel(marker())).toBe("Aktywne zamówienie · nie dzwoń");
  });

  it("koniec zamówienia blisko i klient tej rekrutacji mówią to samo", () => {
    const ending = marker({
      phase: "ending",
      clients: [client({ phase: "ending", order_end_date: "2026-11-30" })],
    });
    expect(markerLabel(ending)).toBe("Aktywne zamówienie · nie dzwoń");
    expect(markerLabel(marker({ elsewhere: false }))).toBe("Aktywne zamówienie · nie dzwoń");
  });

  it("umowa z przyszłym startem też „nie dzwoń”", () => {
    expect(
      markerLabel(marker({ phase: "starting", clients: [client({ phase: "starting", starts_on: "2026-11-01" })] })),
    ).toBe("Zaczyna u nas · nie dzwoń");
  });

  it("karta Tablicy: samo polecenie", () => {
    expect(markerLabel(marker(), { short: true })).toBe("Nie dzwoń");
    expect(markerLabel(marker({ phase: "starting" }), { short: true })).toBe("Nie dzwoń");
  });

  it("ławka: bez zakazu", () => {
    expect(markerLabel(marker({ no_current_order: true }))).toBe("Bez aktywnego zamówienia");
    expect(markerLabel(marker({ no_current_order: true }), { short: true })).toBe("Bez zamówienia");
  });

  it("przekazana do front office: „Wraca na rynek”, bez zakazu", () => {
    const back = marker({ returns_to_market: true, returns_to_market_on: "2026-11-30" });
    expect(markerLabel(back)).toBe("Wraca na rynek 30.11");
    expect(markerLabel(back, { short: true })).toBe("Wraca na rynek 30.11");
  });
});

describe("markerTone", () => {
  it("zakaz na czerwono, ławka neutralnie, powrót na rynek informacyjnie", () => {
    expect(markerTone(marker())).toBe("danger");
    expect(markerTone(marker({ phase: "ending" }))).toBe("danger");
    expect(markerTone(marker({ phase: "starting" }))).toBe("danger");
    expect(markerTone(marker({ elsewhere: false }))).toBe("danger");
    expect(markerTone(marker({ no_current_order: true }))).toBe("neutral");
    expect(markerTone(marker({ returns_to_market: true }))).toBe("info");
  });
});

describe("markerCallHint", () => {
  it("mówi, kto zajmuje się końcem zamówienia, i nie podaje daty", () => {
    const hint = markerCallHint(marker({ clients: [client({ order_end_date: "2026-12-31" })] }));
    expect(hint).toContain("Nie dzwoń");
    expect(hint).toContain("osobny dział");
    expect(hint).not.toMatch(/\d{2}\.\d{2}/);
  });

  it("ławka i przyszły start mają własne zdanie", () => {
    expect(markerCallHint(marker({ no_current_order: true }))).toContain("żadnego trwającego zamówienia");
    expect(markerCallHint(marker({ phase: "starting" }))).toContain("jeszcze się nie zaczęła");
  });
});

describe("markerDetails", () => {
  const two = marker({
    clients: [
      client({ order_end_date: "2026-12-31", delivery_lead_name: "Karol Wzorcowy" }),
      client({ client_id: 101, client_name: "Nowy", contract_id: 11, phase: "starting", starts_on: "2026-11-01" }),
    ],
  });

  it("rekruter: klient i Delivery Lead, bez dat", () => {
    expect(markerDetails(two)).toEqual([
      {
        key: "100:10",
        title: "Aktywne zamówienie · nie dzwoń · Bank Przykładowy",
        detail: "Delivery Lead: Karol Wzorcowy",
        contractId: 10,
      },
      { key: "101:11", title: "Zaczyna u nas · nie dzwoń · Nowy", detail: "", contractId: 11 },
    ]);
  });

  it("dostęp do Delivery: daty zostają", () => {
    expect(markerDetails(two, { showDates: true }).map((line) => line.detail)).toEqual([
      "Zamówienie do 31.12.2026 · Delivery Lead: Karol Wzorcowy",
      "Start 01.11.2026",
    ]);
  });

  it("umowa bez końca zamówień: „Zamówienie bez daty końca”, nic o ręcznym oznaczeniu ani etapie", () => {
    // 17.10.2026: znacznik daje tylko umowa w Kontraktach.
    const [line] = markerDetails(marker({ clients: [client({ delivery_lead_name: "Karol Wzorcowy" })] }), {
      showDates: true,
    });
    expect(line.detail).toBe("Zamówienie bez daty końca · Delivery Lead: Karol Wzorcowy");
    expect(line.detail).not.toMatch(/ręcznie|Zatrudniony/);
  });

  it("ławka: bez zakazu w nagłówku", () => {
    expect(markerDetails(marker({ no_current_order: true }))[0].title).toBe(
      "Bez aktywnego zamówienia · Bank Przykładowy",
    );
  });
});

describe("worksForUsNow", () => {
  it("umowa od przyszłego miesiąca to jeszcze nie praca", () => {
    expect(worksForUsNow(marker())).toBe(true);
    expect(worksForUsNow(marker({ phase: "ending" }))).toBe(true);
    expect(worksForUsNow(marker({ phase: "starting" }))).toBe(false);
    expect(worksForUsNow(null)).toBe(false);
  });
});

describe("employedCountLabel", () => {
  it.each([
    [1, 4, "1 z 4 osób pracuje u nas"],
    [2, 4, "2 z 4 osób pracują u nas"],
    [5, 9, "5 z 9 osób pracuje u nas"],
    [22, 30, "22 z 30 osób pracują u nas"],
  ])("%i z %i", (employed, total, expected) => {
    expect(employedCountLabel(employed, total)).toBe(expected);
  });
});

describe("returnsToMarketLabel (22.10.2026)", () => {
  it("„Wraca na rynek DD.MM” tylko przy przekazaniu z opieki", () => {
    expect(returnsToMarketLabel(marker())).toBeNull();
    expect(returnsToMarketLabel(null)).toBeNull();
    expect(
      returnsToMarketLabel(marker({ returns_to_market: true, returns_to_market_on: "2026-11-30" })),
    ).toBe("Wraca na rynek 30.11");
    expect(returnsToMarketLabel(marker({ returns_to_market: true, returns_to_market_on: null }))).toBe(
      "Wraca na rynek",
    );
  });
});
