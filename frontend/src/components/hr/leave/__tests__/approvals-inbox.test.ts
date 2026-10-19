import { describe, expect, it } from "vitest";

import type { PendingLeaveRow } from "@/lib/api/hr-leave";
import type { TeamQueueItem } from "@/lib/api/hr-time";

import {
  agoLabel,
  dayMonthRange,
  inboxItems,
  termDays,
  termRows,
  timesheetSummary,
  timesheetSummaryText,
} from "../approvals-inbox";

function row(extra: Partial<PendingLeaveRow> = {}): PendingLeaveRow {
  return {
    id: "r1",
    user_id: 11,
    user_name: "Kamil Testowy",
    leave_type: "vacation",
    leave_type_label: "Urlop wypoczynkowy",
    status: "pending",
    start_date: "2026-11-25",
    end_date: "2026-11-27",
    half_day: null,
    days_total: "3.0",
    paid_days: "3.0",
    unpaid_days: "0.0",
    note: null,
    substitute_user_id: 21,
    substitute_name: "Ola Przykładowa",
    forward_mail_consent: false,
    oof_internal_message: null,
    oof_external_message: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    source: "self",
    created_at: "2026-10-21T09:00:00+02:00",
    can_cancel: false,
    department: "Delivery",
    manager_name: "Marta Fikcyjna",
    work_total: 0,
    work_by_kind: [],
    department_absent: [
      { user_id: 31, name: "Adam Wzorcowy", start_date: "2026-11-26", end_date: "2026-12-01" },
    ],
    ...extra,
  };
}

describe("skrzynka „Akceptacji”", () => {
  it("do decyzji: termin, dni, kolizja i załącznik; czas od złożenia", () => {
    const { decide, info } = inboxItems([row({ proof_count: 1 })], [], "2026-10-23");
    expect(info).toEqual([]);
    expect(decide[0].line).toBe("Urlop wypoczynkowy · 25–27.11.2026 · 3 dni");
    expect(decide[0].chips).toEqual([
      { tone: "warning", text: "kolizja: Adam 26.11–1.12" },
      { tone: "neutral", text: "załącznik ✓" },
    ]);
    expect(decide[0].waited).toBe("2 dni temu");
  });

  it("zastępca przełożonego przy L4: „do wiadomości”, „w zastępstwie za …”", () => {
    const { decide } = inboxItems(
      [row({ can_decide: false, as_substitute_for: "Kamil Testowy", department_absent: [] })],
      [],
      "2026-10-21",
    );
    expect(decide[0].chips).toEqual([
      { tone: "info", text: "w zastępstwie za Kamil" },
      { tone: "neutral", text: "do wiadomości" },
    ]);
    expect(decide[0].waited).toBe("dziś");
  });

  it("czas od złożenia: wczoraj i bez daty", () => {
    expect(agoLabel("2026-10-22T09:00:00+02:00", "2026-10-23")).toBe("wczoraj");
    expect(agoLabel(null, "2026-10-23")).toBeUndefined();
    expect(dayMonthRange("2026-11-12", "2026-11-12")).toBe("12.11");
  });
});

describe("mini-kalendarz „Zespół w tym terminie”", () => {
  it("dni robocze od poniedziałku do piątku tygodni terminu", () => {
    // 25.11.2026 to środa: tydzień 23–27.11.
    expect(termDays("2026-11-25", "2026-11-27")).toEqual([
      "2026-11-23",
      "2026-11-24",
      "2026-11-25",
      "2026-11-26",
      "2026-11-27",
    ]);
    expect(termDays("2026-11-27", "2026-12-02")).toHaveLength(10);
    // Długi termin ucięty do trzech tygodni.
    expect(termDays("2026-11-02", "2026-12-31")).toHaveLength(15);
  });

  it("osoba z wnioskiem (czeka) i nieobecni z działu — kolizja w tych samych kolumnach", () => {
    const days = termDays("2026-11-25", "2026-11-27");
    const rows = termRows(row(), days);
    expect(rows.map((line) => [line.name, line.self, line.cells])).toEqual([
      ["Kamil Testowy", true, ["none", "none", "pending", "pending", "pending"]],
      ["Adam Wzorcowy", false, ["none", "none", "none", "absent", "absent"]],
    ]);
    // Zgłoszenie z B2B (zatwierdzone od razu) — pełny pasek, nie przerywany.
    expect(termRows(row({ status: "approved", department_absent: [] }), days)[0].cells[2]).toBe(
      "absent",
    );
  });
});

describe("podsumowanie timesheetów", () => {
  const item = (status: TeamQueueItem["status"]): TeamQueueItem => ({
    user_id: 1,
    name: "Osoba",
    job_title: null,
    timesheet: null,
    status,
    hours: 0,
    overtime_hours: 0,
    absence_days: 0,
    can_decide: true,
  });

  it("liczby w stałej kolejności, bez pustych statusów", () => {
    const slices = timesheetSummary([
      item("submitted"),
      item("draft"),
      item("draft"),
      item("missing"),
      item("draft"),
    ]);
    expect(slices.map((slice) => [slice.status, slice.count])).toEqual([
      ["draft", 3],
      ["missing", 1],
      ["submitted", 1],
    ]);
    expect(timesheetSummaryText(slices)).toBe("3 szkic · 1 nie założony · 1 do akceptacji");
    expect(timesheetSummary([])).toEqual([]);
  });
});
