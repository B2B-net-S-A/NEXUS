import { describe, expect, it } from "vitest";

import {
  availabilityDraft,
  availabilityDraftError,
  availabilityPatch,
} from "@/lib/candidate-availability-edit";

describe("availabilityDraft", () => {
  it("reads the profile fields and fills defaults", () => {
    expect(
      availabilityDraft({
        availability_status: "actively_looking",
        availability_date: "2026-10-15T00:00:00Z",
        notice_period: 30,
        notice_period_unit: "days",
      }),
    ).toEqual({
      status: "actively_looking",
      date: "2026-10-15",
      noticePeriod: "30",
      noticeUnit: "days",
    });
    expect(availabilityDraft({})).toEqual({
      status: "unknown",
      date: "",
      noticePeriod: "",
      noticeUnit: "days",
    });
  });
});

describe("availabilityPatch", () => {
  const initial = availabilityDraft({
    availability_status: "open_to_offers",
    availability_date: "2026-10-15",
    notice_period: 1,
    notice_period_unit: "months",
  });

  it("sends nothing when nothing changed", () => {
    expect(availabilityPatch(initial, { ...initial })).toEqual({});
  });

  it("sends only the changed field", () => {
    expect(
      availabilityPatch(initial, { ...initial, status: "actively_looking" }),
    ).toEqual({ availability_status: "actively_looking" });
    expect(availabilityPatch(initial, { ...initial, date: "" })).toEqual({
      availability_date: null,
    });
  });

  it("sends the notice period and its unit together", () => {
    expect(availabilityPatch(initial, { ...initial, noticeUnit: "weeks" })).toEqual({
      notice_period: 1,
      notice_period_unit: "weeks",
    });
    expect(availabilityPatch(initial, { ...initial, noticePeriod: "" })).toEqual({
      notice_period: null,
      notice_period_unit: null,
    });
  });

  it("ignores a unit change when there is no notice period", () => {
    const empty = availabilityDraft({});
    expect(availabilityPatch(empty, { ...empty, noticeUnit: "weeks" })).toEqual({});
  });
});

describe("availabilityDraftError", () => {
  it("accepts an empty or whole-number notice period", () => {
    expect(availabilityDraftError(availabilityDraft({}))).toBeNull();
    expect(
      availabilityDraftError({ ...availabilityDraft({}), noticePeriod: "30" }),
    ).toBeNull();
  });

  it("rejects fractions, text and absurd values", () => {
    const base = availabilityDraft({});
    expect(availabilityDraftError({ ...base, noticePeriod: "1.5" })).toMatch(/liczba/);
    expect(availabilityDraftError({ ...base, noticePeriod: "miesiąc" })).toMatch(/liczba/);
    expect(availabilityDraftError({ ...base, noticePeriod: "999" })).toMatch(/365/);
  });
});
