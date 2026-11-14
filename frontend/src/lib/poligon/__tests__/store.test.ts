import { describe, expect, it, vi } from "vitest";

import dataset from "../dataset.json";
import poligonRegistry from "../../../../../backend/app/data/novelties/poligon.json";
import { EXERCISES } from "../exercises";
import { BLOCKED_WRITE_MESSAGE, POLIGON_PROGRESS, createPoligonStore, mentionsPoligon, resolveDates, type PoligonAction, type PoligonDataset } from "../store";

const DATA = dataset as unknown as PoligonDataset;
const NOW = Date.UTC(2026, 10, 20, 12, 0, 0);
const JOB = DATA.meta.job_id;
const [first, second] = DATA.meta.people;

function setup() {
  const store = createPoligonStore(DATA, NOW);
  const actions: PoligonAction[] = [];
  store.subscribe((a) => actions.push(a));
  return { store, actions };
}

/** Ostatnie zdarzenie poza odczytami ekranu (`view`). */
const acted = (actions: PoligonAction[]) => actions.filter((a) => a.type !== "view").at(-1);

type Board = { columns: Array<{ stage: string; stage_def_id: number; items: Array<{ candidate_id: number; stage: string; taken_by_name?: string }> }> };

describe("poligon: zapisy nie wychodzą z przeglądarki", () => {
  it("nieznany zapis kończy się odmową, nie zapytaniem do serwera", () => {
    const { store, actions } = setup();
    for (const method of ["post", "put", "patch", "delete"]) {
      const res = store.handle({ method, url: "/api/candidates/123/whatever", body: { a: 1 } });
      expect(res).not.toBe("network");
      expect(res).toEqual({ status: 409, data: { detail: BLOCKED_WRITE_MESSAGE } });
    }
    expect(actions.filter((a) => a.type === "blocked")).toHaveLength(4);
  });

  it("zapis bez identyfikatora poligonu też zostaje w przeglądarce", () => {
    const { store } = setup();
    expect(store.handle({ method: "post", url: "/api/users/me/preferences", body: { theme: "dark" } })).not.toBe("network");
    expect(store.handle({ method: "post", url: "/api/novelties/x/events", body: {} })).toEqual({ status: 204, data: null });
  });

  it("odczyt spoza rekrutacji ćwiczebnej idzie do API (pasek górny, powiadomienia)", () => {
    const { store } = setup();
    expect(store.handle({ method: "get", url: "/api/auth/me" })).toBe("network");
    expect(store.handle({ method: "get", url: "/api/notifications/jobs" })).toBe("network");
  });

  it("odczyt rekrutacji ćwiczebnej bez nagrania daje 404 i ślad dla Testera", () => {
    const { store, actions } = setup();
    const res = store.handle({ method: "get", url: `/api/jobs/${JOB}/nie-ma-takiego` });
    expect(res).toMatchObject({ status: 404 });
    expect(acted(actions)).toMatchObject({ type: "missing" });
  });
});

describe("poligon: Tablica", () => {
  it("ruch karty zmienia Tablicę i zgłasza zdarzenie", () => {
    const { store, actions } = setup();
    const res = store.handle({ method: "post", url: "/api/pipeline/move", body: { candidate_id: first.candidate_id, job_id: JOB, stage: "screening" } });
    expect(res).toMatchObject({ status: 200 });
    const board = (store.handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: Board }).data;
    const screening = board.columns.find((c) => c.stage === "screening")!;
    expect(screening.items[0].candidate_id).toBe(first.candidate_id);
    expect(board.columns.find((c) => c.stage === "new")!.items.some((i) => i.candidate_id === first.candidate_id)).toBe(false);
    expect(acted(actions)).toMatchObject({ type: "move", candidateId: first.candidate_id, fromStage: "new", toStage: "screening" });
  });

  it("odrzucenie niesie nazwę powodu z szablonu rekrutacji", () => {
    const { store, actions } = setup();
    const reasons = (DATA.responses["GET /api/pipeline-templates/1"] as { rejection_reasons: Array<{ id: number; name: string }> }).rejection_reasons;
    const finansowy = reasons.find((r) => r.name.toLowerCase().includes("finans"))!;
    store.handle({ method: "post", url: "/api/pipeline/move", body: { candidate_id: first.candidate_id, job_id: JOB, stage: "rejected", rejection_reason_id: finansowy.id } });
    expect(acted(actions)).toMatchObject({ type: "move", toStage: "rejected", rejectionReasonName: finansowy.name });
  });

  it("„Biorę” oznacza osobę jako Twoją", () => {
    const { store, actions } = setup();
    store.handle({ method: "post", url: "/api/pipeline/claim", body: { candidate_id: second.candidate_id, job_id: JOB } });
    const board = (store.handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: Board }).data;
    const item = board.columns.flatMap((c) => c.items).find((i) => i.candidate_id === second.candidate_id)!;
    expect(item.taken_by_name).toBe("Ty");
    expect(acted(actions)).toEqual({ type: "claim", candidateId: second.candidate_id });
  });

  it("odpowiedzi to kopie — zmiana na ekranie nie psuje stanu poligonu", () => {
    const { store } = setup();
    const a = (store.handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: Board }).data;
    a.columns.length = 0;
    const b = (store.handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: Board }).data;
    expect(b.columns.length).toBeGreaterThan(0);
  });
});

