import { describe, expect, it } from "vitest";

import type { CandidateNotesFacts } from "@/lib/api";
import {
  contractTypesText,
  describeNotesRate,
  noticeText,
  notesAvailabilityText,
  notesWorkModeText,
} from "@/lib/notes-facts";

type Rate = NonNullable<CandidateNotesFacts["rate"]>;

function rate(overrides: Partial<Rate>): Rate {
  return {
    value: "1200",
    currency: "PLN",
    period: "md",
    raw: null,
    as_of: null,
    hourly_pln: "150.00",
    flexibility: null,
    profile_amount: null,
    profile_rate_version: 0,
    can_apply: true,
    ...overrides,
  };
}

describe("notes facts wording", () => {
  it("shows the hourly equivalent with the conversion that produced it", () => {
    const out = describeNotesRate(rate({}));
    expect(out.hourly).toBe("150 PLN netto/h");
    expect(out.original).toBe("1200 PLN / dzień (MD)");
    expect(out.conversion).toBe("stawka za dzień ÷ 8 h");
    expect(out.warning).toBeNull();
  });

  it("shows the server's reason first (monthly amount without B2B)", () => {
    const note = "Stawka miesięczna bez potwierdzonej formy B2B — sprawdź.";
    const out = describeNotesRate(
      rate({ value: "18000", period: "month", hourly_pln: null, note }),
    );
    expect(out.hourly).toBeNull();
    expect(out.warning).toBe(note);
  });

  it("explains why a rate cannot be converted", () => {
    expect(
      describeNotesRate(rate({ currency: "EUR", period: "h", hourly_pln: null })).warning,
    ).toMatch(/EUR/);
    expect(
      describeNotesRate(rate({ currency: null, hourly_pln: null })).warning,
    ).toMatch(/waluty/);
    expect(
      describeNotesRate(rate({ period: null, hourly_pln: null })).warning,
    ).toMatch(/godzinę, dzień czy miesiąc/);
  });

  it("describes work mode from notes and profile", () => {
    expect(
      notesWorkModeText({
        modes: ["remote", "hybrid"],
        max_onsite_days: 2,
        profile_modes: [],
        profile_max_onsite_days: null,
        can_apply: true,
      }),
    ).toEqual({
      notes: "Hybrydowo lub zdalnie · do 2 dni w biurze w tygodniu",
      profile: "nie uzupełniono",
    });
  });

  it("uses Polish plural forms for notice periods", () => {
    expect(noticeText(1, "months")).toBe("1 miesiąc wypowiedzenia");
    expect(noticeText(3, "months")).toBe("3 miesiące wypowiedzenia");
    expect(noticeText(5, "weeks")).toBe("5 tygodni wypowiedzenia");
    expect(noticeText(null, "days")).toBeNull();
  });

  it("prefers a parsed date, else quotes the note", () => {
    const base = {
      raw: "po zakończeniu projektu",
      notice_period_text: null,
      available_from_text: null,
      notice_period: null,
      notice_period_unit: null,
      available_from: null,
      profile_notice_period: 2,
      profile_notice_period_unit: "weeks",
      profile_availability_date: null,
      can_apply: false,
    };
    expect(notesAvailabilityText(base)).toEqual({
      notes: "po zakończeniu projektu",
      profile: "2 tygodnie wypowiedzenia",
    });
    expect(
      notesAvailabilityText({ ...base, available_from: "2026-11-01" }).notes,
    ).toBe("od 01.11.2026");
  });

  it("labels contract types", () => {
    expect(contractTypesText(["b2b", "uop"])).toBe("B2B, UoP");
    expect(contractTypesText([])).toBe("nie uzupełniono");
  });
});
