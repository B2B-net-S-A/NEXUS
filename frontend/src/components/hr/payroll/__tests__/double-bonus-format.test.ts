/**
 * Premia 200% (decyzje Artura 05.11.2026): opis warunków osoby i stan
 * „w trakcie” / „po końcu miesiąca”. Dane fikcyjne.
 */
import { describe, expect, it } from "vitest";

import type { DoubleBonusDl, DoubleBonusRecruiter } from "@/lib/api/hr-payroll";

import { doubleBonusConditions, doubleBonusState, progressShare } from "../double-bonus-format";
import { cancelReasonLabel, doubleBonusNote } from "../payroll-format";

const recruiter: DoubleBonusRecruiter = {
  user_id: 1,
  name: "Osoba Przykładowa",
  kind: "recruiter",
  placements: 1,
  target: 2,
  verifications_per_day: "3.2",
  precision_pct: "87.1",
  checks: { placements: false, verifications: false, precision: true },
  excluded: null,
  qualified: false,
  contracts: [],
};

const dl: DoubleBonusDl = {
  user_id: 2,
  name: "Druga Osoba",
  kind: "dl",
  placements: 3,
  average_margin: "49.00",
  missing_margins: 1,
  excluded: null,
  qualified: false,
  contracts: [],
};

describe("doubleBonusConditions", () => {
  it("rekruter: placementy z celem, weryfikacje na dzień i precision", () => {
    expect(doubleBonusConditions(recruiter)).toBe(
      "placementy 1/2 · weryfikacje 3,2/dzień · precision 87%",
    );
  });

  it("DL: średnia marża i kontrakty bez stawki", () => {
    expect(doubleBonusConditions(dl)).toBe(
      "placementy 3 · średnia marża 49 zł/h · bez stawki: 1",
    );
  });
});

describe("doubleBonusState", () => {
  it("w trakcie miesiąca to postęp, po końcu decyzja", () => {
    expect(doubleBonusState({ ...recruiter, qualified: true }, false).label).toBe("na dziś spełnia");
    expect(doubleBonusState({ ...recruiter, qualified: true }, true)).toEqual({
      label: "200%",
      tone: "success",
    });
    expect(doubleBonusState(recruiter, true).label).toBe("zwykła premia");
    expect(doubleBonusState(recruiter, false).label).toBe("jeszcze nie");
  });

  it("po zapisie liczy się decyzja; rozjazd ze stanem na dziś każe przeliczyć", () => {
    expect(doubleBonusState({ ...recruiter, qualified: true, decided: false }, true)).toEqual({
      label: "zwykła premia · do przeliczenia",
      tone: "neutral",
    });
    expect(doubleBonusState({ ...dl, qualified: true, decided: true }, true).label).toBe("200%");
  });
});

describe("progressShare", () => {
  it("udział w celu od 0 do 100", () => {
    expect(progressShare("3.2", "4")).toBe(80);
    expect(progressShare("5", "4")).toBe(100);
    expect(progressShare(null, "4")).toBe(0);
    expect(progressShare(1, 0)).toBe(100);
  });
});

describe("opisy premii", () => {
  it("premia 200% mówi, za który miesiąc", () => {
    expect(doubleBonusNote("2026-11")).toBe("200% za cel w listopadzie 2026");
    expect(doubleBonusNote("zły")).toBe("200% za cel");
  });

  it("gwarancja ma własny powód anulowania", () => {
    expect(cancelReasonLabel("guarantee")).toContain("gwarancji");
    expect(cancelReasonLabel("client_referral")).toContain(
      "kandydat wskazany przez klienta",
    );
  });
});
