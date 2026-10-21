import { describe, expect, it } from "vitest";
import {
  employedCountLabel,
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

describe("markerLabel", () => {
  it("pracuje: klient i koniec zamówienia", () => {
    expect(markerLabel(marker({ clients: [client({ order_end_date: "2026-12-31" })] }))).toBe(
      "Pracuje u nas · Bank Przykładowy · do 31.12.2026",
    );
  });

  it("pracuje bez daty końca: sam klient", () => {
    expect(markerLabel(marker())).toBe("Pracuje u nas · Bank Przykładowy");
  });

  it("kończy: data stoi zaraz po nagłówku", () => {
    expect(
      markerLabel(
        marker({
          phase: "ending",
          clients: [client({ phase: "ending", order_end_date: "2026-11-30", client_name: "Telekom Przykładowy" })],
        }),
      ),
    ).toBe("Kończy u nas 30.11.2026 · Telekom Przykładowy");
  });

  it("zaczyna: data startu", () => {
    expect(
      markerLabel(
        marker({ phase: "starting", clients: [client({ phase: "starting", starts_on: "2026-11-01" })] }),
      ),
    ).toBe("Zaczyna u nas 01.11.2026 · Bank Przykładowy");
  });

  it("dwóch klientów: nazwy bez daty", () => {
    expect(
      markerLabel(
        marker({
          clients: [
            client({ order_end_date: "2026-12-31" }),
            client({ client_id: 101, client_name: "Ubezpieczenia Przykładowe", phase: "ending", order_end_date: "2026-10-20" }),
          ],
        }),
      ),
    ).toBe("Pracuje u nas · Bank Przykładowy, Ubezpieczenia Przykładowe");
  });

  it("więcej niż dwóch klientów albo wąskie miejsce: liczba", () => {
    const three = marker({
      clients: [client(), client({ client_id: 101, client_name: "B" }), client({ client_id: 102, client_name: "C" })],
    });
    expect(markerLabel(three)).toBe("Pracuje u nas · 3 klientów");
    expect(
      markerLabel(marker({ clients: [client(), client({ client_id: 101, client_name: "B" })] }), {
        clients: "count",
      }),
    ).toBe("Pracuje u nas · 2 klientów");
  });

  it("przyszły start u drugiego klienta nie wchodzi do nagłówka „pracuje”", () => {
    expect(
      markerLabel(
        marker({
          clients: [client(), client({ client_id: 101, client_name: "Nowy", phase: "starting", starts_on: "2026-11-01" })],
        }),
      ),
    ).toBe("Pracuje u nas · Bank Przykładowy");
  });

  it("krótka wersja: bez klienta, data bez roku", () => {
    const ending = marker({
      phase: "ending",
      clients: [client({ phase: "ending", order_end_date: "2026-11-30" })],
    });
    expect(markerLabel(ending, { clients: "none", date: "short" })).toBe("Kończy u nas 30.11");
    expect(markerLabel(marker({ clients: [client({ order_end_date: "2026-12-31" })] }), { clients: "none" })).toBe(
      "Pracuje u nas · do 31.12.2026",
    );
    expect(markerLabel(marker(), { clients: "none" })).toBe("Pracuje u nas");
  });

  it("klient rekrutacji: „u tego klienta”, bez nazwy", () => {
    expect(markerLabel(marker({ elsewhere: false }))).toBe("Pracuje u tego klienta");
    expect(
      markerLabel(marker({ elsewhere: false, clients: [client({ order_end_date: "2026-12-31" })] })),
    ).toBe("Pracuje u tego klienta · do 31.12.2026");
    // U innego klienta zostaje zwykły znacznik z nazwą.
    expect(markerLabel(marker({ elsewhere: true }))).toBe("Pracuje u nas · Bank Przykładowy");
  });

  it("klient bez nazwy: numer; bez klienta: sam nagłówek", () => {
    expect(markerLabel(marker({ clients: [client({ client_name: null })] }))).toBe("Pracuje u nas · Klient #100");
    expect(markerLabel(marker({ clients: [client({ client_id: null, client_name: null })] }))).toBe(
      "Pracuje u nas",
    );
  });
});

describe("markerTone", () => {
  it("faza wyznacza kolor, klient rekrutacji zawsze ostrzega", () => {
    expect(markerTone(marker())).toBe("success");
    expect(markerTone(marker({ phase: "ending" }))).toBe("warning");
    expect(markerTone(marker({ phase: "starting" }))).toBe("info");
    expect(markerTone(marker({ elsewhere: false }))).toBe("warning");
  });
});

describe("markerDetails", () => {
  it("wiersz na klienta: zamówienie i Delivery Lead", () => {
    expect(
      markerDetails(
        marker({
          clients: [
            client({ order_end_date: "2026-12-31", delivery_lead_name: "Karol Wzorcowy" }),
            client({ client_id: 101, client_name: "Nowy", contract_id: 11, phase: "starting", starts_on: "2026-11-01" }),
          ],
        }),
      ),
    ).toEqual([
      {
        key: "100:10",
        title: "Pracuje u nas · Bank Przykładowy",
        detail: "Zamówienie do 31.12.2026 · Delivery Lead: Karol Wzorcowy",
        contractId: 10,
      },
      { key: "101:11", title: "Zaczyna u nas · Nowy", detail: "Start 01.11.2026", contractId: 11 },
    ]);
  });

  it("umowa bez końca zamówień: „Zamówienie bez daty końca”, nic o ręcznym oznaczeniu ani etapie", () => {
    // 17.10.2026: znacznik daje tylko umowa w Kontraktach.
    const [line] = markerDetails(marker({ clients: [client({ delivery_lead_name: "Karol Wzorcowy" })] }));
    expect(line.detail).toBe("Zamówienie bez daty końca · Delivery Lead: Karol Wzorcowy");
    expect(line.detail).not.toMatch(/ręcznie|Zatrudniony/);
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
