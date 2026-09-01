/**
 * Round-trip okresu przez URL — warstwa, w której „Wszystko" ginęło.
 *
 * Test pickera asertował argument `onChange` i był ZIELONY, kiedy przycisk był
 * martwy: daty gubiły się dopiero w panelu, przy zapisie do URL-a, a przy
 * odczycie `custom` nie przechodziło przez listę granulacji i wracało na
 * „Miesiąc". Ten plik testuje dokładnie to przejście — zapis, a potem odczyt
 * tego, co zapisaliśmy.
 */
import { describe, expect, it } from "vitest";

import {
  INSIGHTS_URL_KINDS,
  readPeriodFromParams,
  writePeriodToParams,
} from "@/lib/insights-period-url";
import { DEFAULT_INSIGHTS_OFFSET } from "@/lib/insights-api";

const ALL_TIME = {
  period: "custom" as const,
  date_from: "2025-09-02",
  date_to: "2026-09-01",
};

describe("okres w URL-u", () => {
  it("przeżywa round-trip granulacji „Wszystko”", () => {
    const written = writePeriodToParams(new URLSearchParams(), ALL_TIME);
    // Bez tego przycisk „Wszystko" wraca na „Miesiąc" przy najbliższym renderze.
    expect(readPeriodFromParams(written)).toEqual(ALL_TIME);
  });

  it("nie wysyła `offset` razem z jawnym zakresem", () => {
    // Backend zwraca 422 na tę parę — URL nie może jej nieść.
    const written = writePeriodToParams(
      new URLSearchParams("period=month&offset=-3"),
      ALL_TIME,
    );
    expect(written.get("offset")).toBeNull();
    expect(readPeriodFromParams(written).offset).toBeUndefined();
  });

  it("kasuje zwietrzałe daty przy powrocie na granulację kalendarzową", () => {
    const written = writePeriodToParams(
      new URLSearchParams(
        "period=custom&date_from=2025-01-01&date_to=2025-12-31",
      ),
      { period: "month", offset: -1 },
    );
    // Zostawione daty czyniłyby z linku coś innego, niż widział klikający.
    expect(written.get("date_from")).toBeNull();
    expect(written.get("date_to")).toBeNull();
    expect(readPeriodFromParams(written)).toEqual({
      period: "month",
      offset: -1,
    });
  });

  it("zachowuje pozostałe parametry adresu, np. zakładkę", () => {
    const written = writePeriodToParams(
      new URLSearchParams("tab=rekrutacja"),
      ALL_TIME,
    );
    expect(written.get("tab")).toBe("rekrutacja");
  });

  it("niekompletny `custom` degraduje do domyślnego okna, a nie do żądania pewnego 422", () => {
    expect(readPeriodFromParams(new URLSearchParams("period=custom"))).toEqual({
      period: "month",
      offset: DEFAULT_INSIGHTS_OFFSET,
    });
    expect(
      readPeriodFromParams(
        new URLSearchParams("period=custom&date_from=2025-01-01"),
      ),
    ).toEqual({ period: "month", offset: DEFAULT_INSIGHTS_OFFSET });
  });

  it("odrzuca daty w złym formacie zamiast wysyłać je dalej", () => {
    expect(
      readPeriodFromParams(
        new URLSearchParams("period=custom&date_from=wczoraj&date_to=dzis"),
      ).period,
    ).toBe("month");
  });

  it("szanuje domyślne zakładki, bo trzy zakładki mają trzy różne", () => {
    expect(
      readPeriodFromParams(new URLSearchParams(), {
        kind: "quarter",
        offset: 0,
      }),
    ).toEqual({ period: "quarter", offset: 0 });
  });

  it("nieznana granulacja wraca na domyślną, nie wywraca odczytu", () => {
    expect(readPeriodFromParams(new URLSearchParams("period=dekada"))).toEqual({
      period: "month",
      offset: DEFAULT_INSIGHTS_OFFSET,
    });
  });

  it("lista granulacji URL-a zawiera `custom` — to jej brak zabijał „Wszystko”", () => {
    expect(INSIGHTS_URL_KINDS).toContain("custom");
  });
});
