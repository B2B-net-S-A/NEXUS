/**
 * Pamięć rozmowy screeningowej — gałęzie brzegowe (uzupełnienie
 * screening-memory.test.ts): tekst z odstępami, pole ruszone vs przywrócone
 * z pamięci, wartość równa zapisanej, stawka w trybie „ta sama” i osobno,
 * klient przy kotwicy, przycinanie do `null`, przywracanie z remisem kolejności.
 * Dane fikcyjne.
 */
import { describe, expect, it } from "vitest";

import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";
import type { JointGroup, JointPair } from "@/lib/joint-screening";
import { jointDefaults } from "@/lib/joint-screening";
import {
  emptyMemory,
  jointRestore,
  memoryAfterSave,
  memoryFromJoint,
  memoryFromSingle,
  memoryHasEntries,
  memoryPairSummary,
  memoryWithSelection,
  singleRestore,
  type JointMemoryInput,
  type ScreeningMemory,
} from "@/lib/screening-memory";
import { formDefaultsFromState } from "@/lib/screening-form";

const NOW = 1_800_000_000_000;
const QA = [{ id: "q1", question: "Ile lat z Javą?", ideal_answer: "", deal_breaker: "" }];
const EDITABLE = ["availability", "work_mode", "rate", "recommendation", "red_flags", "worked_at_client"];

type State = JointPair["state"];

/** Karta z zapisanymi polami (`raw`) i polami do edycji. */
function cardWith(fields: Record<string, string>, editable: string[] = EDITABLE): State["card"] {
  return {
    ...formState().card,
    fields: Object.fromEntries(Object.entries(fields).map(([k, raw]) => [k, { raw }])),
    editable_fields: editable,
  } as never;
}

const rate = (amount: number) => ({ amount, unit: "hourly" as const, currency: "PLN", source: "stage" as const, at: null });

function pairWith(jobId: number, anchor: boolean, overrides: Partial<State> = {}, clientId: number | null = jobId): JointPair {
  return {
    jobId,
    title: `Rekrutacja ${jobId}`,
    clientId,
    clientName: null,
    budgetHourly: null,
    verifiedStageDefId: 1,
    anchor,
    state: formState({ job_id: jobId, champion_profile: { screening_questions: QA }, ...overrides }),
  };
}

const GROUPS: JointGroup[] = [{ key: "g0", members: [{ jobId: 201, questionId: "q1" }, { jobId: 202, questionId: "q1" }] }];

function joint(prev: ScreeningMemory | null, pairs: JointPair[], input: Partial<JointMemoryInput>, groups = GROUPS) {
  return memoryFromJoint(prev, {
    anchorJobId: 201,
    pairs,
    groups,
    values: jointDefaults(pairs, groups),
    dirty: {},
    origins: {},
    note: null,
    now: NOW,
    ...input,
  });
}

const valueAt = (patches: Array<{ path: string; value: unknown }>, path: string) => patches.find((p) => p.path === path)?.value;
const singleValueAt = (patches: Array<[string, unknown]>, path: string) => patches.find(([p]) => p === path)?.[1];

