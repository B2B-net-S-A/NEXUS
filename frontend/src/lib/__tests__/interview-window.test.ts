import { describe, expect, it } from "vitest";

import type { NotificationResponse } from "@/lib/api";
import type {
  AgendaEntry,
  CycleItem,
  CycleOverview,
  PairInfo,
  SlotRequest,
  TodoEntry,
} from "@/lib/interview-cycle";
import {
  buildInterviewWindow,
  nextWindowBoundary,
  shortName,
  whenLabel,
} from "@/lib/interview-window";

// Wtorek 13.10.2026, 14:48 w Warszawie (UTC+2).
const NOW = new Date("2026-10-13T12:48:00Z");
const at = (minutes: number) => new Date(NOW.getTime() + minutes * 60_000).toISOString();

function pair(candidateId: number, name: string): PairInfo {
  return {
    candidate_id: candidateId,
    candidate_name: name,
    candidate_email: null,
    job_id: 100 + candidateId,
    job_title: "Analityk danych",
    client_id: 5,
    client_name: "Klient Testowy",
  };
}

const MARTA = pair(1, "Marta Wilk");
const TOMASZ = pair(2, "Tomasz Lis");
const IGOR = pair(3, "Igor Sowa");

function agenda(p: PairInfo, kind: AgendaEntry["kind"], fields: Partial<AgendaEntry>): AgendaEntry {
  return {
    ...p,
    kind,
    start: at(0),
    end: null,
    event_id: 900 + p.candidate_id,
    slot_request_id: null,
    online_meeting_url: null,
    done: false,
    mine: true,
    ...fields,
  };
}

function todo(p: PairInfo, kind: TodoEntry["kind"], fields: Partial<TodoEntry> = {}): TodoEntry {
  return {
    ...p,
    kind,
    priority: 5,
    due: null,
    event_id: null,
    slot_request_id: null,
    mine: true,
    ...fields,
  };
}

function slotRequest(status: SlotRequest["status"], slots = 3): SlotRequest {
  return {
    id: 7,
    status,
    slots: Array.from({ length: slots }, (_, i) => ({ start: at(60 * 24 * (i + 2)), end: null })),
    chosen_index: null,
    respond_by: null,
    recruiter_id: 11,
    created_by: 22,
    duration_minutes: 60,
    note: null,
    event_id: null,
  };
}

function item(p: PairInfo, fields: Partial<CycleItem> = {}): CycleItem {
  return {
    ...p,
    steps: [],
    current_step: null,
    latest_stage: "client_interview",
    slot_request: null,
    interview_event_id: null,
    debrief: null,
    ...fields,
  };
}

function overview(fields: Partial<CycleOverview> = {}): CycleOverview {
  return {
    generated_at: at(0),
    scope: "mine",
    call_window_minutes: 30,
    items: [],
    agenda: [],
    todos: [],
    truncated: false,
    ...fields,
  };
}

let nextId = 1;
function notif(
  type: string,
  link: string | null,
  fields: Partial<NotificationResponse> = {},
): NotificationResponse {
  return {
    id: nextId++,
    user_id: 11,
    title: `Tytuł ${type}`,
    message: `Treść ${type}`,
    link,
    notification_type: type,
    is_read: false,
    created_at: at(-30),
    ...fields,
  };
}

const build = (o: CycleOverview | null, n: NotificationResponse[] = []) =>
  buildInterviewWindow({ overview: o, notifications: n, now: NOW });