describe("poligon: panel osoby", () => {
  it("panel innej osoby dostaje treść z nagrania, ale jej imię i identyfikator", () => {
    const { store } = setup();
    const res = store.handle({ method: "get", url: `/api/candidates/${first.candidate_id}` }) as { status: number; data: { id: number; name: string; lastname: string } };
    expect(res.status).toBe(200);
    expect(res.data).toMatchObject({ id: first.candidate_id, name: first.name, lastname: first.lastname });
  });

  it("notatka wraca na liście notatek osoby i zgłasza zdarzenie", () => {
    const { store, actions } = setup();
    store.handle({ method: "post", url: "/api/notes", body: { candidate_id: first.candidate_id, job_id: JOB, content: "Rozmowa: 140 zł/h, od grudnia" } });
    const list = (store.handle({ method: "get", url: "/api/notes", params: { candidate_id: first.candidate_id } }) as { data: { items: Array<{ content: string }> } }).data.items;
    expect(list[0].content).toBe("Rozmowa: 140 zł/h, od grudnia");
    expect(acted(actions)).toMatchObject({ type: "note", candidateId: first.candidate_id });
  });
});

describe("poligon: pomocnicze", () => {
  it("daty względne liczą się od teraz", () => {
    expect(resolveDates("@rel:-1", NOW)).toBe(new Date(NOW - 86_400_000).toISOString());
    expect(resolveDates("@reld:2", NOW)).toBe("2026-11-22");
  });

  it("identyfikator poligonu rozpoznaje tylko całe liczby z zakresu", () => {
    expect(mentionsPoligon("/api/jobs/990001")).toBe(true);
    expect(mentionsPoligon("/api/jobs/1990001")).toBe(false);
    expect(mentionsPoligon("/api/jobs/789167")).toBe(false);
  });
});

describe("poligon: ćwiczenia", () => {
  const ctx = { firstNew: { candidateId: first.candidate_id, fullName: `${first.name} ${first.lastname}` } };
  const judge = (id: string, action: PoligonAction) => EXERCISES.find((e) => e.id === id)!.judge!(action, ctx);
  const move = (over: Partial<Extract<PoligonAction, { type: "move" }>>): PoligonAction => ({
    type: "move", candidateId: first.candidate_id, fromStage: "new", toStage: "screening",
    rejectionReasonId: null, rejectionReasonName: null, rejectionNote: "", ...over,
  });

  it("przesunięcie zalicza tylko wskazaną osobę na Screening", () => {
    expect(judge("tablica-przesun", move({}))).toEqual({ done: true });
    expect(judge("tablica-przesun", move({ candidateId: second.candidate_id }))).toMatchObject({ done: false });
    expect(judge("tablica-przesun", move({ toStage: "verified" }))).toMatchObject({ done: false });
  });

  it("odrzucenie z „Inne” nie zalicza (także z opisem), powód finansowy zalicza", () => {
    expect(judge("panel-odrzuc", move({ toStage: "rejected", rejectionReasonName: "Inne (rejected)" }))).toMatchObject({ done: false });
    expect(judge("panel-odrzuc", move({ toStage: "rejected", rejectionReasonName: "Inne (rejected)", rejectionNote: "nie pasuje" }))).toMatchObject({ done: false });
    expect(judge("panel-odrzuc", move({ toStage: "rejected", rejectionReasonName: "Brak doświadczenia" }))).toMatchObject({ done: false });
    expect(judge("panel-odrzuc", move({ toStage: "rejected", rejectionReasonName: "Za wysokie oczekiwania finansowe" }))).toEqual({ done: true });
  });

  it("za krótka notatka nie zalicza", () => {
    expect(judge("panel-notatka", { type: "note", candidateId: 1, content: "ok" })).toMatchObject({ done: false });
    expect(judge("panel-notatka", { type: "note", candidateId: 1, content: "Rozmowa: 140 zł/h, dostępna od grudnia, chce banku." })).toEqual({ done: true });
  });
});

