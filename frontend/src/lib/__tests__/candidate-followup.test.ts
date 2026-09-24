import { describe, expect, it } from "vitest";

import type { FollowupRow } from "@/lib/api/candidateFollowups";
import {
  addDaysIso,
  callerReasonSentence,
  cardBadgeLabel,
  followupDueLabel,
  lastContactLabel,
  nextStepSentence,
  processChipLabel,
  shortDate,
  shortPersonName,
  todayInBusinessTz,
} from "@/lib/candidate-followup";

function row(extra: Partial<FollowupRow> = {}): FollowupRow {
  return {
    candidate_id: 1,
    candidate_name: "Jan Wiśniewski",
    phone: "600 214 390",
    due_on: "2026-09-22",
    state: "overdue",
    overdue_days: 2,
    caller_id: 3,
    caller_name: "Anna Kowalczyk",
    caller_reason: "furthest",
    processes: [
      {
        job_id: 10,
        job_title: "Backend Java",
        client_name: "PKO BP",
        column: "client_interview",
        stage_name: "Po Interview",
        sent_at: "2026-09-01T08:00:00Z",
        silent_since: "2026-09-09T08:00:00Z",
        silent_days: 11,
        owner_id: 3,
        owner_name: "Anna Kowalczyk",
      },
    ],
    last_contact_at: "2026-09-08T10:00:00Z",
    last_contact_by: "Anna Kowalczyk",
    last_contact_kind: "note",
    no_answer_count: 0,
    pending: null,
    ...extra,
  };
}

describe("follow-up z kandydatem — etykiety (0372)", () => {
  it("termin: zaległy z poprawną liczbą mnogą, dziś, jutro, data", () => {
    expect(followupDueLabel(row())).toBe("zaległy 2 dni");
    expect(followupDueLabel(row({ overdue_days: 1 }))).toBe("zaległy 1 dzień");
    expect(followupDueLabel(row({ state: "today" }))).toBe("dziś");
    expect(followupDueLabel(row({ state: "tomorrow" }))).toBe("jutro");
    expect(followupDueLabel(row({ state: "scheduled", due_on: "2026-10-08" }))).toBe("08.10");
  });

  it("chip procesu mówi, u kogo i od ilu dni klient milczy", () => {
    expect(processChipLabel(row().processes[0])).toBe("PKO BP · po rozmowie u klienta, 11 dni");
  });

  it("ostatni kontakt w czasie polskim, z osobą i rodzajem", () => {
    expect(lastContactLabel(row())).toBe("Ostatni kontakt 08.09 (Anna K., notatka)");
    expect(lastContactLabel(row({ last_contact_at: null }))).toBe("Brak kontaktu od wysłania CV");
    // 23:30 UTC 30.09 to już 1.10 w Warszawie.
    expect(shortDate("2026-09-30T23:30:00Z")).toBe("01.10");
  });

  it("powód dzwoniącego wskazuje najdalszy proces", () => {
    expect(callerReasonSentence(row())).toBe(
      "prowadzi proces, który zaszedł najdalej (PKO BP, po rozmowie u klienta)",
    );
    expect(callerReasonSentence(row({ caller_reason: "claim" }))).toBe("przejął(a) tę rundę");
  });

  it("plakietka karty: „Ty”, skrót imienia, brak opiekuna", () => {
    const badge = { ...row(), caller_id: 3 };
    expect(cardBadgeLabel(badge, 3)).toBe("Follow-up: Ty · zaległy 2 dni");
    expect(cardBadgeLabel(badge, 9)).toBe("Follow-up: Anna K. · zaległy 2 dni");
    expect(cardBadgeLabel({ ...badge, caller_id: null }, 9)).toBe(
      "Follow-up: brak opiekuna · zaległy 2 dni",
    );
    expect(shortPersonName("Cher")).toBe("Cher");
  });

  it("zdanie o następnym kroku i daty pola „oddzwoń”", () => {
    expect(nextStepSentence("no_answer", null)).toContain("2 dni robocze");
    expect(nextStepSentence("callback", "2026-09-29")).toBe("Przypomnimy 29.09.");
    expect(addDaysIso("2026-12-20", 60)).toBe("2027-02-18");
    expect(todayInBusinessTz(new Date("2026-09-30T23:30:00Z"))).toBe("2026-10-01");
  });
});
