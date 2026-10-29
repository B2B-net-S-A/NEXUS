import { describe, expect, it } from "vitest";

import type { CalendarAbsence } from "@/lib/api/hr-leave";

import {
  absenceBadgeText,
  calendarCells,
  cproSubstituteMissing,
  daysLabel,
  formatRange,
  leaveInputFrom,
  shortName,
  validRange,
  type LeaveFormValues,
} from "../leave-format";

describe("daty urlopów", () => {

  it("zakres dat po polsku", () => {
    expect(formatRange("2026-12-23", "2026-12-31")).toBe("23–31.12.2026");
    expect(formatRange("2026-10-28", "2026-11-03")).toBe("28.10–03.11.2026");
    expect(formatRange("2026-12-29", "2027-01-04")).toBe("29.12.2026–04.01.2027");
    expect(formatRange("2026-11-14", "2026-11-14")).toBe("14.11.2026");
  });

  it("poprawny zakres włącza podgląd", () => {
    expect(validRange("2026-11-02", "2026-11-02")).toBe(true);
    expect(validRange("2026-11-03", "2026-11-02")).toBe(false);
    expect(validRange("", "2026-11-02")).toBe(false);
  });
});

describe("dni i osoby", () => {
  it("polskie formy liczby dni", () => {
    expect(daysLabel("1.0")).toBe("1 dzień");
    expect(daysLabel("5.0")).toBe("5 dni");
    expect(daysLabel("0.5")).toBe("0,5 dnia");
    expect(daysLabel("2.5")).toBe("2,5 dnia");
  });

  it("skrót nazwiska do plakietki", () => {
    expect(shortName("Anna Przykładowa")).toBe("Anna P.");
    expect(shortName("Jan")).toBe("Jan");
    expect(shortName(null)).toBe("");
  });
});

describe("plakietka nieobecności (D6: bez rodzaju)", () => {
  it("mówi do kiedy i kto zastępuje", () => {
    expect(
      absenceBadgeText(
        { until: "2026-10-24", half_day: null, substitute_name: "Anna Przykładowa" },
        "2026-10-20",
      ),
    ).toBe("Nieobecność do 24.10 · zastępuje Anna P.");
    expect(
      absenceBadgeText({ until: "2026-10-20", half_day: "morning", substitute_name: null }, "2026-10-20"),
    ).toBe("Nieobecność dziś (pół dnia)");
  });
});

describe("komórki kalendarza", () => {
  const absence = (overrides: Partial<CalendarAbsence>): CalendarAbsence => ({
    id: null,
    start_date: "2026-11-03",
    end_date: "2026-11-04",
    half_day: null,
    status: "approved",
    label: "Nieobecność",
    leave_type: null,
    substitute_user_id: null,
    substitute_name: null,
    ...overrides,
  });

  it("zatwierdzona nieobecność wygrywa z oczekującą, pół dnia jest połówką", () => {
    const days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"];
    const cells = calendarCells(
      [
        absence({ status: "pending", start_date: "2026-11-04", end_date: "2026-11-05" }),
        absence({}),
        absence({ start_date: "2026-11-02", end_date: "2026-11-02", half_day: "morning" }),
      ],
      days,
    );
    expect(cells.get("2026-11-02")).toMatchObject({ kind: "absent", half: true });
    expect(cells.get("2026-11-03")).toMatchObject({ kind: "absent", half: false });
    expect(cells.get("2026-11-04")).toMatchObject({ kind: "absent" });
    expect(cells.get("2026-11-05")).toMatchObject({ kind: "pending" });
  });

  it("nieobecność spoza miesiąca nie dokłada komórek", () => {
    const cells = calendarCells(
      [absence({ start_date: "2026-10-28", end_date: "2026-11-02" })],
      ["2026-11-02", "2026-11-03"],
    );
    expect(cells.get("2026-11-02")?.kind).toBe("absent");
    expect(cells.get("2026-11-03")?.kind).toBe("none");
    expect(cells.size).toBe(2);
  });
});

describe("leaveToast — zmiana urlopu w zamkniętym miesiącu płac", () => {
  it("bez ostrzeżenia zwykły sukces", async () => {
    const { leaveToast } = await import("../leave-format");
    expect(leaveToast("Wniosek zaakceptowany", { payroll_warning: null })).toEqual([
      "Wniosek zaakceptowany",
      "success",
    ]);
    expect(leaveToast("Wniosek anulowany")).toEqual(["Wniosek anulowany", "success"]);
  });

  it("z ostrzeżeniem doklejone zdanie i typ „info”", async () => {
    const { leaveToast } = await import("../leave-format");
    expect(
      leaveToast("Wniosek zaakceptowany", {
        payroll_warning: "Miesiąc 2031-03 jest zamknięty w Płacach — dostały informację.",
      }),
    ).toEqual([
      "Wniosek zaakceptowany. Miesiąc 2031-03 jest zamknięty w Płacach — dostały informację.",
      "info",
    ]);
  });
});

