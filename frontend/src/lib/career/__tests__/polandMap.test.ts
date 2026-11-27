import { describe, expect, it } from "vitest";

import { buildCityMap, columnScale, fitLabel, inCities, officeNote, offerMapMode, textWidth } from "../polandMap";
import { facetCounts, jobCities, type Facet } from "../site";

/** Stan tablicy z 26.11.2026 (makieta A-pierwszy-ekran). */
const TODAY: Facet[] = [
  ["Warszawa", 77], ["Gdańsk", 42], ["Gdynia", 33], ["Łódź", 20],
  ["Katowice", 5], ["Sopot", 5], ["Kraków", 4], ["Bydgoszcz", 1],
].map(([label, count]) => ({ id: String(label).toLowerCase(), label: String(label), count: Number(count) }));

const cities = (city: string | null) => jobCities({ city });

describe("szklana mapa miast — kolumny z danych", () => {
  it("odtwarza makietę: 3,6 jednostki na ofertę, Warszawa 277,2 wysokości", () => {
    const map = buildCityMap(TODAY);
    const waw = map.columns.find((c) => c.label === "Warszawa")!;
    const gda = map.columns.find((c) => c.label === "Gdańsk")!;
    expect(waw.height).toBeCloseTo(277.2, 1);
    expect(gda.height).toBeCloseTo(151.2, 1);
    expect(waw.front).toBe("378.0,432.6 400.0,432.6 400.0,155.4 378.0,155.4");
    expect(waw.top).toBe("371.4,144.0 393.4,144.0 400.0,155.4 378.0,155.4");
    // Jedna oferta nie znika: najniższa kolumna ma 6 jednostek.
    expect(map.columns.find((c) => c.label === "Bydgoszcz")!.height).toBe(6);
  });

  it("wysokość i etykieta idą za liczbą, nie za makietą", () => {
    const map = buildCityMap([
      { id: "krakow", label: "Kraków", count: 30 },
      { id: "warszawa", label: "Warszawa", count: 10 },
    ]);
    const krk = map.columns.find((c) => c.label === "Kraków")!;
    const waw = map.columns.find((c) => c.label === "Warszawa")!;
    expect(krk.height).toBeGreaterThan(waw.height);
    expect(map.labels[0]).toMatchObject({ name: "Kraków", count: 30, size: "big" });
    expect(map.hub).toEqual(krk.foot);
    expect(map.flows).toHaveLength(1);
  });

  it("dużo ofert w jednym mieście ściska skalę, kolumna nie wychodzi poza mapę", () => {
    expect(columnScale(77)).toBeCloseTo(3.6, 6);
    expect(columnScale(20)).toBe(3.6);
    expect(columnScale(154)).toBeCloseTo(1.8, 5);
    const map = buildCityMap([{ id: "gdansk", label: "Gdańsk", count: 400 }]);
    expect(map.columns[0].height).toBeCloseTo(277.2, 1);
  });

  it("kolumny rysują się od tyłu do przodu (rosnąca podstawa)", () => {
    const bases = buildCityMap(TODAY).columns.map((c) => c.base);
    expect([...bases].sort((a, b) => a - b)).toEqual(bases);
  });

  it("rozmiary etykiet: największe miasto duże, od 10 ofert średnie, reszta w linii", () => {
    const sizes = Object.fromEntries(buildCityMap(TODAY).labels.map((l) => [l.name, l.size]));
    expect(sizes).toMatchObject({ Warszawa: "big", Gdańsk: "mid", Gdynia: "mid", Łódź: "mid", Sopot: "inline", Kraków: "inline" });
    expect(Object.keys(sizes)).toHaveLength(8);
  });

  it("telefon: etykiety tylko czterech największych", () => {
    expect(buildCityMap(TODAY, { phone: true }).labels.map((l) => l.name)).toEqual(["Warszawa", "Gdańsk", "Gdynia", "Łódź"]);
  });

  it("etykieta nie wchodzi w cudzą kolumnę: na telefonie „Gdańsk” przysuwa się do swojej", () => {
    const map = buildCityMap(TODAY, { phone: true });
    const waw = map.columns.find((c) => c.label === "Warszawa")!;
    const gda = map.labels.find((l) => l.name === "Gdańsk")!;
    // Szacunek szerokości jak w module: 0,56 em na znak, nazwa 27 jednostek.
    expect(gda.x + "Gdańsk".length * 27 * 0.56).toBeLessThanOrEqual(waw.x - 6.6);
    expect(gda.line[2]).toBeLessThan(gda.line[0] + 32);
  });

  it("miasto bez położenia na mapie i zero ofert nie dają kolumny; opis ma wszystkie miasta", () => {
    const map = buildCityMap([
      { id: "warszawa", label: "Warszawa", count: 3 },
      { id: "zakopane", label: "Zakopane", count: 2 },
      { id: "sopot", label: "Sopot", count: 0 },
    ]);
    expect(map.columns.map((c) => c.label)).toEqual(["Warszawa"]);
    expect(map.summary).toBe("Warszawa 3, Zakopane 2, Sopot 0");
  });

  it("pusta tablica = pusta mapa bez środka i linii", () => {
    expect(buildCityMap([])).toMatchObject({ columns: [], labels: [], hub: null, flows: [] });
  });

  it("liczy miasta z pola miejsca tablicy (Trójmiasto = trzy kolumny)", () => {
    const map = buildCityMap(facetCounts([{ city: "Trójmiasto" }, { city: "Priorytet Gdańsk" }, { city: "Warszawa" }]));
    expect(Object.fromEntries(map.columns.map((c) => [c.label, c.count]))).toEqual({
      Gdańsk: 2,
      Gdynia: 1,
      Sopot: 1,
      Warszawa: 1,
    });
  });
});

