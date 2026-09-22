import { describe, expect, it } from "vitest";

import {
  availabilityCellText,
  candidatesCountLabel,
  lastContactText,
  processCell,
  rateCellText,
} from "@/components/v2/candidates/candidate-row-format";

describe("candidate-row-format", () => {
  it("dostępność: data > okres wypowiedzenia > deklaracja > brak", () => {
    expect(
      availabilityCellText({ availability_date: "2026-10-01", notice_period: 1, notice_period_unit: "months" }),
    ).toBe("od 01.10");
    expect(availabilityCellText({ notice_period: 2, notice_period_unit: "weeks" })).toBe("za 2 tyg.");
    expect(availabilityCellText({ availability_status: "actively_looking" })).toBe("szuka aktywnie");
    expect(availabilityCellText({ availability_status: "unknown" })).toBeNull();
    expect(availabilityCellText({})).toBeNull();
  });

  it("w procesie: zatrudnienie wygrywa, zamknięte rekrutacje się nie liczą", () => {
    expect(processCell({ state: "employed_at_client", client_name: "PKO BP" }, [])).toEqual({
      text: "Pracuje u nas · PKO BP",
      tone: "employed",
    });
    expect(
      processCell(null, [
        { job_id: 1, job_title: "A", stage: "verified", moved_at: "2026-09-01T00:00:00Z" },
        { job_id: 2, job_title: "B", stage: "client_interview", moved_at: "2026-09-10T00:00:00Z" },
        { job_id: 3, job_title: "C", stage: "hired", moved_at: "2026-09-20T00:00:00Z" },
      ]),
    ).toEqual({ text: "2 procesy · Rozmowa u klienta", tone: "process" });
    expect(
      processCell(null, [{ job_id: 1, job_title: "A", stage: "new" }])?.text,
    ).toBe("1 proces · Nowy");
    expect(processCell(null, [{ job_id: 1, job_title: "A", stage: "rejected" }])).toBeNull();
    expect(processCell(undefined, null)).toBeNull();
  });

  it("stawka w zł/h, obca waluta wprost, zero = brak", () => {
    expect(rateCellText({ expected_rate_hourly: 160 })).toBe("160 zł/h");
    expect(rateCellText({ expected_rate_hourly: "142.5", expected_rate_currency: "PLN" })).toBe("142,5 zł/h");
    expect(rateCellText({ expected_rate_hourly: 40, expected_rate_currency: "eur" })).toBe("40 EUR/h");
    expect(rateCellText({ expected_rate_hourly: 0 })).toBeNull();
    expect(rateCellText({})).toBeNull();
  });

  it("ostatni kontakt i licznik", () => {
    expect(lastContactText(null)).toBeNull();
    expect(lastContactText("2026-01-01T00:00:00Z")).toBeTruthy();
    expect(candidatesCountLabel(1)).toBe("1 kandydat");
    expect(candidatesCountLabel(248)).toBe("248 kandydatów");
  });
});
