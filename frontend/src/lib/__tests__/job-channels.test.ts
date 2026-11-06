import { describe, expect, it } from "vitest";

import {
  boardChannelNotes,
  channelBuckets,
  parsePlanInput,
  planShortfall,
  sortByChannel,
} from "@/lib/job-channels";

const p = (id: number, channel: "base" | "linkedin" | null, proposed = false) => ({
  user_id: id,
  channel,
  proposed,
});

describe("koszyki Baza / LinkedIn", () => {
  it("dzieli pracujących na koszyki i pomija propozycje automatu", () => {
    const buckets = channelBuckets([p(1, "base"), p(2, "linkedin"), p(3, null), p(4, "base", true)]);
    expect(buckets.base.map((x) => x.user_id)).toEqual([1]);
    expect(buckets.linkedin.map((x) => x.user_id)).toEqual([2]);
    expect(buckets.none.map((x) => x.user_id)).toEqual([3]);
  });

  it("brak do planu: tylko przy planie, nigdy ujemny", () => {
    expect(planShortfall(null, 0)).toBe(0);
    expect(planShortfall(2, 1)).toBe(1);
    expect(planShortfall(1, 3)).toBe(0);
    expect(planShortfall(0, 0)).toBe(0);
  });

  it("pole planu: puste = bez planu, 0–20 = liczba, reszta = błąd", () => {
    expect(parsePlanInput("")).toBeNull();
    expect(parsePlanInput(" 3 ")).toBe(3);
    expect(parsePlanInput("0")).toBe(0);
    expect(parsePlanInput("20")).toBe(20);
    expect(parsePlanInput("21")).toBe("invalid");
    expect(parsePlanInput("-1")).toBe("invalid");
    expect(parsePlanInput("1.5")).toBe("invalid");
    expect(parsePlanInput("dwa")).toBe("invalid");
  });

  it("kolejność: Baza, LinkedIn, bez koszyka — w obrębie koszyka jak z serwera", () => {
    const sorted = sortByChannel([p(1, null), p(2, "linkedin"), p(3, "base"), p(4, "base")]);
    expect(sorted.map((x) => x.user_id)).toEqual([3, 4, 2, 1]);
  });

  it("ostrzeżenia wiersza pulpitu: brak do planu, bez koszyka, bez przypisania", () => {
    expect(
      boardChannelNotes({
        people: [p(1, "base"), p(2, null), p(3, null)],
        channel_plan_base: 1,
        channel_plan_linkedin: 1,
        unassigned_workers: [{}, {}, {}, {}, {}],
      }),
    ).toEqual(["LinkedIn: brakuje 1 z 1", "bez koszyka: 2 osoby", "bez przypisania: 5 osób"]);
  });

  it("request z championem nie ostrzega — nikt już nie szuka", () => {
    expect(
      boardChannelNotes({
        champion: true,
        people: [p(1, null)],
        channel_plan_linkedin: 2,
        unassigned_workers: [{}],
      }),
    ).toEqual([]);
  });

  it("starszy serwer bez pól koszyków: tylko osoby bez koszyka", () => {
    expect(boardChannelNotes({ people: [p(1, null)] })).toEqual(["bez koszyka: 1 osoba"]);
  });
});