describe("poligon: screening i bramka „Zweryfikowany”", () => {
  const screeningPerson = () => {
    const board = createPoligonStore(DATA, NOW).handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: Board };
    return board.data.columns.find((c) => c.stage === "screening")!.items[0].candidate_id;
  };
  const verifiedDef = () => (createPoligonStore(DATA, NOW).handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: Board }).data.columns.find((c) => c.stage === "verified")!.stage_def_id;

  it("bez screeningu ruch na „Zweryfikowany” dostaje odmowę serwera z brakami", () => {
    const { store, actions } = setup();
    const cid = screeningPerson();
    const res = store.handle({ method: "post", url: "/api/pipeline/move", body: { candidate_id: cid, job_id: JOB, stage_def_id: verifiedDef() } });
    expect(res).toMatchObject({ status: 409, data: { detail: { code: "VERIFIED_REQUIREMENTS_MISSING", missing: ["screening_sheet"] } } });
    expect(store.stageOf(cid)).toBe("screening");
    expect(acted(actions)).toMatchObject({ type: "gate", candidateId: cid });
    const req = store.handle({ method: "get", url: `/api/pipeline/move-requirements?candidate_id=${cid}&job_id=${JOB}&to_stage_def_id=${verifiedDef()}` });
    expect(req).toMatchObject({ status: 200, data: { primary: { kind: "blocked" } } });
  });

  it("zapisany screening z polami karty otwiera bramkę i wraca w formularzu", () => {
    const { store, actions } = setup();
    const cid = screeningPerson();
    const saved = store.handle({
      method: "put",
      url: "/api/screening-form",
      body: {
        candidate_id: cid, job_id: JOB, expected_version: 0, state_token: "poligon",
        sheet: { answers: [{ question_id: "q1", response: "Tak, 5 lat", deal_breaker_hit: false, origin: "manual" }], experience_checks: [], overall_fit: "fit" },
        card: { fields: { location: "Gdańsk", work_mode: "hybrid", recommendation: "Prowadziła migrację płatności w banku." } },
        rate: null, note_import: null,
      },
    });
    expect(saved).toMatchObject({ status: 200, data: { saved_version: 1 } });
    expect(acted(actions)).toMatchObject({ type: "screening", candidateId: cid, sheetSaved: true });
    const form = store.handle({ method: "get", url: `/api/screening-form?candidate_id=${cid}&job_id=${JOB}` }) as { data: { sheet: unknown; card: { fields: Record<string, string> } } };
    expect(form.data.sheet).not.toBeNull();
    expect(form.data.card.fields.recommendation).toContain("migrację");
    const req = store.handle({ method: "get", url: `/api/pipeline/move-requirements?candidate_id=${cid}&job_id=${JOB}&to_stage_def_id=${verifiedDef()}` });
    expect(req).toMatchObject({ data: { primary: { kind: "move" } } });
    expect(store.handle({ method: "post", url: "/api/pipeline/move", body: { candidate_id: cid, job_id: JOB, stage_def_id: verifiedDef() } })).toMatchObject({ status: 200 });
    expect(store.stageOf(cid)).toBe("verified");
  });

  it("screening jednej osoby nie otwiera bramki drugiej", () => {
    const { store } = setup();
    const board = store.handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: Board };
    const [a, b] = board.data.columns.find((c) => c.stage === "screening")!.items.map((i) => i.candidate_id);
    store.handle({ method: "put", url: "/api/screening-form", body: { candidate_id: a, job_id: JOB, sheet: { answers: [] }, card: { fields: { location: "x", work_mode: "y", recommendation: "z" } } } });
    expect(store.handle({ method: "post", url: "/api/pipeline/move", body: { candidate_id: b, job_id: JOB, stage_def_id: verifiedDef() } })).toMatchObject({ status: 409 });
  });
});

