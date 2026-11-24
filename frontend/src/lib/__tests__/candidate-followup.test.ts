import { afterEach, describe, expect, it, vi } from "vitest";

import type { FollowupRow } from "@/lib/api/candidateFollowups";
import {
  addDaysIso,
  callerReasonSentence,
  cardBadgeLabel,
  columnLabel,
  followupDueLabel,
  followupTone,
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

describe("follow-up z kandydatem — brzegi etykiet", () => {
  it("shortDate: niepoprawna wartość wraca bez zmian, data kalendarzowa bez strefy", () => {
    expect(shortDate("nie-data")).toBe("nie-data");
    expect(shortDate("")).toBe("");
    // Sama data (bez godziny) nie przesuwa się o strefę.
    expect(shortDate("2026-01-01")).toBe("01.01");
    // Zima (CET, +1): 22:59 UTC to jeszcze ten sam dzień, 23:00 UTC już następny.
    expect(shortDate("2026-12-31T22:59:00Z")).toBe("31.12");
    expect(shortDate("2026-12-31T23:00:00Z")).toBe("01.01");
    // Lato (CEST, +2): granica dnia o 22:00 UTC.
    expect(shortDate("2026-07-14T21:59:00Z")).toBe("14.07");
    expect(shortDate("2026-07-14T22:00:00Z")).toBe("15.07");
  });

  it("shortPersonName: pusto, same spacje, trzy człony", () => {
    expect(shortPersonName(null)).toBe("");
    expect(shortPersonName(undefined)).toBe("");
    expect(shortPersonName("")).toBe("");
    expect(shortPersonName("   ")).toBe("");
    expect(shortPersonName("  Anna   Maria  Testowa ")).toBe("Anna T.");
  });

  it("followupTone: zaległy = danger, dziś = warning, reszta neutralnie", () => {
    expect(followupTone("overdue")).toBe("danger");
    expect(followupTone("today")).toBe("warning");
    expect(followupTone("tomorrow")).toBe("neutral");
    expect(followupTone("scheduled")).toBe("neutral");
  });

  it("zaległy 5 dni i 22 dni — liczba mnoga", () => {
    expect(followupDueLabel(row({ overdue_days: 5 }))).toBe("zaległy 5 dni");
    expect(followupDueLabel(row({ overdue_days: 22 }))).toBe("zaległy 22 dni");
  });

  it("chip procesu bez klienta używa tytułu rekrutacji, 1 dzień w liczbie pojedynczej", () => {
    const process = {
      ...row().processes[0],
      client_name: null,
      column: "cv_sent" as const,
      silent_days: 1,
    };
    expect(processChipLabel(process)).toBe("Backend Java · CV wysłane, 1 dzień");
    expect(columnLabel("cv_sent")).toBe("CV wysłane");
  });

  it("ostatni kontakt: nieznany rodzaj przechodzi wprost, bez osoby i rodzaju — bez nawiasu", () => {
    expect(
      lastContactLabel(row({ last_contact_kind: "sms", last_contact_by: null })),
    ).toBe("Ostatni kontakt 08.09 (sms)");
    expect(
      lastContactLabel(row({ last_contact_kind: null, last_contact_by: null })),
    ).toBe("Ostatni kontakt 08.09");
    expect(lastContactLabel(row({ last_contact_kind: "call" }))).toBe(
      "Ostatni kontakt 08.09 (Anna K., telefon)",
    );
  });

  it("powód dzwoniącego: każdy wariant i nieznany powód", () => {
    expect(callerReasonSentence(row({ caller_reason: "recent_contact" }))).toBe(
      "prowadzi jeden z procesów i ostatnio rozmawiał(a) z kandydatem",
    );
    expect(callerReasonSentence(row({ caller_reason: "substitute" }))).toBe(
      "zastępuje właściciela procesu (nieobecność w COMPASS)",
    );
    expect(callerReasonSentence(row({ caller_reason: "next_process" }))).toBe(
      "właściciel najdalszego procesu ma nieaktywne konto",
    );
    expect(callerReasonSentence(row({ caller_reason: "none" }))).toBe(
      "żaden właściciel procesu nie jest aktywny",
    );
    expect(callerReasonSentence(row({ caller_reason: "nieznany_powod" }))).toBe("żaden właściciel procesu nie jest aktywny");
  });

  it("nieznana kolumna z serwera pokazuje się surowo, proces bez klienta — tytułem", () => {
    const process = {
      ...row().processes[0],
      client_name: null,
      column: "offer" as FollowupRow["processes"][number]["column"],
    };
    expect(columnLabel(process.column)).toBe("offer");
    expect(processChipLabel(process)).toBe("Backend Java · offer, 11 dni");
    expect(callerReasonSentence(row({ processes: [process] }))).toBe(
      "prowadzi proces, który zaszedł najdalej (Backend Java, offer)",
    );
  });

  it("powód „najdalej” bez procesów nie wysypuje się", () => {
    expect(callerReasonSentence(row({ processes: [] }))).toBe(
      "prowadzi proces, który zaszedł najdalej ()",
    );
  });

  it("plakietka: dzwoniący bez nazwy to „ktoś z zespołu”, patrzący bez id to nie „Ty”", () => {
    const badge = { ...row(), caller_id: 3, caller_name: null };
    expect(cardBadgeLabel(badge, 9)).toBe("Follow-up: ktoś z zespołu · zaległy 2 dni");
    expect(cardBadgeLabel({ ...row(), caller_id: 3 }, null)).toBe(
      "Follow-up: Anna K. · zaległy 2 dni",
    );
    expect(cardBadgeLabel({ ...row(), caller_id: 3 }, undefined)).toBe(
      "Follow-up: Anna K. · zaległy 2 dni",
    );
  });

  it("następny krok: oddzwonienie bez dnia, zmiana, rozmowa", () => {
    expect(nextStepSentence("callback", null)).toBe("Wybierz dzień, w którym oddzwonić.");
    expect(nextStepSentence("changed", null)).toContain("dostaną powiadomienie");
    expect(nextStepSentence("connected", null)).toContain("Notatka trafi do profilu kandydata");
  });

  it("addDaysIso: wstecz przez przestępny luty i przez zmianę czasu", () => {
    expect(addDaysIso("2028-03-01", -1)).toBe("2028-02-29");
    expect(addDaysIso("2027-03-01", -1)).toBe("2027-02-28");
    expect(addDaysIso("2026-03-28", 1)).toBe("2026-03-29");
    expect(addDaysIso("2026-03-29", 1)).toBe("2026-03-30");
    expect(addDaysIso("2026-10-24", 1)).toBe("2026-10-25");
    expect(addDaysIso("2026-01-01", 0)).toBe("2026-01-01");
  });
});

describe("todayInBusinessTz — granice dnia w Warszawie", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("bez argumentu bierze bieżący czas: 23:30 UTC zimą to już następny dzień", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-24T23:30:00Z"));
    expect(todayInBusinessTz()).toBe("2026-11-25");
    vi.setSystemTime(new Date("2026-11-24T22:59:59Z"));
    expect(todayInBusinessTz()).toBe("2026-11-24");
  });

  it("latem granica wypada o 22:00 UTC, sylwester przechodzi w nowy rok", () => {
    expect(todayInBusinessTz(new Date("2026-07-14T21:59:59Z"))).toBe("2026-07-14");
    expect(todayInBusinessTz(new Date("2026-07-14T22:00:00Z"))).toBe("2026-07-15");
    expect(todayInBusinessTz(new Date("2026-12-31T23:00:00Z"))).toBe("2027-01-01");
  });
});
