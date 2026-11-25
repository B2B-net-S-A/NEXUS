import { describe, expect, it, vi } from "vitest";

import dataset from "../dataset.json";
import poligonRegistry from "../../../../../backend/app/data/novelties/poligon.json";
import { EXERCISES, POLIGON_BUDGET_MAX_HOURLY, POLIGON_CANDIDATE_HOURLY, POLIGON_CLIENT_MAIL, exercisesFor, primaryRole } from "../exercises";
import { SLOTS_MAIL_OTHER } from "../tools";
import { poligonPath } from "../usePoligonPath";
import type { BoardTasksResponse } from "@/lib/api/boardTasks";
import { buildPersonQueue } from "@/lib/dashboard-person-queue";
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

  it("„Klient coś zmienił” na rekrutacji ćwiczebnej nie woła modelu ani nie zapisuje (lekcja nowości)", () => {
    const { store } = setup();
    for (const url of [
      "/api/jobs/990001/champion-profile/client-change",
      "/api/jobs/990001/champion-profile/client-change/apply",
    ]) {
      const res = store.handle({ method: "post", url, body: { text: "Python jako musi mieć" } });
      expect(res).toEqual({ status: 409, data: { detail: BLOCKED_WRITE_MESSAGE } });
    }
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

  it("nagrane 404 (rekrutacja bez migawki rekomendacji) to odpowiedź, nie brak w zestawie", () => {
    const { store, actions } = setup();
    const res = store.handle({ method: "get", url: `/api/jobs/${JOB}/proposals/latest` });
    expect(res).toMatchObject({ status: 404 });
    expect(actions.some((a) => a.type === "missing")).toBe(false);
  });

  it("ostatni przegląd bazy na rekrutacji ćwiczebnej jest pusty, nie brakuje go", () => {
    const { store, actions } = setup();
    const res = store.handle({ method: "get", url: `/api/candidate-search/jobs/${JOB}/latest-run` });
    expect(res).toMatchObject({ status: 200, data: { job_id: JOB, run: null } });
    expect(actions.some((a) => a.type === "missing")).toBe(false);
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
  const ctx = { firstNew: { candidateId: first.candidate_id, fullName: `${first.name} ${first.lastname}` }, role: "recruiter" as const };
  const judge = (id: string, action: PoligonAction) => EXERCISES.find((e) => e.id === id)!.judge!(action, ctx);
  const move = (over: Partial<Extract<PoligonAction, { type: "move" }>>): PoligonAction => ({
    type: "move", candidateId: first.candidate_id, fromStage: "new", toStage: "screening",
    rejectionReasonId: null, rejectionReasonName: null, rejectionNote: "", fixFields: [], clientRate: null, ...over,
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

describe("poligon: „Czeka na Ciebie” na pulpicie", () => {
  // 24.11.2026 lekcja „Pracuj po kolei” była nie do zrobienia dla DL-a i TCM-a
  // bez własnych kart: odczyt szedł do prawdziwego API. Na Poligonie kolejka to
  // osoby ćwiczebne, więc przycisk stoi u każdego.
  it("odpowiada z zestawu osobami ćwiczebnymi, a kolejka „Pracuj po kolei” nie jest pusta", () => {
    const { store } = setup();
    const res = store.handle({ method: "get", url: "/api/board-tasks" });
    expect(res).not.toBe("network");
    const data = (res as { status: number; data: BoardTasksResponse }).data;
    const queue = buildPersonQueue(data.flow, new Date(NOW));
    expect(queue.length).toBeGreaterThan(0);
    const people = new Set(DATA.meta.people.map((p) => p.candidate_id));
    expect(queue.every((entry) => people.has(entry.candidateId) && entry.jobId === JOB)).toBe(true);
  });
});

describe("poligon: plan przelewów", () => {
  // Lekcja „Zajęcia i spory” (25.11.2026): POST planu to odczyt, a Poligon
  // odpowiadał na niego 409 i ekran Przelewów pokazywał błąd pobrania.
  it("POST planu to odczyt z zestawu z fakturą przypiętą do kontraktu ćwiczebnego", () => {
    const { store } = setup();
    const res = store.handle({ method: "post", url: "/api/finance/payments/plan", body: { until: "2026-11-27" } });
    expect(res).toMatchObject({ status: 200 });
    const items = (res as { data: { items: Array<{ contract_id: number | null }> } }).data.items;
    expect(items.some((i) => i.contract_id === 990521)).toBe(true);
  });
});

describe("poligon: baza kandydatów", () => {
  it("lista bazy to osoby ćwiczebne, szukanie zawęża i zgłasza zdarzenie", () => {
    const { store, actions } = setup();
    const all = store.handle({ method: "get", url: "/api/candidates?page=1&page_size=50" }) as { data: { items: Array<{ id: number; name: string }>; total: number } };
    // Osoba z „Rozmowy u klienta”, osoba z pliku CV (ćwiczenia z 16.11.2026) i osoba
    // z „CV wysłane” (lekcja „Terminy przy ruchu”, 25.11.2026) nie są w bazie z nagrania.
    const meta = DATA.meta as PoligonDataset["meta"] & { terms_candidate_id: number };
    const extras = new Set([meta.slot_candidate_id, meta.cv_candidate_id, meta.terms_candidate_id]);
    expect(all.data.items.length).toBe(DATA.meta.people.filter((p) => !extras.has(p.candidate_id)).length);
    expect(all.data.items.every((c) => c.id >= 990_000)).toBe(true);
    const found = store.handle({ method: "get", url: `/api/candidates?q=${encodeURIComponent(first.lastname)}` }) as { data: { items: Array<{ id: number }> } };
    expect(found.data.items.map((c) => c.id)).toEqual([first.candidate_id]);
    expect(actions.at(-1)).toMatchObject({ type: "view", path: "/api/candidates", query: { q: first.lastname } });
  });

  it("przypisanie z profilu dokłada osobę do „Nowych” rekrutacji ćwiczebnej", () => {
    const { store, actions } = setup();
    // Osoba z pliku CV nie stoi na Tablicy, więc da się ją przypisać z profilu.
    const last = DATA.meta.people.find((p) => p.candidate_id === DATA.meta.cv_candidate_id)!;
    expect(store.stageOf(last.candidate_id)).toBeNull();
    expect(store.handle({ method: "post", url: `/api/candidates/${last.candidate_id}/assign-to-job/${JOB}` })).toMatchObject({ status: 200 });
    expect(store.stageOf(last.candidate_id)).toBe("new");
    expect(acted(actions)).toMatchObject({ type: "assign", candidateId: last.candidate_id, jobId: JOB });
  });
});

describe("poligon: ścieżka per rola", () => {
  const ids = (roles: string[]) => exercisesFor(roles).map((e) => e.id);

  it("Delivery Lead: wspólne moduły i przegląd DL, bez screeningu i „Biorę”", () => {
    const dl = ids(["delivery_lead"]);
    expect(dl).toEqual(expect.arrayContaining(["lista-zakres", "tablica-przesun", "panel-odrzuc", "baza-przypisz", "dl-przeglad-otworz", "dl-wyslij", "dl-poprawki", "dl-terminy-klienta"]));
    expect(dl).not.toContain("tablica-biore");
    expect(dl.filter((id) => id.startsWith("screening-"))).toEqual([]);
    expect(dl).not.toContain("rekomendacja-qc");
  });

  it("TCM: wspólne moduły Startu, bez ćwiczeń rekrutera i DL-a", () => {
    const tcm = exercisesFor(["talent_community_manager"]);
    expect([...new Set(tcm.map((e) => e.module))]).toEqual(["Lista rekrutacji", "Tablica", "Panel osoby", "Baza kandydatów"]);
    expect(tcm.some((e) => e.id.startsWith("dl-") || e.id.startsWith("screening-"))).toBe(false);
  });

  it("rekruter ma 27 ćwiczeń (19 z 14.11 i 8 narzędzi z 16.11), osoba z dwiema rolami — sumę", () => {
    expect(ids(["recruiter"])).toHaveLength(27);
    expect(ids(["talent_community_manager"])).toHaveLength(13);
    expect(ids(["delivery_lead"])).toHaveLength(17);
    expect(ids(["recruiter"]).some((id) => id.startsWith("dl-"))).toBe(false);
    const both = ids(["delivery_lead", "recruiter"]);
    expect(both).toEqual(EXERCISES.filter((e) => both.includes(e.id)).map((e) => e.id));
    expect(both).toEqual(expect.arrayContaining(["screening-zapisz", "dl-wyslij"]));
    expect(ids(["admin"])).toHaveLength(EXERCISES.length);
    expect(ids(["finance"])).toEqual([]);
  });

  it("ścieżki ról zgadzają się z rejestrem serwera", () => {
    for (const role of ["recruiter", "delivery_lead", "talent_community_manager"]) {
      expect(ids([role]).map((id) => `poligon-${id}`)).toEqual(poligonRegistry.exercises.filter((e) => e.roles.includes(role)).map((e) => e.id));
    }
  });

  it("wymagany poligon idzie po liście z serwera: po zmianie roli tylko brakujące ćwiczenia nowej roli", () => {
    const dlOnly = ["poligon-dl-przeglad-otworz", "poligon-dl-wyslij", "poligon-dl-poprawki"];
    const status = { open: true, required: true, exercise_ids: dlOnly, done_ids: [], done: 0, total: 3 };
    expect(poligonPath(["delivery_lead"], status).map((e) => e.id)).toEqual(["dl-przeglad-otworz", "dl-wyslij", "dl-poprawki"]);
    // Bez wymogu (obecna osoba) albo ze starszego serwera bez listy — cała ścieżka ról.
    expect(poligonPath(["delivery_lead"], { ...status, required: false })).toEqual(exercisesFor(["delivery_lead"]));
    expect(poligonPath(["delivery_lead"], { ...status, exercise_ids: undefined })).toEqual(exercisesFor(["delivery_lead"]));
    expect(poligonPath(["delivery_lead"], null)).toEqual(exercisesFor(["delivery_lead"]));
  });

  it("treść mówi z perspektywy roli: DL oznacza rekrutera, rekruter — DL-a", () => {
    const wzmianka = EXERCISES.find((e) => e.id === "panel-wzmianka")!;
    expect(wzmianka.task({ firstNew: null, role: primaryRole(["delivery_lead"]) })).toContain("Jakub Szkoleniowy");
    expect(wzmianka.task({ firstNew: null, role: primaryRole(["recruiter", "delivery_lead"]) })).toContain("Anna Poligonowa");
  });
});

describe("poligon: przegląd Delivery Leada", () => {
  const ctx = { firstNew: null, role: "delivery_lead" as const };
  const judge = (id: string, action: PoligonAction) => EXERCISES.find((e) => e.id === id)!.judge!(action, ctx);
  const fromQc = (over: Partial<Extract<PoligonAction, { type: "move" }>>): PoligonAction => ({
    type: "move", candidateId: 1, fromStage: "interview", toStage: "cv_sent",
    rejectionReasonId: null, rejectionReasonName: null, rejectionNote: "", fixFields: [], clientRate: null, ...over,
  });
  const rate = (value: number, unit = "hourly", currency = "PLN") => ({ value, unit, currency });
  const board = (store: ReturnType<typeof createPoligonStore>) => (store.handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: Board }).data;

  it("otwarcie przeglądu zalicza odczyt kontekstu przeglądu", () => {
    expect(judge("dl-przeglad-otworz", { type: "view", path: "/api/dl-review/context", query: {} })).toEqual({ done: true });
    expect(judge("dl-przeglad-otworz", { type: "view", path: "/api/screening-form", query: {} })).toBeNull();
  });

  it("wysyłka: stawka w budżecie i powyżej stawki kandydata zalicza", () => {
    expect(judge("dl-wyslij", fromQc({ clientRate: rate(POLIGON_BUDGET_MAX_HOURLY) }))).toEqual({ done: true });
    expect(judge("dl-wyslij", fromQc({ clientRate: rate(112 * 8, "daily") }))).toEqual({ done: true });
  });

  it("wysyłka: ponad budżet, bez marży, w innej walucie albo bez stawki — nie zalicza", () => {
    expect(judge("dl-wyslij", fromQc({ clientRate: rate(POLIGON_BUDGET_MAX_HOURLY + 1) }))).toMatchObject({ done: false, feedback: expect.stringContaining("ponad budżet") });
    expect(judge("dl-wyslij", fromQc({ clientRate: rate(POLIGON_CANDIDATE_HOURLY) }))).toMatchObject({ done: false, feedback: expect.stringContaining("nic nie zarabia") });
    expect(judge("dl-wyslij", fromQc({ clientRate: rate(30, "hourly", "EUR") }))).toMatchObject({ done: false });
    expect(judge("dl-wyslij", fromQc({ clientRate: null }))).toMatchObject({ done: false });
    expect(judge("dl-wyslij", fromQc({ fromStage: "verified", clientRate: rate(110) }))).toBeNull();
  });

  it("„Wróć do poprawy” zalicza tylko z zaznaczonymi polami", () => {
    expect(judge("dl-poprawki", fromQc({ toStage: "verified", fixFields: ["field:english"] }))).toEqual({ done: true });
    expect(judge("dl-poprawki", fromQc({ toStage: "verified", fixFields: [] }))).toMatchObject({ done: false });
    expect(judge("dl-poprawki", fromQc({ toStage: "rejected" }))).toBeNull();
  });

  it("kolumna „QC CV” ma osoby gotowe do przeglądu, a przegląd każdej z nich ma jej imię i fikcyjne kwoty", () => {
    const { store } = setup();
    const qc = board(store).columns.find((c) => c.stage === "interview")!;
    expect(qc.items.length).toBeGreaterThanOrEqual(2);
    const person = DATA.meta.people.find((p) => p.candidate_id === qc.items[0].candidate_id)!;
    const ctxRes = store.handle({ method: "get", url: `/api/dl-review/context?candidate_id=${person.candidate_id}&job_id=${JOB}` }) as {
      status: number; data: { candidate_id: number; candidate_name: string; budget: { max_hourly: number }; candidate_rate: { hourly_pln: number } };
    };
    expect(ctxRes.status).toBe(200);
    expect(ctxRes.data).toMatchObject({ candidate_id: person.candidate_id, candidate_name: `${person.name} ${person.lastname}` });
    expect(ctxRes.data.budget.max_hourly).toBe(POLIGON_BUDGET_MAX_HOURLY);
    expect(ctxRes.data.candidate_rate.hourly_pln).toBe(POLIGON_CANDIDATE_HOURLY);
    const row = store.handle({ method: "get", url: `/api/board-tasks/dl-review-row?candidate_id=${person.candidate_id}&job_id=${JOB}` }) as { data: { row: { candidate_id: number; stage_id: number } } };
    expect(row.data.row).toMatchObject({ candidate_id: person.candidate_id, stage_id: person.entry_id });
  });

  it("wysyłka i zwrot z przeglądu to ruch karty w pamięci z polami przeglądu", () => {
    const { store, actions } = setup();
    const columns = board(store).columns;
    const [a, b] = columns.find((c) => c.stage === "interview")!.items.map((i) => i.candidate_id);
    const sent = columns.find((c) => c.stage === "cv_sent")!.stage_def_id;
    const verified = columns.find((c) => c.stage === "verified")!.stage_def_id;
    expect(store.handle({ method: "post", url: "/api/pipeline/move", body: { candidate_id: a, job_id: JOB, stage_def_id: sent, client_rate_value: 112, client_rate_unit: "hourly", client_rate_currency: "PLN" } })).toMatchObject({ status: 200 });
    expect(acted(actions)).toMatchObject({ type: "move", fromStage: "interview", toStage: "cv_sent", clientRate: { value: 112, unit: "hourly", currency: "PLN" } });
    expect(store.handle({ method: "post", url: "/api/pipeline/move", body: { candidate_id: b, job_id: JOB, stage_def_id: verified, fix_fields: ["field:english", "cv"] } })).toMatchObject({ status: 200 });
    expect(acted(actions)).toMatchObject({ type: "move", fromStage: "interview", toStage: "verified", fixFields: ["field:english", "cv"] });
    expect(store.stageOf(a)).toBe("cv_sent");
    expect(store.stageOf(b)).toBe("verified");
  });

  it("podgląd maila odrzucenia w przeglądzie to odczyt, nie zapis", () => {
    const { store } = setup();
    expect(store.handle({ method: "post", url: "/api/rejection-emails/preview", body: { candidate_ids: [first.candidate_id] } })).toMatchObject({ status: 200 });
  });
});

describe("poligon: terminy od klienta Delivery Leada (16.11.2026)", () => {
  const VIEWER = 4243;
  const ctx = { firstNew: null, role: "delivery_lead" as const };
  const judge = (action: PoligonAction) => EXERCISES.find((e) => e.id === "dl-terminy-klienta")!.judge!(action, ctx);
  type Item = { candidate_id: number; stage: string; interview_badge?: { kind: string; label: string; slot_request?: { id: number; status: string; duration_minutes: number; slots: Array<{ start: string; end: string }> } } | null };
  const items = (store: ReturnType<typeof createPoligonStore>) =>
    (store.handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: { columns: Array<{ items: Item[] }> } }).data.columns.flatMap((c) => c.items);
  const weronika = DATA.meta.people.find((p) => p.name === "Weronika")!;
  const slotPerson = DATA.meta.slot_candidate_id;
  /** Jutro i pojutrze o 10:00 i 13:00 czasu lokalnego — w przyszłości względem zegara testu. */
  const at = (days: number, hour: number) => {
    const d = new Date(Date.now() + days * 86_400_000);
    d.setHours(hour, 0, 0, 0);
    return d.toISOString();
  };
  const send = (store: ReturnType<typeof createPoligonStore>, over: Record<string, unknown> = {}) =>
    store.handle({
      method: "post",
      url: "/api/interview-cycle/slots",
      body: { candidate_id: weronika.candidate_id, job_id: JOB, slots: [{ start: at(2, 13) }, { start: at(1, 10) }], duration_minutes: 45, respond_by: null, note: null, ...over },
      viewerId: VIEWER,
    });
  /** Weronika po wysyłce do klienta („QC CV” → „CV wysłane”), jak w ścieżce DL-a. */
  const sent = () => {
    const ctx = setup();
    ctx.store.handle({ method: "post", url: "/api/pipeline/move", body: { candidate_id: weronika.candidate_id, stage: "cv_sent", client_rate_value: 112 } });
    return ctx;
  };

  it("terminy DL-a zostają w pamięci: karta jedzie na „Rozmowę u klienta” z odznaką wyboru dla rekrutera", () => {
    const { store, actions } = sent();
    const res = send(store);
    expect(res).toMatchObject({ status: 201, data: { status: "awaiting_recruiter", duration_minutes: 45, created_by: VIEWER, moved_to_client_interview: true } });
    const card = items(store).find((i) => i.candidate_id === weronika.candidate_id)!;
    expect(card.stage).toBe("client_interview");
    expect(card.interview_badge).toMatchObject({ kind: "choose_slot", label: "Wybierz termin · 2 propozycje" });
    const slots = card.interview_badge!.slot_request!.slots;
    // Terminy po kolei, koniec = początek + długość rozmowy.
    expect(slots.map((s) => s.start)).toEqual([at(1, 10), at(2, 13)]);
    expect(new Date(slots[0].end).getTime() - new Date(slots[0].start).getTime()).toBe(45 * 60_000);
    expect(acted(actions)).toEqual({ type: "slot_request", candidateId: weronika.candidate_id, starts: [at(1, 10), at(2, 13)], durationMinutes: 45, replaced: false });
    expect(judge(acted(actions)!)).toEqual({ done: true });
    // Rekruter wybiera z tego wniosku jak z nagranego.
    const id = card.interview_badge!.slot_request!.id;
    expect(store.handle({ method: "post", url: `/api/interview-cycle/slots/${id}/choose`, body: { index: 0 } })).toMatchObject({ status: 200, data: { status: "awaiting_dl" } });
  });

  it("drugi wniosek bez zastąpienia dostaje 409 z otwartym wnioskiem, „Zastąp” podmienia terminy", () => {
    const { store, actions } = sent();
    const first = send(store, { duration_minutes: 60 }) as { data: { id: number } };
    expect(judge(acted(actions)!)).toMatchObject({ done: false, feedback: expect.stringContaining("45 minutach") });
    const again = send(store);
    expect(again).toMatchObject({ status: 409, data: { detail: { code: "SLOTS_ALREADY_OPEN", open_request_id: first.data.id } } });
    expect(send(store, { replaces_request_id: first.data.id })).toMatchObject({ status: 201, data: { moved_to_client_interview: false } });
    expect(acted(actions)).toMatchObject({ type: "slot_request", replaced: true });
    expect(judge(acted(actions)!)).toEqual({ done: true });
    // Osoba z nagranym wnioskiem też ma otwarte terminy.
    expect(store.handle({ method: "post", url: "/api/interview-cycle/slots", body: { candidate_id: slotPerson, job_id: JOB, slots: [{ start: at(1, 10) }], duration_minutes: 45 } })).toMatchObject({ status: 409 });
  });

  it("nie te godziny, przeszłość, zły etap i osoba spoza rekrutacji — bez zaliczenia albo z odmową", () => {
    const { store, actions } = sent();
    send(store, { slots: [{ start: at(1, 9) }, { start: at(2, 13) }] });
    expect(judge(acted(actions)!)).toMatchObject({ done: false, feedback: expect.stringContaining("10:00") });
    const fresh = sent().store;
    expect(send(fresh, { slots: [{ start: new Date(Date.now() - 3_600_000).toISOString() }] })).toMatchObject({ status: 422 });
    expect(send(fresh, { slots: [] })).toMatchObject({ status: 422 });
    const qc = setup().store;
    expect(send(qc)).toMatchObject({ status: 422, data: { detail: expect.stringContaining("CV wysłane") } });
    expect(send(fresh, { candidate_id: 123 })).toMatchObject({ status: 422 });
    expect(send(fresh, { job_id: 990002 })).toMatchObject({ status: 422 });
  });

  it("„Wklej maila od klienta” bez modelu: mail z ćwiczenia daje stały odczyt, inny tekst — jasną odmowę", () => {
    const { store } = setup();
    const read = store.handle({ method: "post", url: "/api/interview-cycle/slots/from-mail", body: { text: POLIGON_CLIENT_MAIL, mail_date: null } }) as {
      status: number;
      data: { status: string; duration_minutes: number; slots: Array<{ start: string; quote: string }> };
    };
    expect(read).toMatchObject({ status: 200, data: { status: "ok", duration_minutes: 45 } });
    expect(read.data.slots.map((s) => new Date(s.start).getHours())).toEqual([10, 13]);
    for (const slot of read.data.slots) {
      expect(new Date(slot.start).getTime()).toBeGreaterThan(NOW);
      expect([0, 6]).not.toContain(new Date(slot.start).getDay());
      expect(POLIGON_CLIENT_MAIL).toContain(slot.quote);
    }
    expect(store.handle({ method: "post", url: "/api/interview-cycle/slots/from-mail", body: { text: "Pasuje nam piątek rano." } })).toEqual({
      status: 200,
      data: expect.objectContaining({ status: "empty", message: SLOTS_MAIL_OTHER, slots: [] }),
    });
  });

  it("adresat terminów to rekruter poligonu, a odczyt nie jest brakiem w zestawie", () => {
    const { store, actions } = setup();
    expect(store.handle({ method: "get", url: `/api/interview-cycle/slots/recipient?candidate_id=${weronika.candidate_id}&job_id=${JOB}` })).toEqual({
      status: 200,
      data: { recruiter_name: DATA.meta.trainers.rec.name, substitute_name: null, until: null },
    });
    expect(actions.some((a) => a.type === "missing")).toBe(false);
  });
});

describe("poligon: postęp i rejestr serwera", () => {
  it("zaliczenie ćwiczenia jako jedyny zapis idzie do API", () => {
    const { store } = setup();
    expect(POLIGON_PROGRESS.test("/api/novelties/poligon-baza-szukaj/events")).toBe(true);
    expect(store.handle({ method: "post", url: "/api/novelties/poligon-baza-szukaj/events", body: { event: "used" } })).toBe("network");
    expect(store.handle({ method: "post", url: "/api/novelties/inna-nowosc/events", body: { event: "seen" } })).toEqual({ status: 204, data: null });
  });

  it("przeklikanie nowości z porcji dnia zalicza się na serwerze, inne zdarzenia nowości nie", () => {
    const { store } = setup();
    expect(store.handle({ method: "post", url: "/api/novelties/inna-nowosc/events", body: { event: "toured" } })).toBe("network");
    for (const event of ["used", "dot_clicked", "postponed"])
      expect(store.handle({ method: "post", url: "/api/novelties/inna-nowosc/events", body: { event } })).toEqual({ status: 204, data: null });
    // Gate i panel to nie zdarzenie osoby — zostają w przeglądarce.
    expect(store.handle({ method: "put", url: "/api/novelties/start/gate", body: { event: "toured" } })).toEqual({ status: 204, data: null });
  });

  it("każdy etap lekcji nowości idzie na serwer — inaczej porcja blokowałaby bez końca (23.11.2026)", () => {
    const { store } = setup();
    for (const event of ["shown", "solo_failed", "solo_passed", "quiz_wrong", "restart", "completed", "review_passed", "review_failed"])
      expect(store.handle({ method: "post", url: "/api/novelties/lessons/lekcja-porcja-karta/events", body: { event } })).toBe("network");
    // Odczyt lekcji do Szkoleń też idzie do API, nie do zestawu ćwiczebnego.
    expect(store.handle({ method: "get", url: "/api/novelties/lessons" })).toBe("network");
  });

  it("ćwiczenia frontu i rejestr serwera to te same id i te same role", () => {
    expect(poligonRegistry.exercises.map((e) => e.id)).toEqual(EXERCISES.map((e) => `poligon-${e.id}`));
    expect(new Set(EXERCISES.map((e) => e.id)).size).toBe(EXERCISES.length);
    const roles = Object.fromEntries(poligonRegistry.exercises.map((e) => [e.id, [...e.roles].sort()]));
    expect(Object.fromEntries(EXERCISES.map((e) => [`poligon-${e.id}`, [...e.roles].sort()]))).toEqual(roles);
  });

  it("ćwiczenia screeningu oceniają braki i bramkę", () => {
    const ctx = { firstNew: null, role: "recruiter" as const };
    const judge = (id: string, action: PoligonAction) => EXERCISES.find((e) => e.id === id)!.judge!(action, ctx);
    expect(judge("screening-bramka", { type: "gate", candidateId: 1, missing: ["Arkusz screeningu"] })).toEqual({ done: true });
    expect(judge("screening-zapisz", { type: "screening", candidateId: 1, sheetSaved: true, fields: { location: "Gdańsk" } })).toMatchObject({ done: false });
    expect(judge("screening-zapisz", { type: "screening", candidateId: 1, sheetSaved: true, fields: { location: "a", work_mode: "b", recommendation: "c" } })).toEqual({ done: true });
    expect(judge("screening-zweryfikuj", { type: "gate", candidateId: 1, missing: ["Tryb pracy"] })).toMatchObject({ done: false });
    expect(judge("panel-wzmianka", { type: "note", candidateId: 1, content: "Bez oznaczenia nikogo w zespole" })).toMatchObject({ done: false });
    expect(judge("panel-wzmianka", { type: "note", candidateId: 1, content: "@Anna Poligonowa czy stawka 140 jest ok?" })).toEqual({ done: true });
    const noExtras = { rejectionReasonId: null, rejectionReasonName: null, rejectionNote: "", fixFields: [], clientRate: null };
    expect(judge("rekomendacja-qc", { type: "move", candidateId: 1, fromStage: "verified", toStage: "cv_sent", ...noExtras })).toMatchObject({ done: false });
    expect(judge("rekomendacja-qc", { type: "move", candidateId: 1, fromStage: "verified", toStage: "interview", ...noExtras })).toEqual({ done: true });
  });
});

describe("poligon: narzędzia rekrutera (16.11.2026)", () => {
  const VIEWER = 4242;
  const ctx = { firstNew: null, role: "recruiter" as const };
  const judge = (id: string, action: PoligonAction) => EXERCISES.find((e) => e.id === id)!.judge!(action, ctx);
  const template = DATA.meta.people.find((p) => p.candidate_id === DATA.meta.template_candidate_id)!;
  const slotPerson = DATA.meta.people.find((p) => p.candidate_id === DATA.meta.slot_candidate_id)!;
  const cvPerson = DATA.meta.people.find((p) => p.candidate_id === DATA.meta.cv_candidate_id)!;
  type Item = { candidate_id: number; stage: string; booked_call?: { start_time: string } | null; interview_badge?: { slot_request?: { id: number; status: string; slots: Array<{ start: string }> } } };
  const board = (store: ReturnType<typeof createPoligonStore>) =>
    (store.handle({ method: "get", url: `/api/pipeline/kanban/${JOB}` }) as { data: { columns: Array<{ stage: string; items: Item[] }> } }).data;
  const item = (store: ReturnType<typeof createPoligonStore>, cid: number) =>
    board(store).columns.flatMap((c) => c.items).find((i) => i.candidate_id === cid);

  it("żaden zapis narzędzi nie wychodzi z przeglądarki", () => {
    const { store } = setup();
    const writes: Array<[string, string]> = [
      ["post", "/api/screening-calls"],
      ["post", "/api/interview-cycle/slots/990701/choose"],
      ["post", "/api/candidates/from-cv"],
      ["post", `/api/jobs/${JOB}/proposals/bulk`],
      ["post", "/api/saved-searches"],
      ["post", "/api/talent-pools"],
      ["post", `/api/jobs/${JOB}/chat/messages`],
      ["put", `/api/jobs/${JOB}/chat/read`],
      ["patch", `/api/candidates/stages/${DATA.meta.template_entry_id}/cv/branded`],
      ["post", `/api/pipeline/stages/${DATA.meta.template_entry_id}/cv-ai/command`],
      ["post", `/api/pipeline/stages/${DATA.meta.template_entry_id}/cv-ai/applied`],
    ];
    for (const [method, url] of writes) expect(store.handle({ method, url, body: {} })).not.toBe("network");
  });

  it("telefon screeningowy: karta pokazuje termin, poza „Nowymi” i „Screeningiem” odmowa", () => {
    const { store, actions } = setup();
    const start = "2026-11-21T08:00:00.000Z";
    const res = store.handle({ method: "post", url: "/api/screening-calls", body: { candidate_id: first.candidate_id, job_id: JOB, start, note: null, client_request_id: "x".repeat(20) }, viewerId: VIEWER });
    expect(res).toMatchObject({ status: 201, data: { start_time: start, outlook: "not_connected" } });
    expect(item(store, first.candidate_id)?.booked_call).toMatchObject({ start_time: start });
    expect(acted(actions)).toEqual({ type: "screening_call", candidateId: first.candidate_id, start });
    expect(judge("kalendarz-telefon", acted(actions)!)).toEqual({ done: true });
    expect(store.handle({ method: "post", url: "/api/screening-calls", body: { candidate_id: slotPerson.candidate_id, start } })).toMatchObject({ status: 409 });
  });

  it("termin u klienta: osoba czeka na wybór, terminy o pełnej godzinie w przyszłości, wybór idzie do DL-a", () => {
    const { store, actions } = setup();
    const card = item(store, slotPerson.candidate_id)!;
    expect(card.stage).toBe("client_interview");
    const request = card.interview_badge!.slot_request!;
    expect(request.status).toBe("awaiting_recruiter");
    for (const slot of request.slots) {
      expect(new Date(slot.start).getTime()).toBeGreaterThan(NOW);
      expect(new Date(slot.start).getUTCMinutes()).toBe(0);
    }
    const prep = store.handle({ method: "get", url: `/api/interview-cycle/preps/suggestions?candidate_id=${slotPerson.candidate_id}&job_id=${JOB}&interview_start=${encodeURIComponent(request.slots[1].start)}&prep1_minutes=45&prep2_minutes=45` });
    expect(prep).toMatchObject({ status: 200, data: { enabled: false } });
    expect(store.handle({ method: "post", url: `/api/interview-cycle/slots/${request.id}/choose`, body: { index: 1 } })).toMatchObject({ status: 200, data: { status: "awaiting_dl", chosen_index: 1 } });
    expect(item(store, slotPerson.candidate_id)!.interview_badge!.slot_request!.status).toBe("awaiting_dl");
    expect(store.handle({ method: "post", url: `/api/interview-cycle/slots/${request.id}/choose`, body: { index: 0 } })).toMatchObject({ status: 409 });
    expect(actions.some((a) => a.type === "missing")).toBe(false);
    expect(judge("kalendarz-termin-klienta", { type: "slot_choose", candidateId: slotPerson.candidate_id, index: 1 })).toEqual({ done: true });
    expect(judge("kalendarz-termin-klienta", { type: "slot_choose", candidateId: slotPerson.candidate_id, index: 0 })).toMatchObject({ done: false });
  });

  it("osoba z pliku CV: NEXUS „odczytuje” osobę ćwiczebną, a dodanie stawia ją w „Nowych”", () => {
    const { store, actions } = setup();
    const res = store.handle({ method: "post", url: "/api/candidates/from-cv", body: {} }) as { status: number; data: { candidate: { id: number; name: string; lastname: string }; confidence: Record<string, number> } };
    expect(res.status).toBe(201);
    expect(res.data.candidate).toMatchObject({ id: cvPerson.candidate_id, name: cvPerson.name, lastname: cvPerson.lastname });
    expect(Object.values(res.data.confidence).some((v) => v < 0.7)).toBe(true);
    expect(judge("zrodla-cv-z-pliku", acted(actions)!)).toEqual({ done: true });
    expect(store.stageOf(cvPerson.candidate_id)).toBeNull();
    expect(store.handle({ method: "post", url: `/api/jobs/${JOB}/proposals/bulk`, body: { candidate_ids: [cvPerson.candidate_id] } })).toMatchObject({ status: 200, data: { total_added: 1 } });
    expect(store.stageOf(cvPerson.candidate_id)).toBe("new");
  });

  it("zapisane wyszukiwanie: zapis należy do osoby, alert wymaga kryterium i parametrów API", () => {
    const { store, actions } = setup();
    expect(store.handle({ method: "get", url: "/api/saved-searches?entity=candidates" })).toEqual({ status: 200, data: [] });
    const filters = { version: 2, qs: "kw=Scrum", api: { keywords: "Scrum", page: 1 } };
    expect(store.handle({ method: "post", url: "/api/saved-searches", body: { name: "PM Scrum", entity: "candidates", filters, notify_new_matches: true }, viewerId: VIEWER })).toMatchObject({ status: 201, data: { user_id: VIEWER, notify_new_matches: true } });
    expect((store.handle({ method: "get", url: "/api/saved-searches?entity=candidates" }) as { data: unknown[] }).data).toHaveLength(1);
    expect(judge("baza-zapisane-wyszukiwanie", acted(actions)!)).toEqual({ done: true });
    expect(judge("baza-zapisane-wyszukiwanie", { type: "saved_search", notify: false, criteria: true, name: "x" })).toMatchObject({ done: false });
    expect(judge("baza-zapisane-wyszukiwanie", { type: "saved_search", notify: true, criteria: false, name: "x" })).toMatchObject({ done: false });
    expect(store.handle({ method: "post", url: "/api/saved-searches", body: { name: "stary", filters: { qs: "" }, notify_new_matches: true } })).toMatchObject({ status: 400 });
  });

  it("lista: nowa lista jest „Tylko ja” zalogowanej osoby, a osoba na niej wraca w profilu", () => {
    const { store, actions } = setup();
    expect(store.handle({ method: "get", url: "/api/talent-pools" })).toEqual({ status: 200, data: [] });
    const created = store.handle({ method: "post", url: "/api/talent-pools", body: { name: "PM bankowość", is_personal: true, team_visible: false }, viewerId: VIEWER }) as { data: { id: number; owner_id: number } };
    expect(created.data.owner_id).toBe(VIEWER);
    expect(store.handle({ method: "post", url: `/api/talent-pools/${created.data.id}/add`, body: { candidate_id: first.candidate_id } })).toMatchObject({ status: 201 });
    expect(store.handle({ method: "get", url: `/api/talent-pools/for-candidate/${first.candidate_id}` })).toEqual({ status: 200, data: { pool_ids: [created.data.id] } });
    expect(store.handle({ method: "post", url: `/api/talent-pools/${created.data.id}/add`, body: { candidate_id: first.candidate_id } })).toMatchObject({ status: 409 });
    expect(judge("baza-lista", acted(actions)!)).toEqual({ done: true });
  });

  it("czat rekrutacji: wiadomość wraca na liście, „@” trenera to wzmianka", () => {
    const { store, actions } = setup();
    expect(store.handle({ method: "get", url: `/api/jobs/${JOB}/chat/messages?limit=50` })).toMatchObject({ status: 200, data: { items: [] } });
    store.handle({ method: "post", url: `/api/jobs/${JOB}/chat/messages`, body: { content: "Bez oznaczenia", reply_to_message_id: null } });
    expect(judge("zespol-czat", acted(actions)!)).toMatchObject({ done: false });
    store.handle({ method: "post", url: `/api/jobs/${JOB}/chat/messages`, body: { content: "@anna.poligonowa czy budżet 115 zł/h jest sztywny?", reply_to_message_id: null } });
    expect(acted(actions)).toMatchObject({ type: "chat", mentions: [DATA.meta.trainers.dl.id] });
    expect(judge("zespol-czat", acted(actions)!)).toEqual({ done: true });
    expect((store.handle({ method: "get", url: `/api/jobs/${JOB}/chat/messages?limit=5` }) as { data: { items: unknown[] } }).data.items).toHaveLength(2);
  });

  it("odczyt czatu jest migawką: wysyłka nie mutuje wiadomości wcześniej oddanych do cache", () => {
    const { store } = setup();
    const read = () => store.handle({ method: "get", url: `/api/jobs/${JOB}/chat/messages?limit=50` }) as { data: { items: { content: string }[] } };
    const empty = read();
    store.handle({ method: "post", url: `/api/jobs/${JOB}/chat/messages`, body: { content: "Pierwsza wiadomość" } });
    const first = read();
    expect(empty.data.items).toHaveLength(0);
    expect(first.data.items.map((m) => m.content)).toEqual(["Pierwsza wiadomość"]);

    store.handle({ method: "post", url: `/api/jobs/${JOB}/chat/messages`, body: { content: "Druga wiadomość" } });
    expect(first.data.items.map((m) => m.content)).toEqual(["Pierwsza wiadomość"]);
    expect(read().data.items.map((m) => m.content)).toEqual(["Druga wiadomość", "Pierwsza wiadomość"]);
  });

  it("asystent CV: CV ćwiczebne osoby, stały plan bez modelu i autozapis w pamięci", () => {
    const { store, actions } = setup();
    const entry = DATA.meta.template_entry_id;
    const cv = store.handle({ method: "get", url: `/api/candidates/stages/${entry}/cv/branded` }) as { data: { status: string; content_html: string; from_generator: boolean } };
    expect(cv.data).toMatchObject({ status: "draft", from_generator: true });
    expect(cv.data.content_html).toContain(`${template.name} ${template.lastname}`);
    const other = store.handle({ method: "get", url: `/api/candidates/stages/${second.entry_id}/cv/branded` }) as { data: { content_html: string } };
    expect(other.data.content_html).toContain(`${second.name} ${second.lastname}`);
    const lines = [{ id: 1, kind: "text", text: "Metodyki: Scrum, SAFe" }, { id: 2, kind: "bullet", text: "Planowanie w Jira." }];
    const plan = store.handle({ method: "post", url: `/api/pipeline/stages/${entry}/cv-ai/command`, body: { command: "pogrub Scrum i Jira", lines } });
    expect(plan).toMatchObject({ status: 200, data: { status: "ok", operations: [{ type: "bold", terms: ["Scrum", "Jira"] }] } });
    expect(store.handle({ method: "post", url: `/api/pipeline/stages/${entry}/cv-ai/command`, body: { command: "zrób ładniej", lines } })).toMatchObject({ data: { status: "empty" } });
    expect(judge("zespol-cv-ai", acted(actions)!)).toMatchObject({ done: false });
    store.handle({ method: "post", url: `/api/pipeline/stages/${entry}/cv-ai/applied`, body: { preset: null, operations: 1 } });
    expect(judge("zespol-cv-ai", acted(actions)!)).toEqual({ done: true });
    store.handle({ method: "patch", url: `/api/candidates/stages/${entry}/cv/branded`, body: { content_html: "<p><strong>Scrum</strong></p>", expected_revision: 3 } });
    expect(store.handle({ method: "get", url: `/api/candidates/stages/${entry}/cv/branded` })).toMatchObject({ data: { content_html: "<p><strong>Scrum</strong></p>", edit_revision: 4 } });
  });

  it("Jarvis: dostępny na poligonie, odpowiada o osobie z Tablicy bez modelu", () => {
    const { store, actions } = setup();
    expect(store.handle({ method: "get", url: "/api/jarvis/status" })).toMatchObject({ status: 200, data: { available: true } });
    const answer = store.jarvisAnswer("Co wiemy o Helenie Wrzosek?");
    expect(answer).toContain(`${template.name} ${template.lastname}`);
    expect(acted(actions)).toEqual({ type: "jarvis", message: "Co wiemy o Helenie Wrzosek?", candidateId: template.candidate_id });
    expect(judge("zespol-jarvis", acted(actions)!)).toEqual({ done: true });
    store.jarvisAnswer("Kto to jest Jan Kowalski?");
    expect(judge("zespol-jarvis", acted(actions)!)).toMatchObject({ done: false });
  });
});


describe("poligon: CV z nowości (22.11.2026)", () => {
  const meta = DATA.meta as PoligonDataset["meta"] & { ready_cv_candidate_id: number };
  const ready = DATA.meta.people.find((p) => p.candidate_id === meta.ready_cv_candidate_id)!;
  const tpl = DATA.meta.template_entry_id;

  it("odczyt zapisany dla osoby wygrywa z osobą-szablonem, reszta idzie z szablonu", () => {
    const { store } = setup();
    const own = store.handle({ method: "get", url: `/api/candidates/stages/${ready.entry_id}/cv/branded` });
    expect(own).toMatchObject({ status: 200, data: { status: "none", content_html: null, candidate_stage_id: ready.entry_id } });
    const sources = store.handle({ method: "get", url: `/api/candidates/stages/${ready.entry_id}/cv/branded/sources` }) as { data: { items: unknown[] } };
    expect(sources.data.items).toHaveLength(1);
    // Osoba-szablon i inne osoby: CV do klienta jest, gotowego CV z innej rekrutacji nie ma.
    expect(store.handle({ method: "get", url: `/api/candidates/stages/${second.entry_id}/cv/branded` })).toMatchObject({ data: { status: "draft" } });
    expect(store.handle({ method: "get", url: `/api/candidates/stages/${tpl}/cv/branded/sources` })).toMatchObject({ data: { items: [] } });
    const rows = store.handle({ method: "get", url: "/api/cv-generator/generated", params: { candidate_id: ready.candidate_id, job_id: JOB, limit: 10 } });
    expect(rows).toMatchObject({ status: 200, data: [] });
    const rule = store.handle({ method: "get", url: `/api/cv-generator/clients/${DATA.meta.client_id}/rule-for-generation` });
    expect(rule).toMatchObject({ data: { requires_rodo_consent_block: true } });
  });

  it("„Wpisz w punkcie 1”: podmiana frazy z liczbą lat bez zapisu, inne poprawki QC zablokowane", () => {
    const { store } = setup();
    const qc = store.handle({ method: "get", url: `/api/pipeline/stages/${tpl}/qc`, params: { transient: true } }) as {
      data: { checks: Array<{ key: string; items: Array<{ fix: string; proposal: string }> }> };
    };
    const item = qc.data.checks.find((c) => c.key === "years_breakdown")!.items[0];
    expect(item.fix).toBe("tenure_split");
    const html = (store.handle({ method: "get", url: `/api/candidates/stages/${second.entry_id}/cv/branded` }) as { data: { content_html: string } }).data.content_html;
    const url = `/api/pipeline/stages/${second.entry_id}/qc/transform`;
    const res = store.handle({ method: "post", url, body: { content_html: html, actions: [{ action: "tenure_split" }] } }) as { status: number; data: { changed: boolean; content_html: string } };
    expect(res.status).toBe(200);
    expect(res.data.changed).toBe(true);
    expect(res.data.content_html).toContain(`<p>${item.proposal}: migracja systemu płatności`);
    const again = store.handle({ method: "post", url, body: { content_html: res.data.content_html, actions: [{ action: "tenure_split" }] } });
    expect(again).toMatchObject({ status: 200, data: { changed: false, skipped: [{ code: "nothing_to_do" }] } });
    expect(store.handle({ method: "post", url, body: { content_html: html, actions: [{ action: "spelling" }] } })).toMatchObject({ status: 409 });
  });
});

vi.useRealTimers();

describe("poligon: stop do podpisu przedwstępnej (lekcje nowości, 23.11.2026)", () => {
  // Szymon w „QC CV” czeka na podpis (ustawienie rekrutacji: przed wysłaniem CV),
  // Weronika obok ma przedwstępną podpisaną (`poligon_pre_contract_practice.py`).
  const STOPPED = 990110;
  const SIGNED = 990109;
  const defOf = (name: string) =>
    (DATA.responses[`GET /api/pipeline/kanban/${JOB}`] as unknown as { columns: Array<{ name: string; stage_def_id: number }> }).columns.find(
      (c) => c.name === name,
    )!.stage_def_id;
  const move = (store: ReturnType<typeof setup>["store"], candidate: number, name: string) =>
    store.handle({ method: "post", url: "/api/pipeline/move", body: { candidate_id: candidate, job_id: JOB, stage_def_id: defOf(name) } });

  it("ruch na „CV wysłane” i dalej odmawia 409 PRE_CONTRACT_NOT_SIGNED — także po Rozmowę u klienta", () => {
    const { store } = setup();
    for (const name of ["CV Wysłane", "Interview Klient"]) {
      const res = move(store, STOPPED, name);
      if (res === "network") throw new Error("ruch nie może wyjść z przeglądarki");
      expect(res.status).toBe(409);
      expect((res.data as { detail: { code: string; message: string } }).detail.code).toBe("PRE_CONTRACT_NOT_SIGNED");
    }
    expect(store.stageOf(STOPPED)).toBe("interview");
  });

  it("ruch w lewo i osoba z podpisaną umową przechodzą", () => {
    const { store } = setup();
    expect(move(store, SIGNED, "CV Wysłane")).toMatchObject({ status: 200 });
    expect(move(store, STOPPED, "Zweryfikowany")).toMatchObject({ status: 200 });
    expect(store.stageOf(STOPPED)).toBe("verified");
  });

  it("okno „Przesuń dalej” pokazuje blokującą pozycję przedwstępnej", () => {
    const { store } = setup();
    const res = store.handle({
      method: "get",
      url: `/api/pipeline/move-requirements?candidate_id=${STOPPED}&job_id=${JOB}&to_stage_def_id=${defOf("CV Wysłane")}`,
    });
    if (res === "network") throw new Error("odczyt z zestawu");
    const data = res.data as { items: Array<{ key: string; blocking: boolean }>; primary: { kind: string } };
    expect(data.items).toEqual([expect.objectContaining({ key: "pre_contract", blocking: true })]);
    expect(data.primary.kind).toBe("blocked");
  });

  it("„Wyjątek dla tej osoby” (can_set_stop) dostaje tylko rola, która zdejmuje blokadę", () => {
    const { store } = setup();
    const url = `/api/pre-contracts/pair?candidate_id=${STOPPED}&job_id=${JOB}`;
    const pair = (canSetPreContractStop: boolean) => {
      const res = store.handle({ method: "get", url, canSetPreContractStop });
      if (res === "network") throw new Error("odczyt z zestawu");
      return res.data as { can_set_stop: boolean; stop: { origin: string } | null };
    };
    expect(pair(true)).toMatchObject({ can_set_stop: true, stop: { origin: "job" } });
    expect(pair(false).can_set_stop).toBe(false);
  });
});