describe("„Teraz” liczone lokalnie z agendy", () => {
  it("telefon po rozmowie u klienta trwa od jej końca do końca okna i daje pigułkę", () => {
    const call = agenda(MARTA, "call", { start: at(-12), end: at(18) });
    const w = build(overview({ agenda: [call] }));

    expect(w.now.map((r) => [r.title, r.status, r.detail])).toEqual([
      ["Marta Wilk", "Zadzwoń po rozmowie u klienta", "zostało 18 min"],
    ]);
    expect(w.now[0].todo).toMatchObject({ kind: "call_now", event_id: call.event_id });
    expect(w.pill).toMatchObject({ name: "M. Wilk", minutesLeft: 18 });
    expect(w.urgent).toBe(true);
  });

  it("nie czeka na serwer: po oknie telefon staje się zaległym debriefem", () => {
    const call = agenda(MARTA, "call", { start: at(-50), end: at(-20) });
    // Serwer odpytany przed końcem okna nadal mówi „call_now”.
    const w = build(overview({ agenda: [call], todos: [todo(MARTA, "call_now")] }));

    expect(w.now).toEqual([]);
    expect(w.pill).toBeNull();
    expect(w.waiting.map((r) => [r.status, r.detail, r.todo?.kind])).toEqual([
      ["Debrief zaległy", "po terminie 20 min", "debrief_overdue"],
    ]);
  });

  it("zapisany debrief zamyka telefon, a przyszła rozmowa go jeszcze nie otwiera", () => {
    const done = agenda(MARTA, "call", { start: at(-12), end: at(18), done: true });
    const future = agenda(TOMASZ, "call", { start: at(120), end: at(150) });

    expect(build(overview({ agenda: [done, future] })).count).toBe(0);
  });

  it("prep wchodzi kwadrans przed startem z linkiem Teams, rozmowa u klienta bez linku", () => {
    const prep = agenda(TOMASZ, "prep2", {
      start: at(12),
      end: at(42),
      online_meeting_url: "https://teams.example/prep",
    });
    const later = agenda(IGOR, "prep", { start: at(16), end: at(46) });
    const running = agenda(MARTA, "interview", { start: at(-10), end: at(50) });
    const w = build(overview({ agenda: [later, prep, running] }));

    expect(w.now.map((r) => [r.title, r.status, r.joinUrl])).toEqual([
      ["Marta Wilk", "Rozmowa u klienta trwa", null],
      ["Tomasz Lis", "Prep 2 za 12 min", "https://teams.example/prep"],
    ]);
    expect(w.pill).toBeNull();
    // Prep za 16 minut jeszcze nie jest „teraz” — czeka w stopce.
    expect(w.today).toMatchObject({ label: "Prep 1", name: "Igor Sowa" });
  });

  it("link spotkania inny niż https nie daje przycisku „Dołącz”", () => {
    const prep = agenda(TOMASZ, "prep", {
      start: at(5),
      end: at(35),
      online_meeting_url: "javascript:alert(1)",
    });
    const w = build(overview({ agenda: [prep] }));

    expect(w.now[0].joinUrl).toBeNull();
    expect(w.now[0].detail).not.toContain("Teams");
  });

  it("pokazuje tylko wydarzenia i zadania oznaczone przez serwer jako moje", () => {
    const foreign = agenda(MARTA, "call", { start: at(-12), end: at(18), mine: false });
    const legacy = agenda(TOMASZ, "prep", { start: at(5), mine: undefined });
    const w = build(
      overview({
        agenda: [foreign, legacy],
        todos: [todo(IGOR, "slots_pick", { mine: false }), todo(IGOR, "prep_weak", { mine: undefined })],
      }),
    );

    expect(w.count).toBe(0);
  });
});