describe("leaveInputFrom — dane wniosku ze stanu okna", () => {
  const values = (overrides: Partial<LeaveFormValues> = {}): LeaveFormValues => ({
    leaveType: "vacation",
    start: "2026-11-02",
    end: "2026-11-02",
    halfDay: "full",
    substitute: "none",
    note: "",
    forward: false,
    oofInternal: "",
    oofExternal: "",
    ...overrides,
  });

  it("niepełne albo odwrócone daty = brak danych", () => {
    expect(leaveInputFrom(values({ start: "" }), "preview")).toBeNull();
    expect(leaveInputFrom(values({ end: "2026-11-01" }), "self")).toBeNull();
    expect(leaveInputFrom(values({ end: "2026-11-01" }), "on_behalf")).toBeNull();
  });

  it("pół dnia tylko przy jednym dniu; cały dzień = null", () => {
    expect(leaveInputFrom(values({ halfDay: "morning" }), "preview")?.half_day).toBe("morning");
    expect(leaveInputFrom(values({ halfDay: "afternoon" }), "self")?.half_day).toBe("afternoon");
    expect(leaveInputFrom(values({ halfDay: "full" }), "preview")?.half_day).toBeNull();
    expect(
      leaveInputFrom(values({ halfDay: "morning", end: "2026-11-04" }), "preview")?.half_day,
    ).toBeNull();
  });

  it("podgląd: rodzaj, daty, pół dnia i zastępca — bez notatki i OOF", () => {
    expect(
      leaveInputFrom(
        values({ leaveType: "on_demand", substitute: "5", note: "Wyjazd", oofInternal: "Wracam" }),
        "preview",
      ),
    ).toStrictEqual({
      leave_type: "on_demand",
      start_date: "2026-11-02",
      end_date: "2026-11-02",
      half_day: null,
      substitute_user_id: 5,
    });
    expect(leaveInputFrom(values(), "preview")?.substitute_user_id).toBeNull();
  });

  it("własny wniosek: notatka i OOF przycięte, puste = null, zgoda na przekierowanie tylko z zastępcą", () => {
    expect(
      leaveInputFrom(
        values({
          substitute: "5",
          note: "  Wyjazd rodzinny ",
          forward: true,
          oofInternal: " Wracam 3.11. ",
          oofExternal: "   ",
        }),
        "self",
      ),
    ).toStrictEqual({
      leave_type: "vacation",
      start_date: "2026-11-02",
      end_date: "2026-11-02",
      half_day: null,
      substitute_user_id: 5,
      note: "Wyjazd rodzinny",
      forward_mail_consent: true,
      oof_internal_message: "Wracam 3.11.",
      oof_external_message: null,
    });
    const withoutSubstitute = leaveInputFrom(values({ forward: true, note: "  " }), "self");
    expect(withoutSubstitute?.forward_mail_consent).toBe(false);
    expect(withoutSubstitute?.note).toBeNull();
  });

  it("wpis za pracownika: notatka bez zgody na przekierowanie i bez OOF", () => {
    expect(
      leaveInputFrom(
        values({
          leaveType: "sick_leave",
          end: "2026-11-04",
          substitute: "5",
          note: "Zwolnienie od lekarza",
          forward: true,
          oofInternal: "Wracam",
          oofExternal: "Back soon",
        }),
        "on_behalf",
      ),
    ).toStrictEqual({
      leave_type: "sick_leave",
      start_date: "2026-11-02",
      end_date: "2026-11-04",
      half_day: null,
      substitute_user_id: 5,
      note: "Zwolnienie od lekarza",
    });
    expect(leaveInputFrom(values(), "on_behalf")?.note).toBeNull();
  });
});

describe("cproSubstituteMissing — osoba od Cpro wskazuje zastępcę do Cpro", () => {
  const form = { start: "2026-11-02", end: "2026-11-03", halfDay: "full", cproSubstitute: "none" };

  it("własny wniosek osoby od Cpro na pełne dni bez wyboru = brak", () => {
    expect(cproSubstituteMissing(form, true, false)).toBe(true);
    expect(cproSubstituteMissing({ ...form, cproSubstitute: undefined }, true, false)).toBe(true);
    expect(cproSubstituteMissing({ ...form, cproSubstitute: "9" }, true, false)).toBe(false);
  });

  it("pół dnia, wpis za pracownika i zwykła osoba nie wymagają wyboru", () => {
    const half = { ...form, end: form.start, halfDay: "morning" };
    expect(cproSubstituteMissing(half, true, false)).toBe(false);
    expect(cproSubstituteMissing(form, true, true)).toBe(false);
    expect(cproSubstituteMissing(form, false, false)).toBe(false);
    expect(cproSubstituteMissing(form, undefined, false)).toBe(false);
    // „Pół dnia” przy kilku dniach się nie liczy — to pełne dni.
    expect(cproSubstituteMissing({ ...form, halfDay: "morning" }, true, false)).toBe(true);
  });
});
