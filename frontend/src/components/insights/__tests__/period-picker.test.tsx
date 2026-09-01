/**
 * Pasek narzędzi okresu — reguły, których złamanie widać dopiero na produkcji.
 *
 * 1. **Ostatni dzień okresu ≠ `end`.** Okno jest półotwarte [start, end), więc
 *    podpis musi kończyć się na `end − 1 dzień`. Surowy `end` twierdziłby, że
 *    sierpień kończy się 1 września — liczby pod spodem mówiłyby wtedy co
 *    innego niż etykieta nad nimi.
 * 2. **Odejmowanie dnia jest KALENDARZOWE.** Doba zmiany czasu ma 23 lub 25
 *    godzin, więc `end − 24 h` gubi dzień w tygodniu zmiany czasu na letni.
 * 3. **„Wszystko” nie może przekroczyć `MAX_CUSTOM_PERIOD_DAYS` (366)** — backend
 *    odrzuca dłuższe okno błędem 422, nie przycina go po cichu. A skoro front
 *    przycina, musi to NAPISAĆ: „Wszystko” pod cichym limitem jest kłamstwem.
 * 4. **Reset wraca do domyślnego okresu RODZICA**, nie do jednego wpisanego na
 *    sztywno — każdy z trzech paneli ma inny domyślny.
 * 5. **„Eksportuj” bez danych się nie renderuje.** Przycisk oddający pusty plik
 *    czyta się jak utrata danych, a jest brakiem funkcji.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  INSIGHTS_MAX_CUSTOM_PERIOD_DAYS,
  PeriodPicker,
  buildAllTimePeriod,
  buildInsightsCsv,
  describeWindow,
  isoWeek,
  type InsightsCsvExport,
  type ResolvedInsightsWindow,
} from "@/components/insights/PeriodPicker";
import type { InsightsPeriodParams } from "@/lib/insights-api";

const TZ = "Europe/Warsaw";

/** Sierpień 2026 — okno półotwarte, tak jak zwraca `/api/insights/*`. */
const AUGUST: ResolvedInsightsWindow = {
  kind: "month",
  start: "2026-08-01T00:00:00+02:00",
  end: "2026-09-01T00:00:00+02:00",
  timezone: TZ,
};

/** Tydzień 35/2026 — dokładnie ten, który DynaReporter pokazuje w pasku. */
const WEEK_35: ResolvedInsightsWindow = {
  kind: "week",
  start: "2026-08-24T00:00:00+02:00",
  end: "2026-08-31T00:00:00+02:00",
  timezone: TZ,
};

function renderPicker(
  props: Partial<React.ComponentProps<typeof PeriodPicker>>,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const value: InsightsPeriodParams = props.value ?? {
    period: "month",
    offset: -1,
  };
  const utils = render(
    <QueryClientProvider client={client}>
      <PeriodPicker
        value={value}
        onChange={props.onChange ?? vi.fn()}
        resolved={props.resolved}
        defaultValue={props.defaultValue}
        csv={props.csv}
      />
    </QueryClientProvider>,
  );
  return { ...utils, client };
}