describe("memoryFromJoint — gałęzie", () => {
  it("deal-breaker ruszony i inny niż zapisany trafia do pamięci; ruszony, ale równy zapisanemu — nie", () => {
    const a = pairWith(201, true);
    const b = pairWith(202, false);
    const values = jointDefaults([a, b], GROUPS);
    values.hits.j201_q1 = true;
    const memory = joint(null, [a, b], { values, dirty: { hits: { j201_q1: true, j202_q1: true } } });
    expect(memory?.pairs["201"]?.hits).toEqual({ q1: true });
    // Rekrutacja bez wpisów znika z pamięci (przycięcie).
    expect(memory?.pairs["202"]).toBeUndefined();
    // Tryb stawki nie był ruszony ani zapamiętany — nie zostaje.
    expect(memory?.shared.same_rate).toBeUndefined();
  });

  it("pola rekrutacji: ocena, karta z pochodzeniem, pominięcie i notatka wewnętrzna; równe zapisanym (z odstępami) — nie", () => {
    const card = cardWith({ work_mode: "zdalnie", recommendation: "" });
    const a = pairWith(201, true, { card });
    const b = pairWith(202, false, { card });
    const values = jointDefaults([a, b], GROUPS);
    values.jobs.j201 = {
      ...values.jobs.j201,
      overall_fit: "fit",
      card: { ...values.jobs.j201.card, work_mode: "hybryda ", recommendation: "Mocny backend" },
      skip_missing: true,
      skip_reason: "employed",
      internal_note: "Pracuje na etacie",
    };
    values.jobs.j202 = {
      ...values.jobs.j202,
      overall_fit: "uncertain",
      card: { ...values.jobs.j202.card, work_mode: "zdalnie " },
      skip_missing: false,
      internal_note: " ",
    };
    const prev: ScreeningMemory = {
      ...emptyMemory(201, NOW - 10),
      origins: { "jobs.j202.card.work_mode": { value: "zdalnie", origin: "note_ai" } },
    };
    const dirtyJob = { overall_fit: true, card: { work_mode: true, recommendation: true }, skip_missing: true, internal_note: true };
    const memory = joint(prev, [a, b], {
      values,
      dirty: { jobs: { j201: dirtyJob, j202: dirtyJob } },
      origins: {
        "jobs.j201.card.work_mode": { value: "hybryda", origin: "note_ai" },
        // Pochodzenie z inną wartością już nie obowiązuje.
        "jobs.j201.card.recommendation": { value: "Inny tekst", origin: "note_rule" },
      },
    });
    expect(memory?.pairs["201"]).toEqual({
      touchedAt: NOW,
      overall_fit: "fit",
      card: { work_mode: "hybryda ", recommendation: "Mocny backend" },
      skip_missing: true,
      skip_reason: "employed",
      internal_note: "Pracuje na etacie",
    });
    expect(memory?.origins["jobs.j201.card.work_mode"]).toEqual({ value: "hybryda ", origin: "note_ai" });
    expect(memory?.origins["jobs.j201.card.recommendation"]).toBeUndefined();
    expect(memory?.pairs["202"]).toBeUndefined();
    expect(memory?.origins["jobs.j202.card.work_mode"]).toBeUndefined();
  });

  it("pole o osobie: ruszone zostaje, przywrócone z pamięci z tą samą wartością też, powrót do zapisanej — znika", () => {
    const card = cardWith({ availability: "od zaraz", red_flags: "brak" });
    const a = pairWith(201, true, { card });
    const b = pairWith(202, false, { card });
    const values = jointDefaults([a, b], GROUPS);
    values.shared.card.availability = "od 1.12";
    values.shared.card.red_flags = "brak ";
    const first = joint(null, [a, b], {
      values,
      dirty: { shared: { card: { availability: true, red_flags: true } } },
      origins: { "shared.card.availability": { value: "od 1.12", origin: "note_rule" } },
    });
    expect(first?.shared.card).toEqual({ availability: "od 1.12" });
    expect(first?.origins["shared.card.availability"]).toEqual({ value: "od 1.12", origin: "note_rule" });

    // Formularz po przywróceniu: ta sama wartość, ale pole nie jest „ruszone”.
    const held = joint(first, [a, b], { values: { ...values, shared: { ...values.shared, card: { ...values.shared.card, availability: "od 1.12 " } } } });
    expect(held?.shared.card).toEqual({ availability: "od 1.12 " });

    const back = jointDefaults([a, b], GROUPS);
    expect(joint(held, [a, b], { values: back })).toBeNull();
  });

  it("„Czy pracował u Klienta”: zapamiętany przy kliencie i kopia przy kotwicy; wpis z formularza pojedynczego się trzyma; powrót do zapisanego kasuje", () => {
    const card = cardWith({ worked_at_client: "" });
    const a = pairWith(201, true, { card }, 7);
    const b = pairWith(202, false, { card }, 7);
    const values = jointDefaults([a, b], GROUPS);
    values.clients.c7 = "Tak, 2020";
    const memory = joint(null, [a, b], {
      values,
      dirty: { clients: { c7: true } },
      origins: { "clients.c7": { value: "Tak, 2020", origin: "note_ai" } },
    });
    expect(memory?.clients).toEqual({ c7: "Tak, 2020" });
    expect(memory?.pairs["201"]?.card).toEqual({ worked_at_client: "Tak, 2020" });
    expect(memory?.pairs["202"]).toBeUndefined();
    expect(memory?.origins["clients.c7"]?.origin).toBe("note_ai");

    // Wpis z formularza pojedynczego (przy parze, bez klienta) jest „trzymany”.
    const fromSingle: ScreeningMemory = {
      ...emptyMemory(201, NOW - 10),
      pairs: { "202": { touchedAt: NOW - 10, card: { worked_at_client: "Nie" } } },
    };
    const kept = joint(fromSingle, [a, b], { values: { ...values, clients: { c7: "Nie" } } });
    expect(kept?.clients).toEqual({ c7: "Nie" });

    expect(joint(memory, [a, b], { values: jointDefaults([a, b], GROUPS) })).toBeNull();
  });

  it("kopia klienta nie trafia do kotwicy, której karta nie ma pola klienta", () => {
    const a = pairWith(201, true, { card: cardWith({}, ["availability"]) }, 7);
    const b = pairWith(202, false, { card: cardWith({ worked_at_client: "" }) }, 7);
    const values = jointDefaults([a, b], GROUPS);
    values.clients.c7 = "Tak";
    const memory = joint(null, [a, b], { values, dirty: { clients: { c7: true } } });
    expect(memory?.clients).toEqual({ c7: "Tak" });
    expect(memory?.pairs["201"]).toBeUndefined();
  });

  it("wspólna stawka: ruszona i inna niż zapisane zostaje z trybem „ta sama”; równa zapisanej we wszystkich — nie", () => {
    const a = pairWith(201, true, { rate: rate(120) });
    const b = pairWith(202, false, { rate: rate(120) });
    const values = jointDefaults([a, b], GROUPS);
    expect(values.shared.same_rate).toBe(true);
    values.shared.rate_amount = "150";
    const typed = joint(null, [a, b], { values, dirty: { shared: { rate_amount: true } } });
    expect(typed?.shared.rate).toEqual({ rate_amount: "150", rate_unit: "hourly", rate_currency: "PLN" });
    expect(typed?.shared.same_rate).toBe(true);

    // Przywrócona z pamięci (bez „ruszenia”) zostaje.
    const held = joint(typed, [a, b], { values });
    expect(held?.shared.rate?.rate_amount).toBe("150");

    // Powrót do 120: stawka znika, tryb zostaje, bo pamięć miała ten sam tryb — ale bez innych wpisów nic nie zostaje.
    const back = jointDefaults([a, b], GROUPS);
    const reverted = joint(typed, [a, b], { values: back, dirty: { shared: { rate_amount: true } } });
    expect(reverted?.shared.rate).toBeUndefined();
    expect(reverted?.shared.same_rate).toBe(true);
  });

  it("tryb stawki ruszony sam zostaje zapamiętany", () => {
    const a = pairWith(201, true, { rate: rate(120) });
    const b = pairWith(202, false, { rate: rate(120) });
    const values = jointDefaults([a, b], GROUPS);
    values.shared.same_rate = false;
    const memory = joint(null, [a, b], { values, dirty: { shared: { same_rate: true } } });
    expect(memory?.shared).toEqual({ same_rate: false });
  });

  it("stawka rekrutacji przywrócona z pamięci (osobno) zostaje bez „ruszenia”", () => {
    const a = pairWith(201, true, { rate: rate(120) });
    const b = pairWith(202, false, { rate: rate(100) });
    const values = jointDefaults([a, b], GROUPS);
    values.jobs.j201.rate_amount = "150";
    const prev: ScreeningMemory = {
      ...emptyMemory(201, NOW - 10),
      pairs: { "201": { touchedAt: NOW - 10, rate: { rate_amount: "150,00", rate_unit: "hourly", rate_currency: "pln" } } },
    };
    const memory = joint(prev, [a, b], { values });
    expect(memory?.pairs["201"]?.rate).toEqual({ rate_amount: "150", rate_unit: "hourly", rate_currency: "PLN" });
    expect(memory?.shared.same_rate).toBe(false);
  });

  it("pochodzenie odpowiedzi idzie do każdej rekrutacji grupy; odpowiedź nieruszona traci stare pochodzenie", () => {
    const a = pairWith(201, true);
    const b = pairWith(202, false);
    const values = jointDefaults([a, b], GROUPS);
    values.answers.g0 = "9 lat";
    const memory = joint(null, [a, b], {
      values,
      dirty: { answers: { g0: true } },
      origins: { "answers.g0": { value: "", origin: "phrased", keywords: "java" } },
    });
    expect(memory?.origins["answers.j201.q1"]).toEqual({ value: "9 lat", origin: "phrased", keywords: "java" });
    expect(memory?.origins["answers.j202.q1"]).toEqual({ value: "9 lat", origin: "phrased", keywords: "java" });

    const untouched = joint(
      { ...emptyMemory(201, NOW - 10), origins: { "answers.j201.q1": { value: "x", origin: "phrased" } }, note: { source: { text: "Notatka" }, filled: 1 } },
      [a, b],
      { note: { source: { text: "Notatka" }, filled: 1 } },
    );
    expect(untouched?.origins).toEqual({});
    expect(untouched?.note?.filled).toBe(1);
  });
});

