/**
 * 409 `ELIGIBILITY_WARNING` (17.09.2026): tablica rozpoznaje ostrzeżenie po
 * `code` w strukturalnym `detail` i NIE myli go z innymi 409 z tej samej trasy.
 */

import { describe, expect, it } from "vitest";

import {
  eligibilityWarningReason,
  isEligibilityWarning,
} from "@/lib/pipeline-eligibility-warning";

const err = (status: number, detail: unknown) => ({
  response: { status, data: { detail } },
});

describe("isEligibilityWarning", () => {
  it("strukturalne 409 z kodem ostrzeżenia → powód z serwera", () => {
    const e = err(409, {
      code: "ELIGIBILITY_WARNING",
      reason_code: "client_nda",
      reason: "Kandydat ma aktywne NDA z tym klientem.",
      can_acknowledge: true,
    });
    expect(isEligibilityWarning(e)).toBe(true);
    expect(eligibilityWarningReason(e)).toBe(
      "Kandydat ma aktywne NDA z tym klientem.",
    );
  });

  it("409 z tekstowym `detail` (bulk, wtyczka) nie jest ostrzeżeniem", () => {
    const e = err(409, "Kandydat jest na czarnej liście.");
    expect(isEligibilityWarning(e)).toBe(false);
    expect(eligibilityWarningReason(e)).toBeNull();
  });

  it("konflikt wersji procesu nie jest ostrzeżeniem dopuszczalności", () => {
    expect(
      isEligibilityWarning(
        err(409, { code: "PIPELINE_VERSION_CONFLICT", message: "x" }),
      ),
    ).toBe(false);
  });

  it("inny status niż 409 nie jest ostrzeżeniem", () => {
    expect(
      isEligibilityWarning(
        err(422, { code: "ELIGIBILITY_WARNING", reason: "x" }),
      ),
    ).toBe(false);
  });
});
