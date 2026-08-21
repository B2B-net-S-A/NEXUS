/**
 * Testy stanów StatsBoundary (plan PR 5).
 *
 * deriveBoundaryState: fail-closed (disabled bez capability/trybu),
 * forbidden ≠ error, unavailable/partial z koperty — nigdy "0".
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  StatsBoundary,
  deriveBoundaryState,
} from "@/components/v2/dashboard/StatsBoundary";

const BASE = {
  allowed: true,
  isLoading: false,
  isError: false,
} as const;

describe("deriveBoundaryState", () => {
  it("disabled gdy brak capability/trybu (fail-closed)", () => {
    expect(deriveBoundaryState({ ...BASE, allowed: false })).toBe("disabled");
  });

  it("loading tylko gdy allowed", () => {
    expect(deriveBoundaryState({ ...BASE, isLoading: true })).toBe("loading");
    expect(
      deriveBoundaryState({ allowed: false, isLoading: true, isError: false })
    ).toBe("disabled");
  });

  it("403 to forbidden, inne błędy to error", () => {
    expect(
      deriveBoundaryState({ ...BASE, isError: true, errorStatus: 403 })
    ).toBe("forbidden");
    expect(
      deriveBoundaryState({ ...BASE, isError: true, errorStatus: 500 })
    ).toBe("error");
  });

  it("quality z koperty: unavailable/partial", () => {
    expect(
      deriveBoundaryState({
        ...BASE,
        quality: { status: "unavailable", warnings: [], source_watermarks: {} },
      })
    ).toBe("unavailable");
    expect(
      deriveBoundaryState({
        ...BASE,
        quality: { status: "partial", warnings: ["x"], source_watermarks: {} },
      })
    ).toBe("partial");
  });

  it("empty przed ready", () => {
    expect(deriveBoundaryState({ ...BASE, isEmpty: true })).toBe("empty");
    expect(deriveBoundaryState({ ...BASE })).toBe("ready");
  });
});

describe("StatsBoundary render", () => {
  it("unavailable NIE renderuje dzieci (zero nie udaje danych)", () => {
    render(
      <StatsBoundary state="unavailable">
        <div>SECRET-NUMBER-0</div>
      </StatsBoundary>
    );
    expect(screen.queryByText("SECRET-NUMBER-0")).toBeNull();
    expect(screen.getByText(/niedostępne/i)).toBeTruthy();
  });

  it("partial renderuje dzieci + ostrzeżenia", () => {
    render(
      <StatsBoundary state="partial" warnings={["brak kursu EUR"]}>
        <div>DANE</div>
      </StatsBoundary>
    );
    expect(screen.getByText("DANE")).toBeTruthy();
    expect(screen.getByText(/brak kursu EUR/)).toBeTruthy();
  });

  it("ready renderuje wyłącznie dzieci", () => {
    render(
      <StatsBoundary state="ready">
        <div>DANE</div>
      </StatsBoundary>
    );
    expect(screen.getByText("DANE")).toBeTruthy();
  });
});