describe("jointRestore — gałęzie", () => {
  it("bez pamięci nic nie wraca", () => {
    const a = pairWith(201, true);
    expect(jointRestore(null, [a], GROUPS, jointDefaults([a], GROUPS))).toEqual({ patches: [], origins: {}, note: null });
  });

  it("pola o osobie tylko te na ekranie; klient — wpis z formularza pojedynczego wygrywa z wpisem przy kliencie", () => {
    const card = cardWith({ availability: "", worked_at_client: "" }, ["availability", "worked_at_client"]);
    const a = pairWith(201, true, { card }, 7);
    const b = pairWith(202, false, { card }, 8);
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: { "202": { touchedAt: NOW, card: { worked_at_client: "Tak, z pojedynczego" } } },
      shared: { card: { availability: "od 1.12", location: "Kraków" } },
      clients: { c7: "Nie", c8: "Tak, z wspólnego" },
      origins: {
        "shared.card.availability": { value: "od 1.12", origin: "note_ai" },
        "clients.c7": { value: "Inna wartość", origin: "note_ai" },
      },
    };
    const restore = jointRestore(memory, [a, b], GROUPS, jointDefaults([a, b], GROUPS));
    expect(valueAt(restore.patches, "shared.card.availability")).toBe("od 1.12");
    expect(valueAt(restore.patches, "shared.card.location")).toBeUndefined();
    expect(valueAt(restore.patches, "clients.c7")).toBe("Nie");
    expect(valueAt(restore.patches, "clients.c8")).toBe("Tak, z pojedynczego");
    expect(restore.origins).toEqual({ "shared.card.availability": { value: "od 1.12", origin: "note_ai" } });
    // Pole klienta przy parze B nie ma osobnego pola rekrutacji w formularzu wspólnym.
    expect(valueAt(restore.patches, "jobs.j202.card.worked_at_client")).toBeUndefined();
  });

  it("tryb „ta sama”: pole wspólne bierze stawkę kotwicy z formularza pojedynczego", () => {
    const a = pairWith(201, true);
    const b = pairWith(202, false);
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: {
        "201": { touchedAt: NOW, rate: { rate_amount: "150", rate_unit: "hourly", rate_currency: "PLN" } },
        "202": { touchedAt: NOW, rate: { rate_amount: "130", rate_unit: "hourly", rate_currency: "PLN" } },
      },
      shared: { same_rate: true },
    };
    const restore = jointRestore(memory, [a, b], GROUPS, jointDefaults([a, b], GROUPS));
    expect(valueAt(restore.patches, "shared.same_rate")).toBe(true);
    expect(valueAt(restore.patches, "shared.rate_amount")).toBe("150");
    expect(valueAt(restore.patches, "shared.rate_unit")).toBe("hourly");
    expect(valueAt(restore.patches, "shared.rate_currency")).toBe("PLN");
  });

  it("tryb „ta sama” bez stawki kotwicy: pole wspólne bierze pierwszą zapamiętaną stawkę innej rekrutacji", () => {
    const a = pairWith(201, true);
    const b = pairWith(202, false);
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: { "202": { touchedAt: NOW, rate: { rate_amount: "130", rate_unit: "daily", rate_currency: "EUR" } } },
    };
    // Tryb z formularza (obie bez stawki → „ta sama”), bo pamięć trybu nie ma.
    const restore = jointRestore(memory, [a, b], GROUPS, jointDefaults([a, b], GROUPS));
    expect(valueAt(restore.patches, "shared.same_rate")).toBeUndefined();
    expect(valueAt(restore.patches, "shared.rate_amount")).toBe("130");
    expect(valueAt(restore.patches, "shared.rate_unit")).toBe("daily");
    expect(valueAt(restore.patches, "jobs.j202.rate_amount")).toBe("130");
  });

  it("tryb osobno: kotwica bez własnej stawki dostaje stawkę wspólną do swojego pola", () => {
    const a = pairWith(201, true);
    const b = pairWith(202, false);
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: { "201": { touchedAt: NOW, overall_fit: "fit" }, "202": { touchedAt: NOW, overall_fit: "miss" } },
      shared: { same_rate: false, rate: { rate_amount: "160", rate_unit: "hourly", rate_currency: "PLN" } },
    };
    const restore = jointRestore(memory, [a, b], GROUPS, jointDefaults([a, b], GROUPS));
    expect(valueAt(restore.patches, "jobs.j201.rate_amount")).toBe("160");
    expect(valueAt(restore.patches, "jobs.j202.rate_amount")).toBeUndefined();
    expect(valueAt(restore.patches, "shared.same_rate")).toBe(false);
  });

  it("pola rekrutacji: ocena, karta tylko na ekranie, pominięcie (powód domyślnie null), notatka, deal-breakery tylko na ekranie", () => {
    const card = cardWith({ work_mode: "" }, ["work_mode"]);
    const a = pairWith(201, true, { card });
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: {
        "201": {
          touchedAt: NOW,
          overall_fit: "miss",
          card: { work_mode: "biuro", motivation: "Rozwój" },
          skip_missing: true,
          internal_note: "Rozmowa przerwana",
          hits: { q1: true, q5: true },
        },
      },
      origins: { "jobs.j201.card.work_mode": { value: "biuro", origin: "note_rule" } },
    };
    const groups: JointGroup[] = [{ key: "g0", members: [{ jobId: 201, questionId: "q1" }] }];
    const restore = jointRestore(memory, [a], groups, jointDefaults([a], groups));
    expect(restore.patches).toEqual([
      { path: "jobs.j201.overall_fit", value: "miss" },
      { path: "jobs.j201.card.work_mode", value: "biuro" },
      { path: "jobs.j201.skip_missing", value: true },
      { path: "jobs.j201.skip_reason", value: null },
      { path: "jobs.j201.internal_note", value: "Rozmowa przerwana" },
      { path: "hits.j201_q1", value: true },
    ]);
    expect(restore.origins).toEqual({ "jobs.j201.card.work_mode": { value: "biuro", origin: "note_rule" } });
  });

  it("remis czasu rozmowy: wygrywa kotwica, potem kolejność par; pochodzenie idzie za wybraną odpowiedzią", () => {
    const a = pairWith(201, true);
    const b = pairWith(202, false);
    const c = pairWith(203, false);
    const groups: JointGroup[] = [
      {
        key: "g0",
        members: [
          { jobId: 203, questionId: "q1" },
          { jobId: 202, questionId: "q1" },
          { jobId: 201, questionId: "q1" },
        ],
      },
    ];
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: {
        "201": { touchedAt: NOW, answers: { q1: "z kotwicy" } },
        "202": { touchedAt: NOW, answers: { q1: "z B" } },
        "203": { touchedAt: NOW, answers: { q1: "z C" } },
      },
      origins: { "answers.j201.q1": { value: "z kotwicy", origin: "note_import" } },
    };
    // Kotwica na końcu listy par — i tak wygrywa remis.
    const restore = jointRestore(memory, [c, b, a], groups, jointDefaults([c, b, a], groups));
    expect(valueAt(restore.patches, "answers.g0")).toBe("z kotwicy");
    expect(restore.origins["answers.g0"]).toEqual({ value: "z kotwicy", origin: "note_import" });

    // Bez kotwicy w pamięci: między B i C decyduje kolejność par na liście.
    const noAnchor: ScreeningMemory = { ...memory, pairs: { "202": memory.pairs["202"], "203": memory.pairs["203"] }, origins: {} };
    expect(valueAt(jointRestore(noAnchor, [a, b, c], groups, jointDefaults([a, b, c], groups)).patches, "answers.g0")).toBe("z B");
    expect(valueAt(jointRestore(noAnchor, [a, c, b], groups, jointDefaults([a, c, b], groups)).patches, "answers.g0")).toBe("z C");
  });
});

