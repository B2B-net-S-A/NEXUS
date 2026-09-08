/**
 * Arytmetyka tabel rok-do-roku Rady.
 *
 * Testujemy warstwę, która NAPRAWDĘ przenosi znaczenie — nie komponent. Lekcja
 * z PR #1316: `PeriodPicker` był poprawny i w pełni przetestowany, a martwe
 * było jego podłączenie, bo testy kończyły się na argumencie callbacka.
 *
 * Cztery defekty DynaReportera, których te testy pilnują:
 *
 * 1. **„Suma" pod kolumną procentów dawała 874%** — procenty się nie sumują.
 * 2. **`+0,0%` oceniane jako „Lepiej"** — dwie identyczne liczby dostawały
 *    zieloną plakietkę poprawy.
 * 3. **Niepełny rok porównywany z pełnym** — dziewięć miesięcy 2026 obok
 *    dwunastu miesięcy 2025 pokazywało spadek, którego nie ma.
 * 4. **Zmiana wskaźnika podawana jako procent z procentu** — „hit ratio wzrosło
 *    o 50%" przy 20% → 30% jest prawdą arytmetyczną i myli każdego czytelnika.
 */

import { describe, expect, it } from "vitest";

import type { InsightsYoYMetric } from "@/lib/insights-api";
import {
  aggregateSeries,
  buildYoYTable,
  coveredMonths,
  verdictFor,
  yoyDelta,
} from "@/lib/insights-yoy";

const MONTHS = [
  "sty",
  "lut",
  "mar",
  "kwi",
  "maj",
  "cze",
  "lip",
  "sie",
  "wrz",
  "paź",
  "lis",
  "gru",
];

function metric(over: Partial<InsightsYoYMetric> = {}): InsightsYoYMetric {
  return {
    key: "placements",
    group: "hr",
    label: "Liczba placementów",
    unit: "count",
    aggregate: "sum",
    lower_is_better: false,
    definition: null,
    note: null,
    // Domyślnie „z kontraktów" — to podstawa dotknięta luką w ewidencji,
    // więc test bez jawnego wyboru pracuje na wariancie ostrożniejszym.
    basis: "contracts",
    series: {},
    ...over,
  };
}

describe("yoyDelta — jednostka zmiany zależy od jednostki metryki", () => {
  it("wskaźnik procentowy zmienia się w PUNKTACH procentowych", () => {
    // 20% → 30% to +10 pp. Podane jako „+50%" byłoby arytmetycznie prawdziwe
    // i mylące dla każdego, kto to czyta.
    const d = yoyDelta(20, 30, { unit: "pct", lowerIsBetter: false });
    expect(d.mode).toBe("pp");
    expect(d.value).toBe(10);
    expect(d.verdict).toBe("better");
  });

  it("kwoty i liczby zmieniają się względnie", () => {
    const d = yoyDelta(200, 250, { unit: "pln", lowerIsBetter: false });
    expect(d.mode).toBe("pct");
    expect(d.value).toBe(25);
  });

  it("zero w mianowniku daje null, nie nieskończoność", () => {
    // Wzrost „o nieskończoność" nie jest liczbą, a 0 czytałoby się jako
    // „bez zmian" — czyli odwrotnie niż jest.
    expect(yoyDelta(0, 12, { unit: "count", lowerIsBetter: false }).value).toBe(
      null,
    );
    expect(
      yoyDelta(0, 12, { unit: "count", lowerIsBetter: false }).verdict,
    ).toBe("unknown");
  });

  it("brak którejkolwiek wartości daje null", () => {
    expect(yoyDelta(null, 5, { unit: "count", lowerIsBetter: false }).value).toBe(
      null,
    );
    expect(yoyDelta(5, null, { unit: "count", lowerIsBetter: false }).value).toBe(
      null,
    );
  });

  it("wskaźnik procentowy Z ZEROWĄ bazą nadal liczy się w pp", () => {
    // Dla `pp` zero w bazie jest legalne: 0% → 8% to +8 pp. Gałąź „zero
    // w mianowniku" dotyczy wyłącznie zmiany względnej.
    const d = yoyDelta(0, 8, { unit: "pct", lowerIsBetter: false });
    expect(d.value).toBe(8);
    expect(d.verdict).toBe("better");
  });
});

describe("verdictFor — zero to „bez zmian”, nigdy „Lepiej”", () => {
  it("brak zmiany nie jest poprawą", () => {
    expect(verdictFor(0, false)).toBe("flat");
    expect(verdictFor(0, true)).toBe("flat");
  });

  it("dla metryk „im mniej, tym lepiej” spadek jest poprawą", () => {
    // Zejścia, koszty, koncentracja klienta. Bez tej flagi wzrost dostałby
    // zieloną strzałkę w górę, czyli komunikat odwrotny do prawdy.
    expect(verdictFor(-20, true)).toBe("better");
    expect(verdictFor(20, true)).toBe("worse");
    expect(verdictFor(20, false)).toBe("better");
  });

  it("brak danych to „—”, nie ocena", () => {
    expect(verdictFor(null, false)).toBe("unknown");
  });
});

