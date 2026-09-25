import { describe, expect, it } from "vitest";

import {
  awaitingLuna,
  bookableSessions,
  bulkFailureMessage,
  callQueue,
  cohortLabel,
  editionStats,
  lunaSkipped,
  nextCohort,
  sessionLabel,
  taskOverdue,
  toIsoDate,
  truncatedListNote,
  withReplacedApplication,
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

  it("przy przyciętej liście wykluczonych i sumę liczy serwer, nie lista", () => {
    const apps = [app({ id: 1 }), app({ id: 2, status: "rejected", closed_reason: "x" })];
    const stats = editionStats(apps, {
      to_call: 1,
      rejected: 2400,
      withdrew: 10,
      reapplied_excluded: 7,
    });
    expect(stats).toMatchObject({ fromAds: 2411, toCall: 1, excluded: 2400, reapplied: 7 });
    // Bez liczników z serwera (harness) — liczymy z listy jak dotąd.
    expect(editionStats(apps)).toMatchObject({ fromAds: 2, excluded: 1 });
  });

  it("informacja „pokazano N z M” tylko przy przyciętej liście", () => {
    expect(truncatedListNote(2000, 2000)).toBeNull();
    expect(truncatedListNote(12, undefined)).toBeNull();
    expect(truncatedListNote(2000, 2501)).toMatch(/^Pokazano 2000 z 2501 zgłoszeń\./);
  });

  it("zbiorcze wykluczenie mówi, ilu NIE wykluczono i dlaczego", () => {
    expect(bulkFailureMessage("reject", [])).toBeNull();
    const moved = "Ta osoba nie czeka już odłożona przez Lunę — ktoś ją przesunął.";
    expect(
      bulkFailureMessage("reject", [
        { id: 1, message: moved },
        { id: 2, message: moved },
      ]),
    ).toBe(`Nie wykluczono 2 os.: ${moved}`);
    expect(
      bulkFailureMessage("reject", [
        { id: 1, message: moved },
        { id: 2, message: "Nie ma takiego zgłoszenia." },
      ]),
    ).toBe(`Nie wykluczono 2 os.: ${moved} (1 os.) Nie ma takiego zgłoszenia. (1 os.)`);
    expect(bulkFailureMessage("call", [{ id: 1, message: "x" }])).toBe("Nie udało się dla 1 os.: x");
  });

  it("etykieta terminu ma dzień tygodnia, datę i godzinę", () => {
    const label = sessionLabel(new Date(2026, 8, 28, 10, 0).toISOString());
    expect(label).toBe("pon 28.09 · 10:00");
  });
});

describe("withReplacedApplication — liczniki po akcji na osobie", () => {
  it("wykluczenie przesuwa osobę między licznikami od razu", () => {
    const data = {
      items: [app({ id: 1, status: "to_call" }), app({ id: 2, status: "to_call" })],
      counts: { to_call: 2, rejected: 3, reapplied_excluded: 1 },
    };
    const next = withReplacedApplication(data, app({ id: 1, status: "rejected" }));
    expect(next?.counts).toEqual({ to_call: 1, rejected: 4, reapplied_excluded: 1 });
    expect(next?.items.map((a) => a.status)).toEqual(["rejected", "to_call"]);
    expect(editionStats(next!.items, next!.counts).excluded).toBe(4);
  });

  it("przywrócenie zakłada licznik statusu, którego wcześniej nie było", () => {
    const data = { items: [app({ id: 5, status: "rejected" })], counts: { rejected: 1 } };
    const next = withReplacedApplication(data, app({ id: 5, status: "to_call" }));
    expect(next?.counts).toEqual({ rejected: 0, to_call: 1 });
  });

  it("ten sam status albo osoba spoza listy nie zmienia liczników", () => {
    const data = { items: [app({ id: 1, status: "to_call" })], counts: { to_call: 1 } };
    expect(withReplacedApplication(data, app({ id: 1, status: "to_call" }))?.counts).toEqual({ to_call: 1 });
    expect(withReplacedApplication(data, app({ id: 9, status: "rejected" }))?.counts).toEqual({ to_call: 1 });
    expect(withReplacedApplication(undefined, app({ id: 1 }))).toBeUndefined();
  });
});