describe("memoryFromSingle — gałęzie", () => {
  const card = cardWith({ availability: "od zaraz", work_mode: "zdalnie", recommendation: "", red_flags: "" });
  const state = formState({ job_id: 201, card });
  const base = formDefaultsFromState(state);
  const input = { anchorJobId: 201, state, dirty: {}, rateTouched: false, note: null, now: NOW };

  it("odpowiedzi: pochodzenie z haseł zostaje, ręczne je zdejmuje; deal-breaker tylko inny niż zapisany", () => {
    const values = {
      ...base,
      answers: {
        q1: { response: "9 lat", deal_breaker_hit: true, origin: "phrased" as const, keywords: "java" },
        q2: { response: "Tak", deal_breaker_hit: false, origin: "manual" as const, keywords: null },
      },
    };
    const prev: ScreeningMemory = {
      ...emptyMemory(201, NOW - 10),
      origins: { "answers.j201.q2": { value: "Tak", origin: "note_import" } },
    };
    const memory = memoryFromSingle(prev, {
      ...input,
      values,
      dirty: { answers: { q1: { response: true, deal_breaker_hit: true }, q2: { response: true, deal_breaker_hit: true } } },
    });
    expect(memory?.pairs["201"]?.answers).toEqual({ q1: "9 lat", q2: "Tak" });
    expect(memory?.pairs["201"]?.hits).toEqual({ q1: true });
    expect(memory?.origins).toEqual({ "answers.j201.q1": { value: "9 lat", origin: "phrased", keywords: "java" } });
  });

  it("odpowiedź ruszona, ale równa zapisanej (z odstępami), nie jest zapamiętana", () => {
    const saved = formState({
      job_id: 201,
      card,
      sheet: { answers: [{ question_id: "q1", response: "9 lat", deal_breaker_hit: false }], overall_fit: "uncertain", notes: "" } as never,
    });
    const values = formDefaultsFromState(saved);
    values.answers.q1 = { ...values.answers.q1, response: " 9 lat " };
    expect(memoryFromSingle(null, { ...input, state: saved, values, dirty: { answers: { q1: { response: true } } } })).toBeNull();
  });

  it("karta: pole o osobie do wspólnych, pole rekrutacji do pary, z pochodzeniem; nieruszone pole o osobie znika z pamięci", () => {
    const values = {
      ...base,
      card: { ...base.card, availability: "od 1.12", recommendation: "Mocny backend", work_mode: "zdalnie ", red_flags: "brak" },
      card_origins: { ...base.card_origins, availability: { origin: "note_ai" as const }, recommendation: { origin: "phrased" as const, keywords: "java, kafka" } },
    };
    const prev: ScreeningMemory = {
      ...emptyMemory(201, NOW - 10),
      shared: { card: { red_flags: "brak" } },
      origins: { "shared.card.red_flags": { value: "brak", origin: "note_rule" } },
    };
    const memory = memoryFromSingle(prev, {
      ...input,
      values,
      dirty: { card: { availability: true, recommendation: true, work_mode: true } },
    });
    expect(memory?.shared.card).toEqual({ availability: "od 1.12" });
    expect(memory?.pairs["201"]?.card).toEqual({ recommendation: "Mocny backend" });
    expect(memory?.origins).toEqual({
      "shared.card.availability": { value: "od 1.12", origin: "note_ai", keywords: null },
      "jobs.j201.card.recommendation": { value: "Mocny backend", origin: "phrased", keywords: "java, kafka" },
    });
  });

  it("tryb „ta sama stawka”: stawka idzie do pola wspólnego, nieruszona je czyści", () => {
    const prev: ScreeningMemory = { ...emptyMemory(201, NOW - 10), shared: { same_rate: true } };
    const values = { ...base, rate_amount: "150" };
    const memory = memoryFromSingle(prev, { ...input, values, rateTouched: true });
    expect(memory?.shared.rate).toEqual({ rate_amount: "150", rate_unit: "hourly", rate_currency: "PLN" });
    expect(memory?.pairs["201"]).toBeUndefined();

    const untouched = memoryFromSingle(memory, { ...input, values });
    expect(untouched?.shared.rate).toBeUndefined();
    expect(untouched?.shared.same_rate).toBe(true);
  });

  it("tryb osobno: stara stawka wspólna znika, stawka idzie do rekrutacji", () => {
    const prev: ScreeningMemory = {
      ...emptyMemory(201, NOW - 10),
      shared: { same_rate: false, rate: { rate_amount: "160", rate_unit: "hourly", rate_currency: "PLN" } },
    };
    const memory = memoryFromSingle(prev, { ...input, values: { ...base, rate_amount: "150" }, rateTouched: true });
    expect(memory?.shared.rate).toBeUndefined();
    expect(memory?.pairs["201"]?.rate?.rate_amount).toBe("150");
  });

  it("ocena, pominięcie i notatka wewnętrzna — tylko ruszone i inne niż zapisane", () => {
    const values = { ...base, overall_fit: "fit" as const, skip_missing: true, skip_reason: "reassign" as const, internal_note: "Przeniesiony" };
    const memory = memoryFromSingle(null, {
      ...input,
      values,
      dirty: { overall_fit: true, skip_missing: true, internal_note: true },
      note: { source: { text: "Notatka z rozmowy" }, filled: 2 },
    });
    expect(memory?.pairs["201"]).toEqual({
      touchedAt: NOW,
      overall_fit: "fit",
      skip_missing: true,
      skip_reason: "reassign",
      internal_note: "Przeniesiony",
    });
    expect(memory?.note).toEqual({ source: { text: "Notatka z rozmowy" }, filled: 2 });

    const same = memoryFromSingle(null, {
      ...input,
      values: { ...base, internal_note: "  " },
      dirty: { overall_fit: true, skip_missing: true, internal_note: true },
    });
    expect(same).toBeNull();
  });
});