describe("„Czeka na Ciebie”", () => {
  it("jedna pozycja na parę, w kolejności serwera, bez stanu „brak terminów od klienta”", () => {
    const w = build(
      overview({
        items: [item(IGOR, { slot_request: slotRequest("awaiting_recruiter") })],
        todos: [
          todo(IGOR, "slots_pick", { due: at(60 * 21) }),
          todo(IGOR, "prep_missing"),
          todo(TOMASZ, "prep2_missing", { due: at(60 * 19), urgent: true }),
          todo(MARTA, "slots_missing"),
        ],
      }),
    );

    expect(w.waiting.map((r) => [r.title, r.status, r.detail, r.more])).toEqual([
      ["Igor Sowa", "Terminy czekają na kandydata", "3 terminy od klienta · odpowiedz do jutro 11:48", 1],
      ["Tomasz Lis", "Prep 2 bez terminu", "rozmowa u klienta jutro 09:48", 0],
    ]);
    expect(w.waiting[1].urgent).toBe(true);
    expect(w.urgent).toBe(true);
    expect(w.count).toBe(2);
  });

  it("para bez terminu w NEXUSIE: „Uzupełnij pytania z rozmowy u klienta” (20.10.2026)", () => {
    const w = build(overview({ todos: [todo(IGOR, "questions_missing", { due: at(-60) })] }));
    expect(w.waiting.map((r) => [r.title, r.status, r.detail, r.icon])).toEqual([
      [
        "Igor Sowa",
        "Uzupełnij pytania z rozmowy u klienta",
        "rozmowy nie ma w kalendarzu — zapisz, o co pytał klient",
        "note",
      ],
    ]);
    expect(w.count).toBe(1);
  });

  it("zaległy debrief rozmowy spoza okna agendy (ponad 14 dni) zostaje widoczny", () => {
    // Agenda sięga 14 dni wstecz, zadanie z serwera nie ma limitu wieku.
    const w = build(
      overview({
        todos: [todo(MARTA, "debrief_overdue", { event_id: 901, due: at(-60 * 24 * 20) })],
      }),
    );

    expect(w.waiting.map((r) => [r.title, r.status, r.detail, r.todo?.event_id])).toEqual([
      ["Marta Wilk", "Debrief zaległy", "po terminie 20 dni", 901],
    ]);
    expect(w.count).toBe(1);
  });

  it("zaległy debrief z agendy i z zadania serwera to jeden wiersz", () => {
    const call = agenda(MARTA, "call", { start: at(-60 * 30.5), end: at(-60 * 30), event_id: 901 });
    const w = build(
      overview({
        agenda: [call],
        todos: [todo(MARTA, "debrief_overdue", { event_id: 901, due: call.end })],
      }),
    );

    expect(w.waiting.map((r) => [r.status, r.detail, r.more])).toEqual([
      ["Debrief zaległy", "po terminie 30 h", 0],
    ]);
  });

  it("zadanie pary, która ma wiersz w „Teraz”, nie dostaje drugiego wiersza", () => {
    const w = build(
      overview({
        agenda: [agenda(MARTA, "call", { start: at(-5), end: at(25) })],
        todos: [todo(MARTA, "prep2_missing")],
      }),
    );

    expect(w.waiting).toEqual([]);
    expect(w.now[0].more).toBe(1);
  });
});

