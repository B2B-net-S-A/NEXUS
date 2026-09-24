import { describe, expect, it } from "vitest";

import {
  actionForItem,
  actionForTodo,
  candidateLabel,
  countdownLabel,
  debriefAvailable,
  debriefAvailableFromLabel,
  formatDayLabel,
  pairAgenda,
  parseCycleParam,
  parseScope,
  parseView,
  prepQualityTone,
  upcomingAgenda,
  type AgendaEntry,
  type CycleItem,
  type CycleStep,
  type TodoEntry,
} from "@/lib/interview-cycle";

const PAIR = {
  candidate_id: 1,
  candidate_name: "Anna Kowalska",
  candidate_email: "anna@example.com",
  job_id: 2,
  job_title: "Data Engineer",
  client_id: 3,
  client_name: "Nordea",
};

function steps(overrides: Partial<Record<CycleStep["key"], CycleStep["state"]>>): CycleStep[] {
  const keys: CycleStep["key"][] = ["slots", "choice", "prep", "prep2", "interview", "call", "debrief"];
  return keys.map((key) => ({
    key,
    label: key,
    state: overrides[key] ?? "todo",
    at: null,
    event_id: null,
    meta: null,
  }));
}

function item(partial: Partial<CycleItem>): CycleItem {
  return {
    ...PAIR,
    steps: steps({}),
    current_step: "slots",
    latest_stage: "client_interview",
    slot_request: null,
    interview_event_id: null,
    debrief: null,
    ...partial,
  };
}

function agenda(start: string, kind: AgendaEntry["kind"] = "prep", extra: Partial<AgendaEntry> = {}): AgendaEntry {
  return { ...PAIR, kind, start, end: null, event_id: 9, slot_request_id: null, online_meeting_url: null, done: false, ...extra };
}

describe("interview-cycle — adres", () => {
  it("?event= zawsze otwiera Tydzień, domyślnie Tablica (także stare ?view=agenda)", () => {
    expect(parseView(null, false)).toBe("board");
    expect(parseView("board", false)).toBe("board");
    expect(parseView("week", false)).toBe("week");
    expect(parseView("board", true)).toBe("week");
    expect(parseView("agenda", false)).toBe("board");
    expect(parseView("cokolwiek", false)).toBe("board");
  });

  it("zakres z adresu albo domyślny roli", () => {
    expect(parseScope(null, "jobs")).toBe("jobs");
    expect(parseScope("mine", "jobs")).toBe("mine");
    expect(parseScope("xxx", "mine")).toBe("mine");
  });

  it("?cycle=12-34 → para; śmieci → null", () => {
    expect(parseCycleParam("12-34")).toEqual({ candidateId: 12, jobId: 34 });
    expect(parseCycleParam("12")).toBeNull();
    expect(parseCycleParam(null)).toBeNull();
  });
});

describe("interview-cycle — czas", () => {
  const now = new Date("2031-06-10T10:00:00Z"); // 12:00 w Warszawie

  it("odliczanie zaokrągla w górę i mówi „po terminie”", () => {
    expect(countdownLabel("2031-06-10T10:17:10Z", now)).toBe("zostało 18 min");
    expect(countdownLabel("2031-06-10T09:48:00Z", now)).toBe("po terminie 12 min");
  });

  it("etykieta dnia: dziś / jutro w strefie Warszawy", () => {
    expect(formatDayLabel("2031-06-10T15:00:00Z", now)).toMatch(/^Dziś/);
    // 23:30 UTC = 01:30 następnego dnia w Warszawie → już „Jutro”.
    expect(formatDayLabel("2031-06-10T23:30:00Z", now)).toMatch(/^Jutro/);
  });

  it("wydarzenia jednej pary, chronologicznie (panel kandydata)", () => {
    const other = { ...agenda("2031-06-10T06:00:00Z"), candidate_id: 999 };
    const list = pairAgenda(
      [agenda("2031-06-11T08:00:00Z"), other, agenda("2031-06-10T12:00:00Z"), agenda("2031-06-10T07:00:00Z")],
      "1-2",
      now,
    );
    expect(list.map((e) => e.start)).toEqual([
      "2031-06-10T07:00:00Z",
      "2031-06-10T12:00:00Z",
      "2031-06-11T08:00:00Z",
    ]);
  });

  it("przeszłe dni znikają, chyba że wisi niezamknięty telefon", () => {
    const list = upcomingAgenda(
      [
        agenda("2031-06-09T08:00:00Z"),
        agenda("2031-06-09T09:00:00Z", "call"),
        agenda("2031-06-09T10:00:00Z", "call", { done: true }),
        agenda("2031-06-10T09:00:00Z"),
      ],
      now,
    );
    expect(list).toHaveLength(2);
  });
});

