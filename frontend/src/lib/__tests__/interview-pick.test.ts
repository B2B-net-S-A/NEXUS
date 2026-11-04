import { describe, expect, it } from "vitest";

import {
  candidateWindowError,
  checkManualPrep,
  dayStrip,
  interviewStart,
  isWindow,
  nearestFreeStarts,
  prepDays,
  windowBounds,
  windowEarliest,
} from "@/lib/interview-pick";

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

  it("okno, które już trwa: najwcześniejszy start od teraz w górę do kwadransa (F36)", () => {
    expect(windowEarliest(window, 60, new Date(2031, 5, 13, 10, 15))).toBe("10:15");
    expect(windowEarliest(window, 60, new Date(2031, 5, 13, 10, 16))).toBe("10:30");
    // Okno jeszcze się nie zaczęło — od jego początku.
    expect(windowEarliest(window, 60, new Date(2031, 5, 12, 18, 0))).toBe("09:00");
    expect(windowEarliest(fixed, 60)).toBeNull();
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

  // ── „Inna godzina…” prepu (22.10.2026) ──
  // Rozmowa w piątek 13.06.2031 o 9:00, dziś poniedziałek 9.06, 10:00 (czas przeglądarki).
  const at = (d: number, h: number, m = 0) => new Date(2031, 5, d, h, m).toISOString();
  const NOW = new Date(2031, 5, 9, 10, 0);
  const INTERVIEW = at(13, 9);
  const busy = [
    { start: at(11, 10), end: at(11, 10, 30) },
    { start: at(11, 11, 30), end: at(11, 12) },
    { start: at(11, 12), end: at(11, 13) },
  ];
  const base = {
    prepNo: 1 as const,
    minutes: 45,
    interviewStart: INTERVIEW,
    busy,
    organizerName: "Ewa DL",
    other: null,
    now: NOW,
  };

  it("własna godzina na wolnym — bez blokad i ostrzeżeń", () => {
    expect(checkManualPrep({ ...base, start: at(11, 13, 15) })).toEqual({ blocks: [], warnings: [], busy: null });
  });

  it("zajęte u prowadzącego to ostrzeżenie z połączonym przedziałem, nie blokada", () => {
    const out = checkManualPrep({ ...base, start: at(11, 11, 45) });
    expect(out.blocks).toEqual([]);
    expect(out.warnings[0]).toBe("Ewa DL ma wtedy zajęte (11:30–13:00). Możesz zapisać, jeśli to uzgodnione.");
    expect(out.busy).toEqual({ start: at(11, 11, 30), end: at(11, 13) });
  });

  it("kalendarz niewidoczny = nie ma czym ostrzec", () => {
    expect(checkManualPrep({ ...base, busy: null, start: at(11, 11, 45) }).busy).toBeNull();
  });

  it("blokady: po rozmowie, na drugim prepie, w przeszłości", () => {
    expect(checkManualPrep({ ...base, start: at(13, 8, 30) }).blocks[0]).toMatch(/^Prep musi skończyć się przed rozmową/);
    const other = { start: at(12, 10), end: at(12, 10, 45), prepNo: 1 };
    expect(checkManualPrep({ ...base, prepNo: 2, other, start: at(12, 10, 30) }).blocks[0]).toMatch(
      /^W tym czasie jest Prep 1/,
    );
    expect(checkManualPrep({ ...base, start: at(9, 8) }).blocks).toEqual(["Ta godzina już minęła."]);
  });

  it("ostrzeżenia: za blisko rozmowy, poza godzinami pracy, za mniej niż 2 h", () => {
    // Prep 1 kończy się 8:15, rozmowa 9:00 — zapas 45 min zamiast 2 h.
    expect(checkManualPrep({ ...base, start: at(13, 7, 30) }).warnings).toContain(
      "Prep 1 kończy się 45 min przed rozmową — zwykle zostawiamy 2 h.",
    );
    // Prep 2 wolno 30 min przed — kończy się 8:30, bez ostrzeżenia o zapasie.
    expect(checkManualPrep({ ...base, prepNo: 2, start: at(13, 7, 45) }).warnings.join(" ")).not.toMatch(/zapas|zostawiamy/);
    expect(checkManualPrep({ ...base, start: at(11, 19) }).warnings).toContain("Poza godzinami pracy (8:00–18:00).");
    expect(checkManualPrep({ ...base, start: at(9, 11) }).warnings).toContain(
      "Prep za mniej niż 2 h — kandydat może nie zdążyć odebrać zaproszenia.",
    );
  });

  it("najbliższe wolne starty tego dnia omijają zajęte i drugi prep", () => {
    const near = nearestFreeStarts({
      day: "2031-06-11",
      around: at(11, 11, 45),
      minutes: 45,
      interviewStart: INTERVIEW,
      busy,
      other: null,
      now: NOW,
    });
    expect(near).toEqual([at(11, 10, 30), at(11, 13)]);
  });

  it("dni do wyboru: robocze od dziś do dnia rozmowy", () => {
    const days = prepDays(INTERVIEW, NOW);
    expect(days.map((d) => d.value)).toEqual(["2031-06-09", "2031-06-10", "2031-06-11", "2031-06-12", "2031-06-13"]);
    expect(days[0].label).toMatch(/\(dziś\)$/);
    expect(days[4].label).toMatch(/\(rozmowa\)$/);
  });

  it("pasek dnia: 8–18, poszerzony o prep po godzinach", () => {
    const strip = dayStrip("2031-06-11", [{ start: at(11, 10), end: at(11, 12) }], {
      start: at(11, 19),
      end: at(11, 19, 45),
    });
    expect(strip?.ticks[0].label).toBe("8:00");
    expect(strip?.ticks.at(-1)?.label).toBe("20:00");
    expect(strip?.busy[0].left).toBeCloseTo((120 / 720) * 100);
    expect(strip?.busy[0].width).toBeCloseTo((120 / 720) * 100);
    expect(strip?.chosen?.left).toBeCloseTo((660 / 720) * 100);
  });
});