describe("„Nowe” — powiadomienia", () => {
  const cycle = (p: PairInfo) => `/calendar?cycle=${p.candidate_id}-${p.job_id}`;

  it("sygnał zadania zwija się w kropkę przy wierszu pary", () => {
    const n = notif("interview_slots_requested", cycle(IGOR));
    const w = build(
      overview({
        items: [item(IGOR, { slot_request: slotRequest("awaiting_recruiter") })],
        todos: [todo(IGOR, "slots_pick")],
      }),
      [n],
    );

    expect(w.news).toEqual([]);
    expect(w.waiting[0].unreadIds).toEqual([n.id]);
    expect(w.count).toBe(1);
  });

  it("informacja ma własny wiersz, także gdy para ma zadanie", () => {
    const saved = notif("interview_debrief_saved", cycle(IGOR), {
      message: "Poszło dobrze. Warunek: start od grudnia",
    });
    const confirmed = notif("interview_slot_confirmed", cycle(TOMASZ));
    const w = build(
      overview({
        items: [
          item(IGOR),
          item(TOMASZ, {
            steps: [
              { key: "interview", label: "Rozmowa", state: "scheduled", at: at(60 * 44), event_id: 5, meta: null },
            ],
          }),
        ],
        todos: [todo(IGOR, "prep2_missing")],
      }),
      [saved, confirmed],
    );

    expect(w.waiting[0].unreadIds).toEqual([]);
    expect(w.news.map((r) => [r.title, r.status, r.detail])).toEqual([
      ["Igor Sowa", "Debrief zapisany", "Poszło dobrze. Warunek: start od grudnia"],
      ["Tomasz Lis", "Termin potwierdzony u klienta", "czw., 15.10, 10:48"],
    ]);
    expect(w.count).toBe(3);
  });

  it("debrief pokazuje wynik i warunek kandydata ze stanu pary", () => {
    const debrief = {
      id: 1,
      overall_impression: 5,
      outcome: "good" as const,
      offer_acceptance: "likely" as const,
      acceptance_condition: "start od grudnia",
    };
    const w = build(overview({ items: [item(IGOR, { debrief })] }), [
      notif("interview_debrief_saved", cycle(IGOR)),
    ]);

    expect(w.news[0].detail).toBe("dobrze · raczej przyjmie · warunek: start od grudnia");
  });

  it("chowa sygnał, gdy stan pary mówi, że sprawa jest załatwiona", () => {
    const requested = notif("interview_slots_requested", cycle(IGOR));
    const chosen = notif("interview_slot_chosen", cycle(TOMASZ));
    const call = notif("post_interview_t15", `${cycle(MARTA)}&debrief=901`);
    const escalation = notif("post_interview_t2h_escalation", `${cycle(MARTA)}&debrief=901`);
    const debrief = { id: 1, overall_impression: 5, offer_acceptance: null, acceptance_condition: null };
    const w = build(
      overview({
        items: [
          item(IGOR, { slot_request: slotRequest("awaiting_dl") }),
          item(TOMASZ, { slot_request: slotRequest("confirmed") }),
          item(MARTA, { interview_event_id: 901, debrief }),
        ],
      }),
      [requested, chosen, call, escalation],
    );

    expect(w.news).toEqual([]);
    expect(w.count).toBe(0);
  });

  it("nie chowa niczego, gdy przegląd jest starszy niż powiadomienie, ucięty albo go nie ma", () => {
    const n = notif("interview_slots_requested", cycle(IGOR), { created_at: at(1) });
    const stale = overview({ items: [item(IGOR, { slot_request: slotRequest("confirmed") })] });

    expect(build(stale, [n]).news).toHaveLength(1);
    expect(build({ ...stale, generated_at: at(5), truncated: true }, [n]).news).toHaveLength(1);
    expect(build(null, [n]).news).toHaveLength(1);
    expect(build({ ...stale, generated_at: at(5) }, [n]).news).toHaveLength(0);
  });

  it("para spoza przeglądu zostaje widoczna z tytułem i treścią powiadomienia", () => {
    const n = notif("prep_attention", "/calendar?cycle=70-71", {
      title: "Prep 1 słaby",
      message: "Olga Kruk — Scrum Master: ocena prepu jest słaba.",
    });
    const w = build(overview(), [n]);

    expect(w.news.map((r) => [r.title, r.context, r.status, r.detail, r.href])).toEqual([
      [
        "Prep 1 słaby",
        null,
        "",
        "Olga Kruk — Scrum Master: ocena prepu jest słaba.",
        "/calendar?cycle=70-71",
      ],
    ]);
  });

  it("eskalacja bez debriefu jest informacją z nazwiskiem zamiast numeru kandydata", () => {
    const n = notif("post_interview_t2h_escalation", `${cycle(MARTA)}&debrief=901`, {
      message: "Minęły 2 godziny od interview z kandydatem #1",
    });
    const w = build(overview({ items: [item(MARTA, { interview_event_id: 901 })] }), [n]);

    expect(w.news.map((r) => [r.title, r.status])).toEqual([
      ["Marta Wilk", "Brak debriefu 2 h po rozmowie u klienta"],
    ]);
  });

  it("przypomnienie kalendarza: zwija się w wiersz wydarzenia, po starcie znika", () => {
    const soon = agenda(TOMASZ, "prep2", { start: at(12), end: at(42), event_id: 50 });
    const later = agenda(IGOR, "prep", { start: at(55), end: at(85), event_id: 51 });
    const past = agenda(MARTA, "interview", { start: at(-90), end: at(-30), event_id: 52 });
    const folded = notif("interview_scheduled", "/calendar?event=50");
    const own = notif("interview_scheduled", "/calendar?event=51");
    const gone = notif("interview_scheduled", "/calendar?event=52");
    const w = build(overview({ agenda: [soon, later, past] }), [folded, own, gone]);

    expect(w.now[0].unreadIds).toEqual([folded.id]);
    expect(w.news.map((r) => [r.title, r.status])).toEqual([["Igor Sowa", "Prep 1 dziś 15:43"]]);
  });

  // Produkcja 13.10.2026: w „Nowe” wisiało 8 przypomnień „Za 15 minut: …”
  // sprzed nawet 23 godzin — wydarzenia spoza agendy cyklu żyły tam dobę.
  it("przypomnienie o wydarzeniu spoza agendy znika, gdy wydarzenie się zaczęło", () => {
    const upcoming = notif("interview_scheduled", "/calendar?event=77", {
      message: "Za 15 minut: Screening",
      created_at: at(-14),
    });
    const started = notif("interview_scheduled", "/calendar?event=78", {
      message: "Za 15 minut: Rozmowa",
      created_at: at(-44),
    });
    const lastMinute = notif("interview_scheduled", "/calendar?event=79", {
      message: "Za 1 minutę: Termin",
      created_at: at(-2),
    });
    const yesterday = notif("interview_scheduled", "/calendar?event=80", {
      message: "Za 2 minuty: Rozmowa",
      created_at: at(-60 * 23),
    });
    const w = build(overview(), [upcoming, started, lastMinute, yesterday]);

    expect(w.news.map((r) => [r.detail, r.href])).toEqual([
      ["Za 15 minut: Screening", "/calendar?event=77"],
    ]);
  });

  it("przypomnienie bez liczby minut w treści żyje najwyżej dobę", () => {
    const recent = notif("interview_scheduled", "/calendar?event=77", {
      message: "Przypomnienie: Screening",
      created_at: at(-60 * 5),
    });
    const old = notif("interview_scheduled", "/calendar?event=78", {
      message: "Przypomnienie: Screening",
      created_at: at(-60 * 25),
    });

    expect(build(overview(), [recent, old]).news.map((r) => r.href)).toEqual([
      "/calendar?event=77",
    ]);
  });

  it("podpisuje wiersz przejęty w zastępstwie i pomija typy spoza kategorii", () => {
    const inherited = notif("post_interview_t15", "/calendar?event=9&action=feedback", {
      on_behalf_of_name: "Anna Dąb",
    });
    const other = notif("stage_changed", "/jobs/1");
    const w = build(overview(), [inherited, other]);

    expect(w.news).toHaveLength(1);
    expect(w.news[0].onBehalfOf).toBe("w zastępstwie za Anna Dąb");
  });

  it("awaria przeglądu nie gasi powiadomień", () => {
    const n = notif("interview_slot_chosen", cycle(IGOR));
    const w = build(null, [n]);

    expect(w.news).toHaveLength(1);
    expect(w.now).toEqual([]);
    expect(w.waiting).toEqual([]);
  });
});