describe("singleRestore — gałęzie", () => {
  const card = cardWith({}, ["availability", "work_mode", "recommendation", "worked_at_client"]);
  const state = formState({ job_id: 201, card });

  it("bez pamięci nic nie wraca", () => {
    expect(singleRestore(null, state)).toEqual({ patches: [], rateTouched: false, note: null });
  });

  it("odpowiedzi: pochodzenie z pamięci tylko gdy trzyma wartość, inaczej „manual”; pytań spoza formularza nie ma", () => {
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: { "201": { touchedAt: NOW, answers: { q1: "9 lat", q2: "Tak", q7: "Obce" }, hits: { q1: true, q7: true } } },
      origins: {
        "answers.j201.q1": { value: "9 lat", origin: "phrased" },
        "answers.j201.q2": { value: "Nie", origin: "note_import" },
      },
    };
    expect(singleRestore(memory, state).patches).toEqual([
      ["answers.q1.response", "9 lat"],
      ["answers.q1.origin", "phrased"],
      ["answers.q1.keywords", null],
      ["answers.q2.response", "Tak"],
      ["answers.q2.origin", "manual"],
      ["answers.q1.deal_breaker_hit", true],
    ]);
  });

  it("karta: pole o osobie ze wspólnych, klient przez id klienta, pole rekrutacji z pochodzeniem i hasłami", () => {
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: { "201": { touchedAt: NOW, card: { recommendation: "Mocny backend" } } },
      shared: { card: { availability: "od 1.12" } },
      clients: { c7: "Tak, 2020" },
      origins: {
        "shared.card.availability": { value: "od 1.12", origin: "note_rule" },
        "jobs.j201.card.recommendation": { value: "", origin: "phrased", keywords: "java" },
        "clients.c7": { value: "Tak, 2020", origin: "note_import" },
      },
    };
    const patches = singleRestore(memory, state, 7).patches;
    expect(patches).toEqual([
      ["card.availability", "od 1.12"],
      ["card_origins.availability", { origin: "note_rule" }],
      ["card.recommendation", "Mocny backend"],
      ["card_origins.recommendation", { origin: "phrased", keywords: "java" }],
      ["card.worked_at_client", "Tak, 2020"],
    ]);
    // Bez id klienta wpis przy kliencie nie wraca.
    expect(singleValueAt(singleRestore(memory, state).patches, "card.worked_at_client")).toBeUndefined();
  });

  it("klient: wpis przy parze wygrywa z wpisem przy kliencie", () => {
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: { "201": { touchedAt: NOW, card: { worked_at_client: "Nie" } } },
      clients: { c7: "Tak" },
    };
    expect(singleValueAt(singleRestore(memory, state, 7).patches, "card.worked_at_client")).toBe("Nie");
  });

  it("stawka: w trybie „ta sama” wspólna przed własną, osobno własna przed wspólną; reszta pól pary", () => {
    const shared = { rate_amount: "160", rate_unit: "hourly" as const, rate_currency: "PLN" };
    const own = { rate_amount: "150", rate_unit: "daily" as const, rate_currency: "EUR" };
    const pair = { touchedAt: NOW, rate: own, overall_fit: "fit" as const, skip_missing: true, internal_note: "Pominięte" };
    const same: ScreeningMemory = { ...emptyMemory(201, NOW), pairs: { "201": pair }, shared: { same_rate: true, rate: shared } };
    const restore = singleRestore(same, state);
    expect(restore.rateTouched).toBe(true);
    expect(restore.patches).toEqual([
      ["rate_amount", "160"],
      ["rate_unit", "hourly"],
      ["rate_currency", "PLN"],
      ["overall_fit", "fit"],
      ["skip_missing", true],
      ["skip_reason", null],
      ["internal_note", "Pominięte"],
    ]);
    // „Ta sama” bez stawki wspólnej — własna.
    expect(singleValueAt(singleRestore({ ...same, shared: { same_rate: true } }, state).patches, "rate_amount")).toBe("150");
    // Osobno — własna przed wspólną; bez własnej — wspólna.
    expect(singleValueAt(singleRestore({ ...same, shared: { same_rate: false, rate: shared } }, state).patches, "rate_amount")).toBe("150");
    const noOwn: ScreeningMemory = { ...same, pairs: { "201": { touchedAt: NOW } }, shared: { rate: shared } };
    expect(singleValueAt(singleRestore(noOwn, state).patches, "rate_amount")).toBe("160");
  });
});

