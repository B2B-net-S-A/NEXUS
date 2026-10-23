import { describe, expect, it } from "vitest";

import type { LeaveRequestRow, TeamCalendarPerson } from "@/lib/api/hr-leave";

import {
  FULL_DAY,
  NO_SUBSTITUTE,
  canEditRow,
  editChanges,
  editValuesFrom,
  matchesStatusFilter,
  presenceByDay,
  sourceBadge,
  historyCapNote,
  statusFilterLabel,
} from "../leave-format";
import { forwardStillAhead } from "@/lib/api/hr-m365";

const row = (overrides: Partial<LeaveRequestRow> = {}): LeaveRequestRow => ({
  id: "r1",
  user_id: 1,
  user_name: "Anna Przykładowa",
  leave_type: "vacation",
  leave_type_label: "Urlop wypoczynkowy",
  status: "approved",
  start_date: "2026-11-02",
  end_date: "2026-11-06",
  half_day: null,
  days_total: "5.0",
  paid_days: "5.0",
  unpaid_days: "0.0",
  note: null,
  substitute_user_id: 2,
  substitute_name: "Jan Testowy",
  forward_mail_consent: true,
  oof_internal_message: null,
  oof_external_message: null,
  decided_by_name: null,
  decided_at: null,
  decision_note: null,
  source: "self",
  created_at: null,
  can_cancel: false,
  ...overrides,
});

describe("plakietka źródła i liczniki statusów", () => {
  it("nazywa wpis za pracownika, Outlook i import; zwykły wniosek bez plakietki", () => {
    expect(sourceBadge("on_behalf")).toBe("Wpis za konsultanta/kontraktora");
    expect(sourceBadge("outlook_oof")).toBe("Z Outlooka");
    expect(sourceBadge("compass_import")).toBe("Import z Compassa");
    expect(sourceBadge("self")).toBeNull();
  });

  it("dokleja liczbę z serwera, a bez liczników zostawia samą etykietę", () => {
    const counts = { all: 9, pending: 3, approved: 5, rejected: 1, cancelled: 0 };
    expect(statusFilterLabel("Czeka na akceptację", "pending", counts)).toBe(
      "Czeka na akceptację (3)",
    );
    expect(statusFilterLabel("Anulowany", "cancelled", counts)).toBe("Anulowany (0)");
    expect(statusFilterLabel("Wszystkie statusy", "all", null)).toBe("Wszystkie statusy");
  });
});

describe("edycja wniosku przez przełożonego i Kadry", () => {
  it("bez zmian nie ma czego wysłać", () => {
    expect(editChanges(row(), editValuesFrom(row()))).toBeNull();
  });

  it("wysyła tylko zmienione pola; zastępcę można wyczyścić", () => {
    const values = { ...editValuesFrom(row()), end: "2026-11-04", substitute: NO_SUBSTITUTE };
    expect(editChanges(row(), values)).toEqual({
      end_date: "2026-11-04",
      substitute_user_id: null,
    });
  });

  it("pół dnia tylko przy jednym dniu — przy kilku dniach idzie „cały dzień”", () => {
    const half = row({ start_date: "2026-11-02", end_date: "2026-11-02", half_day: "morning" });
    const longer = { ...editValuesFrom(half), end: "2026-11-03" };
    expect(editChanges(half, longer)).toEqual({ end_date: "2026-11-03", half_day: null });
    const toHalf = { ...editValuesFrom(row()), end: "2026-11-02", halfDay: "afternoon" };
    expect(editChanges(row(), toHalf)).toEqual({
      end_date: "2026-11-02",
      half_day: "afternoon",
    });
    expect(editValuesFrom(row()).halfDay).toBe(FULL_DAY);
  });

  it("odwrócone daty blokują zapis", () => {
    expect(editChanges(row(), { ...editValuesFrom(row()), end: "2026-11-01" })).toBeNull();
  });

  it("zgłoszenie z B2B zmieniają tylko Kadry; zamknięty wniosek nikt", () => {
    expect(canEditRow(row({ is_report: true }), false)).toBe(false);
    expect(canEditRow(row({ is_report: true }), true)).toBe(true);
    expect(canEditRow(row({ status: "pending" }), false)).toBe(true);
    expect(canEditRow(row({ status: "rejected" }), true)).toBe(false);
  });
});

const person = (overrides: Partial<TeamCalendarPerson> = {}): TeamCalendarPerson => ({
  user_id: 1,
  name: "Anna Przykładowa",
  department: null,
  job_title: null,
  is_me: false,
  type_visible: false,
  absences: [],
  presence: [],
  ...overrides,
});