describe("pomocnicze", () => {
  it("whenLabel mówi „dziś”, „jutro” albo podaje dzień w strefie firmy", () => {
    expect(whenLabel(at(60), NOW)).toBe("dziś 15:48");
    expect(whenLabel(at(60 * 20), NOW)).toBe("jutro 10:48");
    expect(whenLabel(at(60 * 44), NOW)).toBe("czw., 15.10, 10:48");
  });

  it("shortName skraca imię, ale nie rusza etykiety bez nazwiska", () => {
    expect(shortName("Marta Wilk")).toBe("M. Wilk");
    expect(shortName("Kandydat #12")).toBe("Kandydat #12");
    expect(shortName("Cher")).toBe("Cher");
  });

  it("nextWindowBoundary wskazuje najbliższą zmianę w moich wydarzeniach", () => {
    const o = overview({
      agenda: [
        agenda(TOMASZ, "prep", { start: at(40), end: at(70) }),
        agenda(MARTA, "call", { start: at(-5), end: at(25) }),
        agenda(IGOR, "prep", { start: at(1), mine: false }),
      ],
    });

    // Koniec okna telefonu (25 min) i wejście prepu do „Teraz” (40 − 15 = 25 min).
    expect(nextWindowBoundary(o, NOW)).toBe(NOW.getTime() + 25 * 60_000);
    expect(nextWindowBoundary(overview(), NOW)).toBeNull();
  });
});
