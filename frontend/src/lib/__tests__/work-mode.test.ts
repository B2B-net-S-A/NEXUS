import { describe, expect, it } from "vitest";

import {
  formatWorkMode,
  modesForOfficeDays,
  profileWorkMode,
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