describe("aggregateSeries — procenty się nie sumują", () => {
  const twelve = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120];

  it("przepływ się sumuje", () => {
    expect(aggregateSeries(twelve, "sum")).toBe(780);
  });

  it("stan i wskaźnik się uśredniają", () => {
    expect(aggregateSeries(twelve, "avg")).toBe(65);
  });

  it("średnia dzieli przez miesiące POLICZONE, nie przez dwanaście", () => {
    // Dziewięć miesięcy podzielone przez 12 zaniżyłoby wynik o jedną czwartą
    // i pokazałoby załamanie, którego nie ma.
    const nine = [...twelve.slice(0, 9), null, null, null];
    expect(aggregateSeries(nine, "avg")).toBe(50);
    expect(aggregateSeries(nine, "sum")).toBe(450);
  });

  it("sam null daje null, nie zero", () => {
    expect(aggregateSeries([null, null], "sum")).toBe(null);
    expect(aggregateSeries([null, null], "avg")).toBe(null);
  });

  it("limit miesięcy zawęża zakres (porównanie YTD)", () => {
    expect(aggregateSeries(twelve, "sum", 3)).toBe(60);
    expect(aggregateSeries(twelve, "avg", 3)).toBe(20);
  });
});

describe("coveredMonths", () => {
  it("liczy nieprzerwany prefiks od stycznia", () => {
    expect(coveredMonths([1, 2, 3, null, null])).toBe(3);
    expect(coveredMonths([null, 2, 3])).toBe(0);
    expect(coveredMonths([1, 2, 3])).toBe(3);
  });
});

describe("buildYoYTable", () => {
  const years = [2024, 2025, 2026];
  const full = (v: number) => Array(12).fill(v);

  it("porównuje niepełny rok z TYMI SAMYMI miesiącami roku poprzedniego", () => {
    // 2025: dwanaście miesięcy po 10 = 120. 2026: dziewięć miesięcy po 10 = 90.
    // Porównanie 90 vs 120 dałoby −25%, czyli spadek, którego nie ma — oba lata
    // biegną w tym samym tempie.
    const m = metric({
      series: {
        "2024": full(8),
        "2025": full(10),
        "2026": [...Array(9).fill(10), null, null, null],
      },
    });
    const table = buildYoYTable(m, years, MONTHS, { year: 2026, month: 9 });

    expect(table.summary.ytd).toBe(true);
    expect(table.summary.comparedMonths).toBe(9);
    // Komórka nadal pokazuje CAŁY rok — to liczba, którą czytelnik chce widzieć.
    expect(table.summary.values).toEqual([96, 120, 90]);
    // ...ale ostatnia delta porównuje 90 z 90, czyli „bez zmian".
    expect(table.summary.deltas[1].value).toBe(0);
    expect(table.summary.deltas[1].verdict).toBe("flat");
    // Delta między dwoma PEŁNYMI latami zostaje pełna: 96 → 120 = +25%.
    expect(table.summary.deltas[0].value).toBe(25);
  });

  it("dwa zamknięte lata porównują się w całości", () => {
    const m = metric({
      series: { "2024": full(8), "2025": full(10), "2026": full(12) },
    });
    const table = buildYoYTable(m, years, MONTHS, null);
    expect(table.summary.ytd).toBe(false);
    expect(table.summary.values).toEqual([96, 120, 144]);
    expect(table.summary.deltas[1].value).toBe(20);
  });

  it("oznacza miesiąc, który jeszcze trwa — i tylko w ostatnim roku", () => {
    const m = metric({
      series: {
        "2024": full(8),
        "2025": full(10),
        "2026": [...Array(9).fill(10), null, null, null],
      },
    });
    const table = buildYoYTable(m, years, MONTHS, { year: 2026, month: 9 });
    expect(table.rows[8].partial).toBe(true);
    expect(table.rows.filter((r) => r.partial)).toHaveLength(1);
  });

  it("miesiąc przyszły renderuje się jako brak, nie jako zero", () => {
    const m = metric({
      series: {
        "2024": full(8),
        "2025": full(10),
        "2026": [...Array(9).fill(10), null, null, null],
      },
    });
    const table = buildYoYTable(m, years, MONTHS, { year: 2026, month: 9 });
    expect(table.rows[11].values[2]).toBe(null);
    // Delta z brakującą wartością nie może udawać spadku do zera.
    expect(table.rows[11].deltas[1].value).toBe(null);
    expect(table.rows[11].deltas[1].verdict).toBe("unknown");
  });

  it("wiersz miesiąca ma tyle wartości, ile lat, i o jedną deltę mniej", () => {
    const m = metric({
      series: { "2024": full(1), "2025": full(2), "2026": full(3) },
    });
    const table = buildYoYTable(m, years, MONTHS, null);
    expect(table.rows).toHaveLength(12);
    for (const row of table.rows) {
      expect(row.values).toHaveLength(3);
      expect(row.deltas).toHaveLength(2);
    }
  });

  it("brakujący rok w serii nie wywraca tabeli", () => {
    // Serwer może zawęzić lata (parametr `years`); widok ma to przeżyć,
    // pokazując „—", a nie pustą stronę.
    const m = metric({ series: { "2026": full(5) } });
    const table = buildYoYTable(m, years, MONTHS, null);
    expect(table.rows[0].values).toEqual([null, null, 5]);
    expect(table.summary.values).toEqual([null, null, 60]);
  });
});
