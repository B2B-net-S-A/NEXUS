import { describe, expect, it } from "vitest";

import { candidateWindowError, interviewStart, isWindow, windowBounds } from "@/lib/interview-pick";

const fixed = { start: "2031-06-12T08:00:00Z", end: "2031-06-12T08:45:00Z" };
const window = {
  start: new Date(2031, 5, 13, 9, 0).toISOString(),
  end: new Date(2031, 5, 13, 9, 45).toISOString(),
  window_end: new Date(2031, 5, 13, 12, 0).toISOString(),
};

describe("interview-pick", () => {
  it("rozpoznaje okno klienta tylko z końcem po końcu terminu", () => {
    expect(isWindow(fixed)).toBe(false);
    expect(isWindow(window)).toBe(true);
    expect(isWindow({ ...fixed, window_end: fixed.end })).toBe(false);
  });

  it("granice okna: najpóźniejszy start mieści całą rozmowę", () => {
    expect(windowBounds(window, 45)).toEqual({ from: "09:00", to: "11:15" });
    expect(windowBounds(fixed, 45)).toBeNull();
  });

  it("start rozmowy: zwykły termin bez zmian, okno z godziną, poza oknem null", () => {
    expect(interviewStart(fixed, "", 45)).toBe("2031-06-12T08:00:00.000Z");
    expect(interviewStart(window, "10:30", 45)).toBe(new Date(2031, 5, 13, 10, 30).toISOString());
    expect(interviewStart(window, "11:30", 45)).toBeNull();
    expect(interviewStart(window, "", 45)).toBeNull();
  });

  it("okno kandydata od–do", () => {
    expect(candidateWindowError("16:00", "15:00")).toMatch(/Koniec/);
    expect(candidateWindowError("16:00", "")).toBeNull();
  });
});
