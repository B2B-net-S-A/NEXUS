import { describe, expect, it } from "vitest";

import { callPresets, callTone, callWhen, savedMessage, warsawInstant } from "@/lib/screening-call";

// Wtorek 3.11.2026, 13:00 w Warszawie (CET, UTC+1).
const NOW = new Date("2026-11-03T12:00:00Z");

describe("warsawInstant", () => {
  it("liczy zimą z przesunięciem +1 h", () => {
    expect(warsawInstant("2026-11-04", "16:00").toISOString()).toBe("2026-11-04T15:00:00.000Z");
  });

  it("liczy latem z przesunięciem +2 h", () => {
    expect(warsawInstant("2026-07-01", "09:00").toISOString()).toBe("2026-07-01T07:00:00.000Z");
  });
});

describe("callWhen", () => {
  it.each([
    ["2026-11-03T15:00:00Z", "dziś 16:00"],
    ["2026-11-04T08:30:00Z", "jutro 9:30"],
    ["2026-11-02T14:00:00Z", "wczoraj 15:00"],
    ["2026-11-05T09:00:00Z", "czw 10:00"],
    ["2026-11-12T09:00:00Z", "12.11 10:00"],
    ["2026-10-30T09:00:00Z", "30.10 10:00"],
  ])("%s → %s", (iso, label) => {
    expect(callWhen(iso, NOW)).toBe(label);
  });

  it("dzień liczy w kalendarzu firmy, nie w UTC", () => {
    // 23:30 UTC 3.11 to już 4.11 w Warszawie.
    expect(callWhen("2026-11-03T23:30:00Z", NOW)).toBe("jutro 0:30");
  });
});

describe("callTone", () => {
  it("rozróżnia zaległy, dzisiejszy i późniejszy", () => {
    expect(callTone("2026-11-03T11:59:00Z", NOW)).toBe("overdue");
    expect(callTone("2026-11-03T15:00:00Z", NOW)).toBe("today");
    expect(callTone("2026-11-04T08:00:00Z", NOW)).toBe("later");
  });
});

describe("callPresets", () => {
  it("w dzień pracy daje dziś i dwa kolejne dni", () => {
    expect(callPresets(NOW).map((p) => p.label)).toEqual([
      "Dziś 16:00",
      "Jutro 9:00",
      "Jutro 16:00",
      "Czw 9:00",
    ]);
  });

  it("po 15:30 nie proponuje już dzisiaj", () => {
    const late = new Date("2026-11-03T15:00:00Z");
    expect(callPresets(late).map((p) => p.label)[0]).toBe("Jutro 9:00");
  });

  it("w piątek przeskakuje weekend", () => {
    const friday = new Date("2026-11-06T12:00:00Z");
    expect(callPresets(friday).map((p) => p.label)).toEqual([
      "Dziś 16:00",
      "Pon 9:00",
      "Pon 16:00",
      "Wt 9:00",
    ]);
  });

  it("w sobotę nie proponuje dzisiaj", () => {
    const saturday = new Date("2026-11-07T09:00:00Z");
    expect(callPresets(saturday).map((p) => p.label)[0]).toBe("Pon 9:00");
  });

  it("niedzielny termin na jutro nazywa jutrem", () => {
    const sunday = new Date("2026-11-08T09:00:00Z");
    expect(callPresets(sunday).map((p) => p.label)[0]).toBe("Jutro 9:00");
  });
});

describe("savedMessage", () => {
  const saved = {
    event_id: 1,
    candidate_id: 2,
    job_id: 3,
    start_time: "2026-11-03T15:00:00Z",
    status: "scheduled",
  };

  it("mówi, gdy Outlook nie przyjął wpisu", () => {
    expect(savedMessage({ ...saved, outlook: "failed" }, NOW)).toContain("Outlook nie przyjął");
  });

  it("mówi, gdy wpis jest w Outlooku", () => {
    expect(savedMessage({ ...saved, outlook: "added" }, NOW)).toContain("także w Outlooku");
  });

  it("bez podłączonej skrzynki nie wspomina o Outlooku", () => {
    expect(savedMessage({ ...saved, outlook: "not_connected" }, NOW)).not.toContain("Outlook");
  });
});
