import { describe, expect, it } from "vitest";

import {
  formatWorkMode,
  jobWorkModeLine,
  modesForOfficeDays,
  officeDaysChoiceLabel,
  officeDaysChoices,
  profileWorkMode,
  rejectionWorkModeOrigin,
  WORK_MODE_ORIGIN_KEY,
  workModeAfterRejection,
  workModeValidationError,
} from "@/lib/work-mode";

describe("work mode", () => {
  it("derives accepted modes from office days (lustro backendu)", () => {
    expect(modesForOfficeDays(0)).toEqual(["remote"]);
    expect(modesForOfficeDays(3)).toEqual(["remote", "hybrid"]);
    expect(modesForOfficeDays(5)).toEqual(["remote", "hybrid", "onsite"]);
  });

  it("says how many office days, not only „hybrydowo”", () => {
    expect(formatWorkMode(["remote", "hybrid"], 2)).toBe(
      "Hybrydowo lub zdalnie · do 2 dni w biurze w tygodniu",
    );
    expect(formatWorkMode(["hybrid"], 1)).toBe(
      "Hybrydowo · do 1 dnia w biurze w tygodniu",
    );
    expect(formatWorkMode(["remote", "hybrid", "onsite"], 5)).toBe(
      "Stacjonarnie, hybrydowo lub zdalnie · do 5 dni w biurze w tygodniu",
    );
    expect(formatWorkMode(["remote", "hybrid"], null)).toBe(
      "Hybrydowo lub zdalnie · liczba dni w biurze nieustalona",
    );
  });

  it("recognises remote-only and falls back to days when modes are missing", () => {
    expect(formatWorkMode(["remote"], null)).toBe("Tylko zdalnie");
    expect(formatWorkMode([], 0)).toBe("Tylko zdalnie");
    expect(formatWorkMode([], 2)).toBe(
      "Hybrydowo lub zdalnie · do 2 dni w biurze w tygodniu",
    );
    expect(formatWorkMode([], null)).toBeNull();
  });

  it("reads the profile shape defensively", () => {
    expect(profileWorkMode({ remote_modes: ["onsite", "remote", "x"] }, 5)).toEqual({
      modes: ["remote", "onsite"],
      days: 5,
    });
    expect(profileWorkMode(["remote"], 9)).toEqual({ modes: [], days: null });
  });

  it("mirrors the server coherence rules", () => {
    expect(workModeValidationError(["remote"], 2)).toMatch(/Tylko zdalnie/);
    expect(workModeValidationError(["remote", "hybrid"], 0)).toMatch(/0 dni/);
    expect(workModeValidationError(["remote", "hybrid"], 2)).toBeNull();
    expect(workModeValidationError([], 3)).toBeNull();
  });
});

describe("odrzucenie „Nie akceptuje trybu pracy” (14.10.2026)", () => {
  it("offers only fewer office days than the recruitment needs", () => {
    expect(officeDaysChoices(2)).toEqual([0, 1]);
    expect(officeDaysChoices(1)).toEqual([0]);
    expect(officeDaysChoices(5)).toEqual([0, 1, 2, 3, 4]);
  });

  it("offers 0–4 when the requirement is unknown", () => {
    expect(officeDaysChoices(null)).toEqual([0, 1, 2, 3, 4]);
    expect(officeDaysChoices(undefined)).toEqual([0, 1, 2, 3, 4]);
    expect(officeDaysChoices(0)).toEqual([0, 1, 2, 3, 4]);
  });

  it("labels the choices like a recruiter says them", () => {
    expect(officeDaysChoices(4).map(officeDaysChoiceLabel)).toEqual([
      "Tylko zdalnie",
      "Do 1 dnia",
      "Do 2 dni",
      "Do 3 dni",
    ]);
  });

  it("previews the profile value after the rejection", () => {
    expect(workModeAfterRejection(0)).toBe("Tylko zdalnie");
    expect(workModeAfterRejection(1)).toBe(
      "Hybrydowo lub zdalnie · do 1 dnia w biurze w tygodniu",
    );
  });

  it("describes the recruitment's work mode", () => {
    expect(jobWorkModeLine("hybrid", 2)).toBe("hybrydowo · 2 dni w biurze w tygodniu");
    expect(jobWorkModeLine("onsite", null)).toBe("stacjonarnie");
    expect(jobWorkModeLine(null, 1)).toBe("1 dzień w biurze w tygodniu");
    expect(jobWorkModeLine(null, null)).toBeNull();
  });

  it("reads the rejection origin of the profile value", () => {
    const origin = rejectionWorkModeOrigin({
      remote_modes: ["remote"],
      [WORK_MODE_ORIGIN_KEY]: {
        source: "rejection",
        at: "2026-10-14T08:30:00+00:00",
        job_title: "Java Developer",
        by_name: "Rekruter A",
      },
    });
    expect(origin).toEqual({
      text: "z odrzucenia · 14.10.2026 · Java Developer",
      title: "Powód odrzucenia: Nie akceptuje trybu pracy · Rekruter A · Java Developer",
    });
  });

  it("has no origin without the marker", () => {
    expect(rejectionWorkModeOrigin({ remote_modes: ["remote"] })).toBeUndefined();
    expect(rejectionWorkModeOrigin(null)).toBeUndefined();
    expect(
      rejectionWorkModeOrigin({ [WORK_MODE_ORIGIN_KEY]: { source: "other" } }),
    ).toBeUndefined();
  });
});