describe("mapa na stronie oferty: hybryda, zdalna, zamknięta", () => {
  it("hybryda i biuro podświetlają miasta oferty", () => {
    expect(offerMapMode("open", { city: "Warszawa, Łódź", remote_policy: "hybrid" }, cities)).toEqual({
      kind: "focus",
      cities: ["Warszawa", "Łódź"],
    });
    expect(offerMapMode("open", { city: "Kraków", remote_policy: "onsite" }, cities).kind).toBe("focus");
  });

  it("zdalna świeci cała, nawet gdy pole miasta coś ma", () => {
    expect(offerMapMode("open", { city: "Warszawa", remote_policy: "remote" }, cities)).toEqual({ kind: "remote" });
  });

  it("zamknięta: przerywany obrys z miastem albo bez", () => {
    expect(offerMapMode("closed", { city: "Gdańsk", remote_policy: "hybrid" }, cities)).toEqual({
      kind: "closed",
      cities: ["Gdańsk"],
    });
    expect(offerMapMode("closed", { city: "Gdańsk", remote_policy: "remote" }, cities)).toEqual({ kind: "closed", cities: [] });
    expect(offerMapMode("closed", null, cities)).toEqual({ kind: "closed", cities: [] });
  });

  it("miasto, którego nie ma na mapie, albo brak parametrów = mapa bez podświetlenia", () => {
    expect(offerMapMode("open", { city: "Polska", remote_policy: "hybrid" }, cities)).toEqual({ kind: "none" });
    expect(offerMapMode("open", null, cities)).toEqual({ kind: "none" });
  });

  it("podpis biura z parametrów, bez dopisywania", () => {
    const base = { onsite_days_per_week: null, onsite_days_per_month: null };
    expect(officeNote({ ...base, remote_policy: "hybrid", onsite_days_per_week: 1 })).toBe("biuro 1 dzień w tygodniu");
    expect(officeNote({ ...base, remote_policy: "hybrid", onsite_days_per_week: 3 })).toBe("biuro 3 dni w tygodniu");
    expect(officeNote({ ...base, remote_policy: "hybrid", onsite_days_per_month: 4 })).toBe("biuro 4 dni w miesiącu");
    expect(officeNote({ ...base, remote_policy: "onsite" })).toBe("praca w biurze");
    expect(officeNote({ ...base, remote_policy: "remote" })).toBeNull();
    expect(officeNote(null)).toBeNull();
  });
});

