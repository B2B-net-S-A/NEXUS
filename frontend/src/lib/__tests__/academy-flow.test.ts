import { describe, expect, it } from "vitest";

import {
  awaitingLuna,
  bookableSessions,
  callQueue,
  cohortLabel,
  editionStats,
  lunaSkipped,
  nextCohort,
  sessionLabel,
  taskOverdue,
  toIsoDate,
} from "@/lib/academy-flow";
import type { AcademyApplication, AcademySessionRow } from "@/lib/api/academy";

function app(overrides: Partial<AcademyApplication>): AcademyApplication {
  return {
    id: 1,
    candidate_id: 1,
    full_name: "Anna Przykładowa",
    email: null,
    phone: "600100200",
    city: null,
    has_cv: true,
    source_job_id: 1,
    source_job_title: "Akademia Rekrutera",
    applied_at: "2026-09-20T10:00:00Z",
    status: "to_call",
    screening_verdict: "call",
    screening_reasons: [],
    screening_facts: {},
    screened_at: null,
    experience_years: 1,
    call_attempts: 0,
    last_call_at: null,
    session_id: null,
    session_starts_at: null,
    attended: null,
    task_due: null,
    task_result: null,
    contract_sent_at: null,
    signed_at: null,
    cohort_month: null,
    closed_stage: null,
    closed_reason: null,
    closed_at: null,
    reapplied_at: null,
    note: null,
    updated_at: "2026-09-20T10:00:00Z",
    ...overrides,
  };
}

function session(overrides: Partial<AcademySessionRow>): AcademySessionRow {
  return {
    id: 1,
    starts_at: "2026-09-29T08:00:00Z",
    location: null,
    capacity: 8,
    taken: 0,
    people: 0,
    cancelled: false,
    ...overrides,
  };
}

describe("academy-flow", () => {
  it("edycja startuje 1. dnia następnego miesiąca", () => {
    expect(toIsoDate(nextCohort(new Date(2026, 8, 24)))).toBe("2026-10-01");
    expect(toIsoDate(nextCohort(new Date(2026, 11, 31)))).toBe("2027-01-01");
    expect(cohortLabel("2026-11-01")).toBe("listopad 2026");
    expect(cohortLabel(null)).toBe("—");
  });

  it("kolejka: najpierw „Dzwonimy”, potem „Do decyzji”; nieodebrani na koniec grupy", () => {
    const queue = callQueue([
      app({ id: 1, screening_verdict: "review", applied_at: "2026-09-01T00:00:00Z" }),
      app({ id: 2, call_attempts: 1, applied_at: "2026-09-02T00:00:00Z" }),
      app({ id: 3, applied_at: "2026-09-10T00:00:00Z" }),
      app({ id: 4, status: "scheduled" }),
    ]);
    expect(queue.map((a) => a.id)).toEqual([3, 2, 1]);
  });

  it("odłożeni przez Lunę czekają na człowieka, a nieposortowani są liczeni osobno", () => {
    const apps = [
      app({ id: 1, status: "new", screening_verdict: "skip" }),
      app({ id: 2, status: "new", screening_verdict: null }),
      app({ id: 3, status: "rejected", screening_verdict: "skip", closed_reason: "x" }),
    ];
    expect(lunaSkipped(apps).map((a) => a.id)).toEqual([1]);
    expect(awaitingLuna(apps)).toBe(1);
  });

  it("do zapisu tylko przyszłe, nieodwołane terminy w kolejności", () => {
    const now = new Date("2026-09-24T10:00:00Z");
    const result = bookableSessions(
      [
        session({ id: 1, starts_at: "2026-09-30T08:00:00Z" }),
        session({ id: 2, starts_at: "2026-09-20T08:00:00Z" }),
        session({ id: 3, starts_at: "2026-09-25T08:00:00Z", cancelled: true }),
        session({ id: 4, starts_at: "2026-09-26T08:00:00Z" }),
      ],
      now,
    );
    expect(result.map((s) => s.id)).toEqual([4, 1]);
  });

  it("zadanie po terminie", () => {
    const today = new Date(2026, 8, 24);
    expect(taskOverdue(app({ status: "task_given", task_due: "2026-09-23" }), today)).toBe(true);
    expect(taskOverdue(app({ status: "task_given", task_due: "2026-09-24" }), today)).toBe(false);
    expect(taskOverdue(app({ status: "task_passed", task_due: "2026-09-01" }), today)).toBe(false);
  });

  it("kafle liczą etapy i wykluczonych, którzy wrócili", () => {
    const stats = editionStats([
      app({ id: 1 }),
      app({ id: 2, screening_verdict: "review" }),
      app({ id: 3, status: "scheduled" }),
      app({ id: 4, status: "contract_sent" }),
      app({ id: 5, status: "rejected", reapplied_at: "2026-09-22T00:00:00Z", closed_reason: "x" }),
    ]);
    expect(stats).toMatchObject({ toCall: 2, review: 1, scheduled: 1, passed: 1, excluded: 1, reapplied: 1 });
  });

  it("etykieta terminu ma dzień tygodnia, datę i godzinę", () => {
    const label = sessionLabel(new Date(2026, 8, 28, 10, 0).toISOString());
    expect(label).toBe("pon 28.09 · 10:00");
  });
});