describe("interview-cycle — akcje", () => {
  it("rola bez DL nie dostaje „Dodaj terminy”", () => {
    const it0 = item({ steps: steps({ slots: "current" }) });
    expect(actionForItem(it0, { canManageSlots: false })).toBeNull();
    expect(actionForItem(it0, { canManageSlots: true })?.label).toBe("Dodaj terminy");
  });

  it("wybór terminu należy do rekrutera, potwierdzenie do DL", () => {
    const req = {
      id: 5,
      status: "awaiting_dl" as const,
      slots: [{ start: "2031-06-12T08:00:00Z", end: null }],
      chosen_index: 0,
      respond_by: null,
      recruiter_id: 7,
      created_by: 8,
      duration_minutes: 60,
      note: null,
      event_id: null,
    };
    const waiting = item({ steps: steps({ slots: "done", choice: "waiting" }), slot_request: req });
    expect(actionForItem(waiting, { canManageSlots: false })).toBeNull();
    expect(actionForItem(waiting, { canManageSlots: true })?.action.type).toBe("confirm");
    const pick = item({
      steps: steps({ slots: "done", choice: "current" }),
      slot_request: { ...req, status: "awaiting_recruiter", chosen_index: null },
    });
    expect(actionForItem(pick, { canManageSlots: false })?.action.type).toBe("pick");
  });

  it("telefon po rozmowie → debrief pod wydarzeniem rozmowy", () => {
    const it0 = item({
      steps: steps({ slots: "done", choice: "done", prep: "done", prep2: "skipped", interview: "done", call: "current" }),
      interview_event_id: 44,
    });
    expect(actionForItem(it0, { canManageSlots: false })).toEqual(
      expect.objectContaining({ stepKey: "call", label: "Zapisz debrief", action: expect.objectContaining({ type: "debrief", eventId: 44 }) }),
    );
  });

  it("zadanie „Zadzwoń teraz” otwiera debrief", () => {
    const todo: TodoEntry = { ...PAIR, kind: "call_now", priority: 0, due: null, event_id: 44, slot_request_id: null };
    expect(actionForTodo(todo, [])).toEqual(expect.objectContaining({ type: "debrief", eventId: 44 }));
  });

  it("bez nazwiska (brak odczytu kandydatów) — numer, nie pustka", () => {
    expect(candidateLabel({ candidate_id: 9, candidate_name: null })).toBe("Kandydat #9");
  });
});

describe("debrief dopiero od rozpoczęcia rozmowy", () => {
  // 23.09.2026 10:00 czasu warszawskiego.
  const now = new Date("2026-09-23T08:00:00Z");

  it("dostępny od startu rozmowy, nie wcześniej", () => {
    expect(debriefAvailable("2026-09-23T07:59:00Z", now)).toBe(true);
    expect(debriefAvailable("2026-09-23T08:00:00Z", now)).toBe(true);
    expect(debriefAvailable("2026-09-23T08:01:00Z", now)).toBe(false);
    // Nieznany termin nie blokuje (serwer i tak pilnuje).
    expect(debriefAvailable(undefined, now)).toBe(true);
  });

  it("podpowiedź podaje godzinę, a dla innego dnia także dzień", () => {
    expect(debriefAvailableFromLabel("2026-09-23T12:00:00Z", now)).toBe(
      "Debrief po rozmowie — dostępny od 14:00",
    );
    expect(debriefAvailableFromLabel("2026-09-24T12:00:00Z", now)).toBe(
      "Debrief po rozmowie — dostępny od jutra, 14:00",
    );
    expect(debriefAvailableFromLabel("2026-09-28T12:00:00Z", now)).toBe(
      "Debrief po rozmowie — dostępny od 28.09, 14:00",
    );
  });
});

describe("interview-cycle — prepy w Teams (0370)", () => {
  it("słaby prep i prep bez nagrania otwierają ocenę prepu, nie planowanie", () => {
    for (const kind of ["prep_weak", "prep_unrecorded"] as const) {
      const todo: TodoEntry = { ...PAIR, kind, priority: 6, due: null, event_id: 71, slot_request_id: null };
      expect(actionForTodo(todo, [])).toEqual(
        expect.objectContaining({ type: "prep_review", eventId: 71 }),
      );
    }
  });

  it("brak Prepu 1 i 2 planuje właściwy numer", () => {
    const p1: TodoEntry = { ...PAIR, kind: "prep_missing", priority: 4, due: null, event_id: 5, slot_request_id: null };
    const p2: TodoEntry = { ...p1, kind: "prep2_missing" };
    expect(actionForTodo(p1, [])).toEqual(expect.objectContaining({ type: "plan_prep", second: false }));
    expect(actionForTodo(p2, [])).toEqual(expect.objectContaining({ type: "plan_prep", second: true }));
  });

  it("jakość prepu ma ton: słaby = danger, bez nagrania = warn, dobry = done", () => {
    expect(prepQualityTone("weak")).toBe("danger");
    expect(prepQualityTone("unrecorded")).toBe("warn");
    expect(prepQualityTone("good")).toBe("done");
    expect(prepQualityTone("pending")).toBe("muted");
  });
});