describe("liczba miast słowem", () => {
  it.each([
    [0, null],
    [1, "w jednym mieście"],
    [2, "w dwóch miastach"],
    [8, "w ośmiu miastach"],
    [14, "w 14 miastach"],
  ])("%i → %s", (n, text) => {
    expect(inCities(n)).toBe(text);
  });
});

describe("podpis obok kolumny mieści się w mapie (0–600)", () => {
  const inside = (colX: number, lines: { text: string; size: number }[], prefer: "left" | "right", gap?: number) => {
    const f = fitLabel(colX, lines, prefer, gap);
    const w = Math.max(...lines.map((l) => textWidth(l.text, l.size * f.scale)));
    return f.anchor === "end" ? f.x - w >= -0.01 : f.x + w <= 600.01;
  };

  it("Warszawa z podpisem biura zostaje po lewej jak na makiecie", () => {
    expect(fitLabel(378, [{ text: "Warszawa", size: 28 }, { text: "biuro 1 dzień w tygodniu", size: 18 }], "left")).toEqual({
      anchor: "end",
      x: 342,
      scale: 1,
    });
  });

  it.each([
    ["Trójmiasto po lewej Gdańska", 232.7, "Gdańsk, Gdynia, Sopot", 28, "left"],
    ["Szczecin przy lewej krawędzi", 40, "Szczecin", 36, "left"],
    ["zamknięta w Krakowie, po prawej", 377.3, "Kraków · zamknięta", 30.8, "right"],
    ["zamknięta w Rzeszowie, po prawej", 478.8, "Rzeszów · zamknięta", 30.8, "right"],
    ["długie hasło na pustej kolumnie", 278, "Programista COBOL mainfr…: 0", 33, "right"],
  ] as const)("%s", (_, x, text, size, prefer) => {
    expect(inside(x, [{ text, size }], prefer)).toBe(true);
  });
});

describe("podpis przy kilku podświetlonych miastach", () => {
  const lines = [{ text: "Warszawa, Gdańsk", size: 34 }];

  it("stoi po lewej od skrajnie lewej kolumny, gdy się tam mieści w pełnym rozmiarze", async () => {
    const { mapLabelColumn } = await import("../polandMap");
    const got = mapLabelColumn([{ x: 520 }, { x: 400 }, { x: 460 }], lines);
    expect(got?.column.x).toBe(400);
    expect(got?.fit.anchor).toBe("end");
    expect(got?.fit.scale).toBe(1);
  });

  it("po lewej brak miejsca — po prawej od skrajnie prawej, nigdy między kolumnami", async () => {
    const { mapLabelColumn } = await import("../polandMap");
    const got = mapLabelColumn([{ x: 60 }, { x: 120 }], lines);
    expect(got?.column.x).toBe(120);
    expect(got?.fit.anchor).toBe("start");
  });

  it("nigdzie się nie mieści — bez podpisu (miasta są w linii pod tytułem)", async () => {
    const { mapLabelColumn } = await import("../polandMap");
    expect(mapLabelColumn([{ x: 200 }, { x: 330 }], [{ text: "Warszawa, Gdańsk, Gdynia, Łódź", size: 34 }])).toBeNull();
    expect(mapLabelColumn([], lines)).toBeNull();
  });

  it("jedno miasto jak dotąd: zawsze z podpisem", async () => {
    const { mapLabelColumn, fitLabel } = await import("../polandMap");
    expect(mapLabelColumn([{ x: 378 }], lines)?.fit).toEqual(fitLabel(378, lines, "left"));
  });
});