describe("poligon: baza kandydatów", () => {
  it("lista bazy to osoby ćwiczebne, szukanie zawęża i zgłasza zdarzenie", () => {
    const { store, actions } = setup();
    const all = store.handle({ method: "get", url: "/api/candidates?page=1&page_size=50" }) as { data: { items: Array<{ id: number; name: string }>; total: number } };
    expect(all.data.items.length).toBe(DATA.meta.people.length);
    expect(all.data.items.every((c) => c.id >= 990_000)).toBe(true);
    const found = store.handle({ method: "get", url: `/api/candidates?q=${encodeURIComponent(first.lastname)}` }) as { data: { items: Array<{ id: number }> } };
    expect(found.data.items.map((c) => c.id)).toEqual([first.candidate_id]);
    expect(actions.at(-1)).toMatchObject({ type: "view", path: "/api/candidates", query: { q: first.lastname } });
  });

  it("przypisanie z profilu dokłada osobę do „Nowych” rekrutacji ćwiczebnej", () => {
    const { store, actions } = setup();
    const last = DATA.meta.people.at(-1)!;
    expect(store.stageOf(last.candidate_id)).toBeNull();
    expect(store.handle({ method: "post", url: `/api/candidates/${last.candidate_id}/assign-to-job/${JOB}` })).toMatchObject({ status: 200 });
    expect(store.stageOf(last.candidate_id)).toBe("new");
    expect(acted(actions)).toMatchObject({ type: "assign", candidateId: last.candidate_id, jobId: JOB });
  });
});

describe("poligon: postęp i rejestr serwera", () => {
  it("zaliczenie ćwiczenia jako jedyny zapis idzie do API", () => {
    const { store } = setup();
    expect(POLIGON_PROGRESS.test("/api/novelties/poligon-baza-szukaj/events")).toBe(true);
    expect(store.handle({ method: "post", url: "/api/novelties/poligon-baza-szukaj/events", body: { event: "used" } })).toBe("network");
    expect(store.handle({ method: "post", url: "/api/novelties/inna-nowosc/events", body: { event: "seen" } })).toEqual({ status: 204, data: null });
  });

  it("ćwiczenia frontu i rejestr serwera to te same id", () => {
    expect(poligonRegistry.exercises.map((e) => e.id)).toEqual(EXERCISES.map((e) => `poligon-${e.id}`));
    expect(new Set(EXERCISES.map((e) => e.id)).size).toBe(EXERCISES.length);
  });

  it("ćwiczenia screeningu oceniają braki i bramkę", () => {
    const ctx = { firstNew: null };
    const judge = (id: string, action: PoligonAction) => EXERCISES.find((e) => e.id === id)!.judge!(action, ctx);
    expect(judge("screening-bramka", { type: "gate", candidateId: 1, missing: ["Arkusz screeningu"] })).toEqual({ done: true });
    expect(judge("screening-zapisz", { type: "screening", candidateId: 1, sheetSaved: true, fields: { location: "Gdańsk" } })).toMatchObject({ done: false });
    expect(judge("screening-zapisz", { type: "screening", candidateId: 1, sheetSaved: true, fields: { location: "a", work_mode: "b", recommendation: "c" } })).toEqual({ done: true });
    expect(judge("screening-zweryfikuj", { type: "gate", candidateId: 1, missing: ["Tryb pracy"] })).toMatchObject({ done: false });
    expect(judge("panel-wzmianka", { type: "note", candidateId: 1, content: "Bez oznaczenia nikogo w zespole" })).toMatchObject({ done: false });
    expect(judge("panel-wzmianka", { type: "note", candidateId: 1, content: "@Anna Poligonowa czy stawka 140 jest ok?" })).toEqual({ done: true });
    expect(judge("rekomendacja-qc", { type: "move", candidateId: 1, fromStage: "verified", toStage: "cv_sent", rejectionReasonId: null, rejectionReasonName: null, rejectionNote: "" })).toMatchObject({ done: false });
    expect(judge("rekomendacja-qc", { type: "move", candidateId: 1, fromStage: "verified", toStage: "interview", rejectionReasonId: null, rejectionReasonName: null, rejectionNote: "" })).toEqual({ done: true });
  });
});

vi.useRealTimers();
