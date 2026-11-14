import { describe, expect, it, vi } from "vitest";

import dataset from "../dataset.json";
import { LEVEL_1 } from "../exercises";
import { BLOCKED_WRITE_MESSAGE, createPoligonStore, mentionsPoligon, resolveDates, type PoligonAction, type PoligonDataset } from "../store";

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
    expect(actions.at(-1)).toMatchObject({ type: "missing" });
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
    expect(actions.at(-1)).toMatchObject({ type: "move", candidateId: first.candidate_id, fromStage: "new", toStage: "screening" });
  });

  it("odrzucenie niesie nazwę powodu z szablonu rekrutacji", () => {
    const { store, actions } = setup();
    const reasons = (DATA.responses["GET /api/pipeline-templates/1"] as { rejection_reasons: Array<{ id: number; name: string }> }).rejection_reasons;
    const finansowy = reasons.find((r) => r.name.toLowerCase().includes("finans"))!;
    store.handle({ method: "post", url: "/api/pipeline/move", body: { candidate_id: first.candidate_id, job_id: JOB, stage: "rejected", rejection_reason_id: finansowy.id } });
    expect(actions.at(-1)).toMatchObject({ type: "move", toStage: "rejected", rejectionReasonName: finansowy.name });
  });

  it("„Biorę” oznacza osobę jako Twoją", () => {
    const { store, actions } = setup();
    store.handle({ method: "post", url: "/api/pipeline/claim", body: { candidate_id: second.candidate_id, job_id: JOB } });
    const board = (store.handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: Board }).data;
    const item = board.columns.flatMap((c) => c.items).find((i) => i.candidate_id === second.candidate_id)!;
    expect(item.taken_by_name).toBe("Ty");
    expect(actions.at(-1)).toEqual({ type: "claim", candidateId: second.candidate_id });
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
    expect(actions.at(-1)).toMatchObject({ type: "note", candidateId: first.candidate_id });
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
  const judge = (id: string, action: PoligonAction) => LEVEL_1.find((e) => e.id === id)!.judge!(action, ctx);
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

vi.useRealTimers();
