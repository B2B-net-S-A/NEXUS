import { describe, expect, it } from "vitest";

import { waitingFor } from "@/lib/api/boardTasks";

// Runda 10 (R10-X1-5): dni kalendarzowe w Europe/Warsaw, nie pełne doby.
describe("waitingFor", () => {
  it("wczoraj o 17:00, dziś o 9:00 = od wczoraj", () => {
    expect(waitingFor("2026-09-26T15:00:00Z", new Date("2026-09-27T07:00:00Z"))).toBe(
      "od wczoraj",
    );
  });

  it("ten sam dzień w Warszawie = od dziś", () => {
    expect(waitingFor("2026-09-27T05:00:00Z", new Date("2026-09-27T20:00:00Z"))).toBe(
      "od dziś",
    );
  });

  it("23:30 UTC to już następny dzień w Warszawie", () => {
    // 26.09 23:30 UTC = 27.09 01:30 w Warszawie → dziś.
    expect(waitingFor("2026-09-26T23:30:00Z", new Date("2026-09-27T08:00:00Z"))).toBe(
      "od dziś",
    );
  });

  it("kilka dni kalendarzowych", () => {
    expect(waitingFor("2026-09-25T21:00:00Z", new Date("2026-09-27T06:00:00Z"))).toBe(
      "od 2 dni",
    );
  });

  it("przejście na czas zimowy nie gubi dnia", () => {
    expect(waitingFor("2026-10-24T10:00:00Z", new Date("2026-10-26T10:00:00Z"))).toBe(
      "od 2 dni",
    );
  });
});