describe("zapis, zaznaczenie, podsumowanie — gałęzie", () => {
  it("po nieudanym zapisie jednej pary pochodzenia pozostałych rekrutacji znikają", () => {
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: {
        "201": { touchedAt: NOW, answers: { q1: "9 lat" } },
        "202": { touchedAt: NOW, card: { work_mode: "biuro" } },
      },
      origins: {
        "answers.j201.q1": { value: "9 lat", origin: "phrased" },
        "jobs.j201.card.recommendation": { value: "x", origin: "note_ai" },
        "jobs.j202.card.work_mode": { value: "biuro", origin: "note_ai" },
        "shared.card.availability": { value: "od 1.12", origin: "note_ai" },
      },
    };
    const after = memoryAfterSave(memory, [202], NOW + 1);
    expect(Object.keys(after?.origins ?? {}).sort()).toEqual(["jobs.j202.card.work_mode", "shared.card.availability"]);
    expect(after?.updatedAt).toBe(NOW + 1);
    expect(memoryAfterSave(null, [202], NOW)).toBeNull();
  });

  it("zaznaczenie zapamiętane tylko przy rozmowie, która już coś ma", () => {
    expect(memoryWithSelection(null, 201, [202], NOW)).toBeNull();
    const memory: ScreeningMemory = { ...emptyMemory(200, NOW - 10), selected: [205], clients: { c7: "Tak" } };
    const next = memoryWithSelection(memory, 201, [202, 203], NOW);
    expect(next).toMatchObject({ anchorJobId: 201, selected: [202, 203], updatedAt: NOW, clients: { c7: "Tak" } });
    expect(memory.selected).toEqual([205]);
  });

  it("czy pamięć coś ma: tryb stawki albo notatka wystarczą; para bez wpisów — nie", () => {
    expect(memoryHasEntries(null)).toBe(false);
    expect(memoryHasEntries(emptyMemory(201, NOW))).toBe(false);
    expect(memoryHasEntries({ ...emptyMemory(201, NOW), shared: { same_rate: false } })).toBe(true);
    expect(memoryHasEntries({ ...emptyMemory(201, NOW), note: { source: { text: "N" }, filled: 0 } })).toBe(true);
    expect(memoryHasEntries({ ...emptyMemory(201, NOW), pairs: { "201": { touchedAt: NOW, answers: {} } } })).toBe(false);
    expect(memoryHasEntries({ ...emptyMemory(201, NOW), pairs: { "201": undefined as never } })).toBe(false);
  });

  it("podsumowanie pary: brak pary = zero, odpowiedzi z samych odstępów się nie liczą", () => {
    expect(memoryPairSummary(null, 201)).toEqual({ answers: 0, any: false });
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: { "201": { touchedAt: NOW, answers: { q1: "  ", q2: "Tak" } } },
    };
    expect(memoryPairSummary(memory, 201)).toEqual({ answers: 1, any: true });
    expect(memoryPairSummary(memory, 999)).toEqual({ answers: 0, any: false });
  });
});