describe("kalendarz zespołu: zdalnie, wyjazd, filtr", () => {
  const NOVEMBER = { start: "2026-11-01", end: "2026-11-30" };

  it("dzień → wyjątek obecności", () => {
    const map = presenceByDay([
      { date: "2026-11-03", kind: "remote" },
      { date: "2026-11-04", kind: "business_trip" },
    ]);
    expect(map.get("2026-11-03")).toBe("remote");
    expect(map.get("2026-11-04")).toBe("business_trip");
    expect(presenceByDay(undefined).size).toBe(0);
  });

  it("w bieżącym miesiącu filtr patrzy na dziś, w innym — na cały miesiąc", () => {
    const remoteTomorrow = person({ presence: [{ date: "2026-11-04", kind: "remote" }] });
    expect(matchesStatusFilter(remoteTomorrow, "remote", "2026-11-03", NOVEMBER)).toBe(false);
    expect(matchesStatusFilter(remoteTomorrow, "remote", "2026-10-20", NOVEMBER)).toBe(true);
    expect(matchesStatusFilter(remoteTomorrow, "all", "2026-11-03", NOVEMBER)).toBe(true);
  });

  it("dwa tygodnie bez dzisiejszego dnia: liczy się tylko to, co nachodzi na okno (audyt 22.10, F13)", () => {
    const window = { start: "2026-11-02", end: "2026-11-15" };
    const absence = {
      id: null,
      half_day: null,
      label: "Nieobecność",
      leave_type: null,
      substitute_user_id: null,
      substitute_name: null,
      status: "approved" as const,
    };
    const later = person({ absences: [{ ...absence, start_date: "2026-11-20", end_date: "2026-11-21" }] });
    const across = person({ absences: [{ ...absence, start_date: "2026-10-30", end_date: "2026-11-02" }] });
    const remoteLater = person({ presence: [{ date: "2026-11-25", kind: "remote" }] });
    const remoteInside = person({ presence: [{ date: "2026-11-15", kind: "remote" }] });
    const tripLater = person({ presence: [{ date: "2026-11-16", kind: "business_trip" }] });
    expect(matchesStatusFilter(later, "absent", "2026-10-22", window)).toBe(false);
    expect(matchesStatusFilter(across, "absent", "2026-10-22", window)).toBe(true);
    expect(matchesStatusFilter(remoteLater, "remote", "2026-10-22", window)).toBe(false);
    expect(matchesStatusFilter(remoteInside, "remote", "2026-10-22", window)).toBe(true);
    expect(matchesStatusFilter(tripLater, "absent", "2026-10-22", window)).toBe(false);
  });

  it("nieobecni = zatwierdzona nieobecność albo delegacja; wniosek czekający się nie liczy", () => {
    const absence = {
      id: null,
      start_date: "2026-11-02",
      end_date: "2026-11-06",
      half_day: null,
      label: "Nieobecność",
      leave_type: null,
      substitute_user_id: null,
      substitute_name: null,
    };
    const away = person({ absences: [{ ...absence, status: "approved" }] });
    const waiting = person({ absences: [{ ...absence, status: "pending" }] });
    const trip = person({ presence: [{ date: "2026-11-03", kind: "business_trip" }] });
    expect(matchesStatusFilter(away, "absent", "2026-11-03", NOVEMBER)).toBe(true);
    expect(matchesStatusFilter(waiting, "absent", "2026-11-03", NOVEMBER)).toBe(false);
    expect(matchesStatusFilter(trip, "absent", "2026-11-03", NOVEMBER)).toBe(true);
    expect(matchesStatusFilter(trip, "remote", "2026-11-03", NOVEMBER)).toBe(false);
  });
});

describe("historia z limitem i przekierowanie po urlopie (audyt 19.10.2026)", () => {
  const counts = { all: 212, pending: 2, approved: 170, rejected: 10, cancelled: 30 };

  it("mówi, ile wniosków się nie zmieściło", () => {
    expect(historyCapNote(200, "all", counts)).toBe(
      "Pokazano 200 z 212 — najnowsze terminy. Wybierz osobę albo status, żeby zobaczyć starsze.",
    );
    expect(historyCapNote(30, "cancelled", counts)).toBeNull();
    expect(historyCapNote(0, "all", null)).toBeNull();
  });

  it("wyłączenie przekierowania tylko do końca urlopu", () => {
    expect(forwardStillAhead("2026-10-23", "2026-10-23")).toBe(true);
    expect(forwardStillAhead("2026-10-22", "2026-10-23")).toBe(false);
  });
});
