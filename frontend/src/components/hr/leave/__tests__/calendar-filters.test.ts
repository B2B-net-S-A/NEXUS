/**
 * Adres „Ludzie → Kalendarz” (22.10.2026): domyślny zakres zależy od tego,
 * czy oglądający ma zespół; w adresie tylko to, co różni się od domyślnego.
 */
import { describe, expect, it } from "vitest";

import {
  filtersFromParams,
  filtersHref,
  inScope,
  matchesPerson,
  type CalendarFilters,
} from "../calendar-filters";

const TODAY = "2026-10-22";
const at = (search: string) => new URLSearchParams(search);
const loc = (search = "") => ({ pathname: "/people/calendar", search });

describe("filtersFromParams", () => {
  it("domyślnie: koordynator „Mój zespół”, reszta „Wszyscy”, bieżący miesiąc", () => {
    expect(filtersFromParams(at(""), { isManager: true, today: TODAY })).toEqual({
      scope: "team",
      status: null,
      query: "",
      view: "month",
      anchor: "2026-10-01",
    });
    expect(filtersFromParams(at(""), { isManager: false, today: TODAY }).scope).toBe("all");
  });

  it("„Mój zespół” u kogoś bez zespołu = „Wszyscy”; dział wygrywa z zakresem", () => {
    expect(filtersFromParams(at("?scope=team"), { isManager: false, today: TODAY }).scope).toBe("all");
    expect(
      filtersFromParams(at("?scope=all&dept=Delivery"), { isManager: true, today: TODAY }).scope,
    ).toBe("dept:Delivery");
  });

  it("złe wartości wracają do domyślnych", () => {
    const filters = filtersFromParams(at("?status=urlop&view=rok&month=2026-13"), {
      isManager: false,
      today: TODAY,
    });
    expect(filters).toMatchObject({ status: null, view: "month", anchor: "2026-10-01" });
    expect(
      filtersFromParams(at("?view=two_weeks&from=2026-02-31x"), { isManager: false, today: TODAY })
        .anchor,
    ).toBe(TODAY);
  });
});

describe("filtersHref", () => {
  const base: CalendarFilters = {
    scope: "team",
    status: null,
    query: "",
    view: "month",
    anchor: "2026-10-01",
  };

  it("domyślny widok = sama ścieżka; obce parametry (harness) zostają", () => {
    expect(filtersHref(base, { isManager: true, today: TODAY }, loc())).toBe("/people/calendar");
    expect(filtersHref(base, { isManager: true, today: TODAY }, loc("?as=manager&q=x"))).toBe(
      "?as=manager",
    );
  });

  it("zapis i odczyt dają ten sam stan", () => {
    const defaults = { isManager: true, today: TODAY };
    const filters: CalendarFilters = {
      scope: "dept:Rekrutacja IT",
      status: "absent",
      query: "ola",
      view: "two_weeks",
      anchor: "2026-11-09",
    };
    const href = filtersHref(filters, defaults, loc());
    expect(href).toBe("?dept=Rekrutacja+IT&status=absent&q=ola&view=two_weeks&from=2026-11-09");
    expect(filtersFromParams(at(href), defaults)).toEqual(filters);
    expect(filtersHref({ ...base, scope: "all", anchor: "2026-12-01" }, defaults, loc())).toBe(
      "?scope=all&month=2026-12",
    );
  });
});

describe("matchesPerson / inScope", () => {
  const people = [
    { user_id: 1, name: "Ewa Makietowa", job_title: "Rekruterka", department: "Rekrutacja", is_me: false, type_visible: false, absences: [] },
    { user_id: 2, name: "Kamil Testowy", job_title: null, department: "Delivery", is_me: false, type_visible: false, absences: [] },
  ];

  it("szuka po imieniu i stanowisku, bez polskich znaków", () => {
    expect(matchesPerson(people[0], "rekruter")).toBe(true);
    expect(matchesPerson(people[0], "makiet")).toBe(true);
    expect(matchesPerson(people[1], "rekruter")).toBe(false);
  });

  it("dział zawęża, „Wszyscy” i „Mój zespół” nie", () => {
    expect(inScope(people, "dept:Delivery").map((p) => p.user_id)).toEqual([2]);
    expect(inScope(people, "all")).toHaveLength(2);
  });
});
