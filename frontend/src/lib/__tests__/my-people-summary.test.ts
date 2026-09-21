import { describe, expect, it } from "vitest";

import type { MyPeopleRow, MyPeopleSummary } from "@/lib/api/myPeople";
import {
  daysAgoLabel,
  groupByCategory,
  matchesQuery,
  splitPeople,
  summarySentences,
  UNCATEGORIZED_LABEL,
} from "@/lib/my-people-summary";

function row(o: Partial<MyPeopleRow>): MyPeopleRow {
  return {
    candidate_id: 1,
    full_name: "Anna Test",
    category_id: null,
    furthest_stage: "cv_sent",
    last_sent_at: null,
    last_sent_job_title: null,
    last_sent_client_name: null,
    sent_count: 1,
    days_since_last_send: null,
    expected_rate_hourly: null,
    availability_status: null,
    city: null,
    source: "auto",
    active_processes: 0,
    working: false,
    snoozed: false,
    snooze_reason: null,
    snoozed_at: null,
    new_matches: 0,
    ...o,
  };
}

const summary = (o: Partial<MyPeopleSummary>): MyPeopleSummary => ({
  total: 0,
  new_matches: 0,
  jobs_with_matches: 0,
  latest_matches: [],
  idle_count: 0,
  idle_top: [],
  idle_days: 30,
  ...o,
});

describe("groupByCategory", () => {
  const cats = [
    { id: 1, name_pl: "Infra" },
    { id: 2, name_pl: "Dev" },
  ];

  it("keeps catalog order, puts unknown and missing categories last as „Pozostałe”", () => {
    const groups = groupByCategory(
      [
        row({ candidate_id: 1, category_id: 2 }),
        row({ candidate_id: 2, category_id: 1 }),
        row({ candidate_id: 3, category_id: null }),
        row({ candidate_id: 4, category_id: 99 }),
      ],
      cats,
    );
    expect(groups.map((g) => g.label)).toEqual(["Infra", "Dev", UNCATEGORIZED_LABEL]);
    expect(groups[2].rows.map((r) => r.candidate_id)).toEqual([3, 4]);
  });

  it("does not render empty categories", () => {
    expect(groupByCategory([row({ category_id: 2 })], cats).map((g) => g.label)).toEqual(["Dev"]);
  });
});

describe("splitPeople", () => {
  it("snoozed wins over working; active is the rest", () => {
    const s = splitPeople([
      row({ candidate_id: 1 }),
      row({ candidate_id: 2, working: true }),
      row({ candidate_id: 3, working: true, snoozed: true }),
    ]);
    expect(s.active.map((r) => r.candidate_id)).toEqual([1]);
    expect(s.working.map((r) => r.candidate_id)).toEqual([2]);
    expect(s.snoozed.map((r) => r.candidate_id)).toEqual([3]);
  });
});

describe("summarySentences", () => {
  it("stays silent when there is nothing concrete to say", () => {
    expect(summarySentences(summary({}))).toEqual([]);
    expect(summarySentences(undefined)).toEqual([]);
  });

  it("names new matches with correct Polish plurals", () => {
    const [first, second] = summarySentences(
      summary({
        new_matches: 5,
        jobs_with_matches: 2,
        latest_matches: [
          { job_id: 1, job_title: "Java", candidate_id: 1, full_name: "Anna Test", score: 80, created_at: "" },
        ],
      }),
    );
    expect(first).toBe("2 nowe rekrutacje pasują do 5 osób z Twojej listy.");
    expect(second).toBe("Na przykład Anna Test → „Java”.");
    expect(summarySentences(summary({ new_matches: 1, jobs_with_matches: 1 }))[0]).toBe(
      "1 nowa rekrutacja pasuje do 1 osoby z Twojej listy.",
    );
  });

  it("mentions the idle person and how many more are waiting", () => {
    const [s] = summarySentences(
      summary({
        idle_count: 3,
        idle_top: [{ candidate_id: 1, full_name: "Ola Test", days_since_last_send: 34 }],
      }),
    );
    expect(s).toBe("Ola Test czeka 34 dni bez wysyłki — i jeszcze 2 osoby.");
  });
});

describe("helpers", () => {
  it("daysAgoLabel", () => {
    expect(daysAgoLabel(null)).toBeNull();
    expect(daysAgoLabel(0)).toBe("dziś");
    expect(daysAgoLabel(1)).toBe("wczoraj");
    expect(daysAgoLabel(5)).toBe("5 dni temu");
  });

  it("matchesQuery searches name, client and city without case", () => {
    const r = row({ full_name: "Łukasz Nowak", last_sent_client_name: "Bank Alfa", city: "Gdańsk" });
    expect(matchesQuery(r, "łukasz")).toBe(true);
    expect(matchesQuery(r, "ALFA")).toBe(true);
    expect(matchesQuery(r, "gdańsk")).toBe(true);
    expect(matchesQuery(r, "Kraków")).toBe(false);
    expect(matchesQuery(r, "  ")).toBe(true);
  });
});