describe("PeriodPicker — podpis okna", () => {
  it("kończy okno na ostatnim dniu, który do niego NALEŻY (nie na `end`)", () => {
    renderPicker({ value: { period: "month", offset: 0 }, resolved: AUGUST });

    expect(screen.getByText(/1 sie 2026 – 31 sie 2026/)).toBeInTheDocument();
    // `end` to 1 września — gdyby wyciekł do podpisu, sierpień „trwałby”
    // o dzień dłużej niż liczby, które są pod nim.
    expect(screen.queryByText(/1 wrz/)).not.toBeInTheDocument();
  });

  it("pisze nagłówek miesiąca po polsku, wielką literą", () => {
    renderPicker({ value: { period: "month", offset: 0 }, resolved: AUGUST });
    expect(screen.getByText("Sierpień 2026")).toBeInTheDocument();
  });

  it("pisze tydzień w formacie DynaReportera — numer, rok i zakres dni", () => {
    renderPicker({ value: { period: "week", offset: 0 }, resolved: WEEK_35 });
    expect(screen.getByText("Tydzień 35/2026 (24–30 sie)")).toBeInTheDocument();
  });

  it("nie gubi dnia w tygodniu zmiany czasu na letni", () => {
    // 29.03.2026 ma 23 godziny. `end − 24 h` wskazałby 28 marca; poprawne
    // odjęcie jest kalendarzowe, więc ostatnim dniem tygodnia jest 29 marca.
    const caption = describeWindow(
      {
        kind: "week",
        start: "2026-03-23T00:00:00+01:00",
        end: "2026-03-30T00:00:00+02:00",
        timezone: TZ,
      },
      "week",
    );
    expect(caption?.headline).toBe("Tydzień 13/2026 (23–29 mar)");
    expect(caption?.range).toBe("23 mar 2026 – 29 mar 2026");
  });

  it("nazywa kwartał i rok tak, jak nazywa je użytkownik", () => {
    expect(
      describeWindow(
        {
          kind: "quarter",
          start: "2026-07-01T00:00:00+02:00",
          end: "2026-10-01T00:00:00+02:00",
          timezone: TZ,
        },
        "quarter",
      )?.headline,
    ).toBe("Q3 2026");

    expect(
      describeWindow(
        {
          kind: "year",
          start: "2026-01-01T00:00:00+01:00",
          end: "2027-01-01T00:00:00+01:00",
          timezone: TZ,
        },
        "year",
      )?.headline,
    ).toBe("2026");
  });

  it("bez okna z serwera nie zmyśla podpisu", () => {
    expect(describeWindow(null, "month")).toBeNull();
    expect(describeWindow(undefined, "month")).toBeNull();
  });

  it("liczy numer tygodnia ISO, nie numer od 1 stycznia", () => {
    // 1.01.2026 (czwartek) należy do tygodnia 1/2026, ale 1.01.2027 (piątek)
    // należy jeszcze do tygodnia 53/2026 — rok tygodnia bywa inny niż rok daty.
    expect(isoWeek(new Date(Date.UTC(2026, 0, 1)))).toEqual({
      week: 1,
      year: 2026,
    });
    expect(isoWeek(new Date(Date.UTC(2027, 0, 1)))).toEqual({
      week: 53,
      year: 2026,
    });
  });
});

