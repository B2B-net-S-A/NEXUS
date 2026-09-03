/**
 * Lejek konwersji — „—" z braku pokrycia musi być odróżnialne od „—" z zera.
 *
 * Na produkcji wisiało tu `akceptacja → placement = 3257,1%` (228 placementów
 * przez 7 akceptacji), bo etapu `acceptance` nie zapełnia import z Traffita.
 * Backend wygasza takie ilorazy do `null`; sam `null` renderuje się jako „—",
 * co jest poprawą, ale bez powodu byłoby tylko cichą dwuznacznością.
 *
 * Import bezpośredni, z pominięciem `next/dynamic` — sekcja ładuje wykres
 * dynamicznie z `ssr:false`, a asercja przez sekcję byłaby krucha.
 */

import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RecruitmentTrendChart } from "@/components/v2/dashboard/RecruitmentTrendChart";
import type {
  RecruitmentFunnelConversions,
  RecruitmentTeamTableTotals,
} from "@/lib/dashboard-v2-api";

const TOTALS = {
  verifications: 6975,
  recommendations: 5232,
  interviews: 3416,
  acceptances: 7,
  placements: 228,
  cv_to_base: 0,
  precision_pct: null,
  people: 12,
} as unknown as RecruitmentTeamTableTotals;

const NOTE =
  "Konwersje przez etapy bez pokrycia w imporcie (Akceptacja) są wygaszone " +
  "— tych etapów nie zapełnia synchronizacja z Traffita, więc iloraz przez " +
  "nie nie opisywałby rzeczywistości.";

function conversions(
  overrides: Partial<RecruitmentFunnelConversions> = {},
): RecruitmentFunnelConversions {
  return {
    verified_to_recommendation_pct: 75,
    recommendation_to_interview_pct: 65.3,
    interview_to_acceptance_pct: null,
    acceptance_to_placement_pct: null,
    interview_to_placement_pct: 6.7,
    overall_pct: 3.3,
    uncovered: [
      "interview_to_acceptance_pct",
      "acceptance_to_placement_pct",
    ],
    coverage_note: NOTE,
    ...overrides,
  };
}

describe("RecruitmentTrendChart — pokrycie etapów", () => {
  it("nazywa powód zamiast pokazywać iloraz zbudowany na etapie bez danych", () => {
    render(
      <RecruitmentTrendChart
        trend={null}
        conversions={conversions()}
        totals={TOTALS}
      />,
    );

    expect(screen.getByText(/bez pokrycia w imporcie/i)).toBeTruthy();
    expect(screen.queryByText(/3257/)).toBeNull();
  });

  it("nadal renderuje zdrowe konwersje", () => {
    render(
      <RecruitmentTrendChart
        trend={null}
        conversions={conversions()}
        totals={TOTALS}
      />,
    );

    expect(screen.getByText("75%")).toBeTruthy();
    expect(screen.getByText("65.3%")).toBeTruthy();
    expect(screen.getByText(/Overall 3.3%/)).toBeTruthy();
  });

  it("nie pokazuje noty, gdy każdy etap ma pokrycie", () => {
    render(
      <RecruitmentTrendChart
        trend={null}
        conversions={conversions({
          interview_to_acceptance_pct: 29.3,
          acceptance_to_placement_pct: 58.3,
          uncovered: [],
          coverage_note: null,
        })}
        totals={TOTALS}
      />,
    );

    expect(screen.queryByText(/bez pokrycia w imporcie/i)).toBeNull();
    expect(screen.getByText("58.3%")).toBeTruthy();
  });
});