describe("PeriodPicker — granulacja „Wszystko”", () => {
  it("mapuje się na custom i NIE przekracza limitu backendu", () => {
    const onChange = vi.fn();
    renderPicker({ value: { period: "month", offset: 0 }, onChange });

    fireEvent.click(screen.getByRole("button", { name: "Wszystko" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as InsightsPeriodParams;
    expect(next.period).toBe("custom");
    expect(next.date_from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(next.date_to).toMatch(/^\d{4}-\d{2}-\d{2}$/);

    // Backend liczy `date_to − date_from + 1` i odrzuca powyżej 366 dni.
    const span =
      (Date.parse(`${next.date_to}T00:00:00Z`) -
        Date.parse(`${next.date_from}T00:00:00Z`)) /
        86_400_000 +
      1;
    expect(span).toBe(INSIGHTS_MAX_CUSTOM_PERIOD_DAYS);
    expect(span).toBeLessThanOrEqual(INSIGHTS_MAX_CUSTOM_PERIOD_DAYS);
  });

  it("nie wysyła `offset` razem z jawnym zakresem", () => {
    // `resolve_period` odrzuca offset przy custom (422). `periodQuery` pomija
    // klucze `undefined`, więc brak klucza jest tu wymogiem, nie stylem.
    expect(buildAllTimePeriod().offset).toBeUndefined();
  });

  it("mówi na ekranie, że zakres został przycięty do limitu", () => {
    renderPicker({ value: buildAllTimePeriod(), resolved: null });

    const note = screen.getByText(/Wszystko[\s\S]*ostatnie 366 dni/);
    expect(note).toBeInTheDocument();
    expect(note.textContent).toMatch(/NIE jest cała historia/);
  });

  it("nie ostrzega o przycięciu przy krótszym oknie custom", () => {
    renderPicker({
      value: {
        period: "custom",
        date_from: "2026-08-01",
        date_to: "2026-08-31",
      },
    });
    expect(
      screen.queryByText(/NIE jest cała historia/),
    ).not.toBeInTheDocument();
  });

  it("gasi strzałki kotwicy, bo backend odrzuca offset przy custom", () => {
    renderPicker({ value: buildAllTimePeriod() });
    expect(
      screen.getByRole("button", { name: "Poprzedni okres" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Następny okres" }),
    ).toBeDisabled();
  });
});

describe("PeriodPicker — Reset i Odśwież", () => {
  it("Reset wraca do domyślnego okresu podanego przez rodzica", () => {
    const onChange = vi.fn();
    const defaultValue: InsightsPeriodParams = { period: "quarter", offset: 0 };
    renderPicker({
      value: { period: "week", offset: -7 },
      defaultValue,
      onChange,
    });

    fireEvent.click(screen.getByRole("button", { name: /Reset/ }));

    expect(onChange).toHaveBeenCalledWith(defaultValue);
  });

  it("Reset bez `defaultValue` wraca do poprzedniego zamkniętego miesiąca", () => {
    const onChange = vi.fn();
    renderPicker({ value: { period: "year", offset: -2 }, onChange });

    fireEvent.click(screen.getByRole("button", { name: /Reset/ }));

    expect(onChange).toHaveBeenCalledWith({ period: "month", offset: -1 });
  });

  it("Odśwież unieważnia wszystkie zapytania `insights`", () => {
    const { client } = renderPicker({ value: { period: "month", offset: 0 } });
    const spy = vi.spyOn(client, "invalidateQueries");

    fireEvent.click(screen.getByRole("button", { name: /Odśwież/ }));

    expect(spy).toHaveBeenCalledWith({ queryKey: ["insights"] });
  });
});

describe("PeriodPicker — eksport CSV", () => {
  const CSV: InsightsCsvExport = {
    filename: "insights-rekrutacja",
    headers: ["Etap", "Liczba"],
    rows: [
      ["Weryfikacje", 828],
      ["Placements", 21],
    ],
  };

  beforeEach(() => {
    // jsdom nie implementuje ObjectURL — bez tego klik w „Eksportuj” wybucha.
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:test"),
      revokeObjectURL: vi.fn(),
    });
  });

  it("nie renderuje przycisku bez propu z danymi", () => {
    renderPicker({ value: { period: "month", offset: 0 } });
    expect(screen.queryByRole("button", { name: /Eksportuj/ })).toBeNull();
  });

  it("nie renderuje przycisku przy zerowej liczbie wierszy", () => {
    renderPicker({
      value: { period: "month", offset: 0 },
      csv: { ...CSV, rows: [] },
    });
    expect(screen.queryByRole("button", { name: /Eksportuj/ })).toBeNull();
  });

  it("pobiera plik nazwany oknem, którego dotyczy", () => {
    const clicks: Array<{ download: string }> = [];
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicks.push({ download: this.download });
      });

    renderPicker({
      value: { period: "month", offset: 0 },
      resolved: AUGUST,
      csv: CSV,
    });
    fireEvent.click(screen.getByRole("button", { name: /Eksportuj/ }));

    expect(clicks).toEqual([
      { download: "insights-rekrutacja_2026-08-01_2026-08-31.csv" },
    ]);
    clickSpy.mockRestore();
  });

  it("cytuje pola z separatorem i zostawia `null` PUSTE, nie zerowe", () => {
    const csv = buildInsightsCsv(
      ["Etap", "Uwaga", "Liczba"],
      [["Rekomendacje", 'a;b "c"', null]],
    );
    expect(csv).toBe('Etap;Uwaga;Liczba\r\nRekomendacje;"a;b ""c""";');
  });
});
