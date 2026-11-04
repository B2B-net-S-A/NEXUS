/**
 * Pamięć rozmowy screeningowej (16.10.2026, D1 A / D2 A / D3 B): w pamięci
 * jest tylko to, co rekruter ruszył i co różni się od zapisanego stanu pary;
 * odznaczone rekrutacje zachowują wpisy, zapis je czyści, karta przeglądarki
 * trzyma pamięć najwyżej 12 h.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";
import type { JointGroup, JointPair } from "@/lib/joint-screening";
import { jointDefaults } from "@/lib/joint-screening";
import {
  emptyMemory,
  jointRestore,
  memoryAfterSave,
  memoryFromJoint,
  memoryFromSingle,
  memoryPairSummary,
  singleRestore,
  type ScreeningMemory,
} from "@/lib/screening-memory";
import {
  SCREENING_MEMORY_TTL_MS,
  clearScreeningMemories,
  readStoredScreeningMemory,
  writeStoredScreeningMemory,
} from "@/lib/screening-memory-storage";
import { formDefaultsFromState } from "@/lib/screening-form";
import { readScreeningMemory, useScreeningMemoryStore } from "@/store/screening-memory";

const NOW = 1_800_000_000_000;

function jointPair(jobId: number, anchor: boolean, questions: Array<{ id: string; question: string }>): JointPair {
  return {
    jobId,
    title: `Rekrutacja ${jobId}`,
    clientId: jobId,
    clientName: null,
    budgetHourly: null,
    verifiedStageDefId: 1,
    anchor,
    state: formState({
      job_id: jobId,
      champion_profile: { screening_questions: questions.map((q) => ({ ...q, ideal_answer: "", deal_breaker: "" })) },
    }),
  };
}

const A = jointPair(201, true, [{ id: "q1", question: "Ile lat z Javą?" }]);
const B = jointPair(202, false, [
  { id: "q9", question: "Ile lat z Javą?" },
  { id: "q2", question: "Kafka?" },
]);
const C = jointPair(203, false, [{ id: "q1", question: "Oracle?" }]);
/** Wspólne pytanie A.q1 = B.q9, reszta osobno. */
const GROUPS_AB: JointGroup[] = [
  { key: "g0", members: [{ jobId: 201, questionId: "q1" }, { jobId: 202, questionId: "q9" }] },
  { key: "g1", members: [{ jobId: 202, questionId: "q2" }] },
];

describe("memoryFromJoint", () => {
  it("an untouched form leaves nothing in memory", () => {
    const values = jointDefaults([A, B], GROUPS_AB);
    expect(memoryFromJoint(null, { anchorJobId: 201, pairs: [A, B], groups: GROUPS_AB, values, dirty: {}, origins: {}, note: null, now: NOW })).toBeNull();
  });

  it("a shared answer is kept per recruitment and question; unchecked recruitments keep theirs", () => {
    const values = jointDefaults([A, B], GROUPS_AB);
    values.answers.g0 = "9 lat";
    const prev: ScreeningMemory = {
      ...emptyMemory(201, NOW - 1000),
      pairs: { "203": { touchedAt: NOW - 1000, answers: { q1: "Rok" } } },
    };
    const memory = memoryFromJoint(prev, {
      anchorJobId: 201,
      pairs: [A, B],
      groups: GROUPS_AB,
      values,
      dirty: { answers: { g0: true } },
      origins: {},
      note: null,
      now: NOW,
    });
    expect(memory?.pairs["201"]?.answers).toEqual({ q1: "9 lat" });
    expect(memory?.pairs["202"]?.answers).toEqual({ q9: "9 lat" });
    expect(memory?.pairs["203"]?.answers).toEqual({ q1: "Rok" });
    expect(memory?.selected).toEqual([202]);
    expect(memoryPairSummary(memory, 203)).toEqual({ answers: 1, any: true });
  });

  it("what the server already has (also with extra spaces) is not unsaved", () => {
    const saved = {
      ...A,
      state: { ...A.state, sheet: { answers: [{ question_id: "q1", response: "9 lat", deal_breaker_hit: false }], overall_fit: "uncertain", notes: "" } } as JointPair["state"],
    };
    const values = jointDefaults([saved], [GROUPS_AB[0]]);
    values.answers.g0 = "9 lat ";
    const memory = memoryFromJoint(null, {
      anchorJobId: 201,
      pairs: [saved],
      groups: [{ key: "g0", members: [{ jobId: 201, questionId: "q1" }] }],
      values,
      dirty: { answers: { g0: true } },
      origins: {},
      note: null,
      now: NOW,
    });
    expect(memory).toBeNull();
  });
});

describe("jointRestore", () => {
  it("a shared question takes the answer of the recruitment that was in the conversation last", () => {
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: {
        "201": { touchedAt: NOW, answers: { q1: "10 lat" } },
        "202": { touchedAt: NOW - 5000, answers: { q9: "9 lat", q2: "Tak" } },
      },
    };
    const values = jointDefaults([A, B], GROUPS_AB);
    const restore = jointRestore(memory, [A, B], GROUPS_AB, values);
    expect(restore.patches).toEqual(
      expect.arrayContaining([
        { path: "answers.g0", value: "10 lat" },
        { path: "answers.g1", value: "Tak" },
      ]),
    );
  });

  it("restores only what belongs to the recruitments on screen", () => {
    const memory: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      pairs: { "203": { touchedAt: NOW, answers: { q1: "Rok" }, overall_fit: "miss" } },
    };
    const values = jointDefaults([A, B], GROUPS_AB);
    expect(jointRestore(memory, [A, B], GROUPS_AB, values).patches).toEqual([]);
    const withC = jointDefaults([A, C], [{ key: "g0", members: [{ jobId: 201, questionId: "q1" }] }, { key: "g1", members: [{ jobId: 203, questionId: "q1" }] }]);
    const patches = jointRestore(
      memory,
      [A, C],
      [{ key: "g0", members: [{ jobId: 201, questionId: "q1" }] }, { key: "g1", members: [{ jobId: 203, questionId: "q1" }] }],
      withC,
    ).patches;
    expect(patches).toEqual(
      expect.arrayContaining([
        { path: "answers.g1", value: "Rok" },
        { path: "jobs.j203.overall_fit", value: "miss" },
      ]),
    );
  });
});

describe("memoryAfterSave (D2 A)", () => {
  const memory: ScreeningMemory = {
    ...emptyMemory(201, NOW),
    pairs: {
      "201": { touchedAt: NOW, answers: { q1: "9 lat" } },
      "202": { touchedAt: NOW, answers: { q9: "9 lat" } },
      "203": { touchedAt: NOW, answers: { q1: "Rok" } },
    },
    shared: { card: { availability: "od 1.12" } },
  };

  it("a successful save clears the whole conversation, unchecked recruitments too", () => {
    expect(memoryAfterSave(memory, [], NOW)).toBeNull();
  });

  it("a pair whose save failed keeps its entries and the fields about the person", () => {
    const after = memoryAfterSave(memory, [202], NOW);
    expect(Object.keys(after?.pairs ?? {})).toEqual(["202"]);
    expect(after?.shared.card).toEqual({ availability: "od 1.12" });
  });
});

describe("formularz pojedynczy", () => {
  const state = formState({ job_id: 201 });

  it("the rate typed in the joint conversation comes to the single form; split rates stay per recruitment", () => {
    const shared: ScreeningMemory = {
      ...emptyMemory(201, NOW),
      shared: { same_rate: true, rate: { rate_amount: "160", rate_unit: "hourly", rate_currency: "PLN" } },
    };
    expect(singleRestore(shared, state).patches).toEqual(expect.arrayContaining([["rate_amount", "160"]]));
    const split: ScreeningMemory = {
      ...shared,
      shared: { ...shared.shared, same_rate: false },
      pairs: { "201": { touchedAt: NOW, rate: { rate_amount: "150", rate_unit: "hourly", rate_currency: "PLN" } } },
    };
    const restore = singleRestore(split, state);
    expect(restore.patches).toEqual(expect.arrayContaining([["rate_amount", "150"]]));
    expect(restore.rateTouched).toBe(true);
  });

  it("a rate the recruiter did not set (start value) is not remembered", () => {
    const values = { ...formDefaultsFromState(state), rate_amount: "140" };
    const input = { anchorJobId: 201, state, values, dirty: {}, note: null, now: NOW };
    expect(memoryFromSingle(null, { ...input, rateTouched: false })).toBeNull();
    // Stawka z formularza pojedynczego jest stawką tej rekrutacji.
    expect(memoryFromSingle(null, { ...input, rateTouched: true })?.pairs["201"]?.rate?.rate_amount).toBe("140");
  });
});

describe("pamięć w karcie przeglądarki (D3 B)", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    useScreeningMemoryStore.setState({ entries: {} });
  });

  it("expires after 12 hours without changes", () => {
    writeStoredScreeningMemory(5, 101, emptyMemory(201, NOW));
    expect(readStoredScreeningMemory(5, 101, NOW + SCREENING_MEMORY_TTL_MS - 1)).not.toBeNull();
    expect(readStoredScreeningMemory(5, 101, NOW + SCREENING_MEMORY_TTL_MS + 1)).toBeNull();
    expect(window.sessionStorage.length).toBe(0);
  });

  it("a broken entry is no memory; logout clears only screening memories", () => {
    window.sessionStorage.setItem("nexus:screening-memory:v1:5:101", JSON.stringify({ v: 1, updatedAt: Date.now(), pairs: "x" }));
    window.sessionStorage.setItem("nexus:note-draft:v1:5:7:101", "szkic");
    expect(readScreeningMemory(5, 101)).toBeNull();
    clearScreeningMemories();
    expect(window.sessionStorage.getItem("nexus:screening-memory:v1:5:101")).toBeNull();
    expect(window.sessionStorage.getItem("nexus:note-draft:v1:5:7:101")).toBe("szkic");
  });
});

describe("przegląd przed PR-em (16.10.2026)", () => {
  const rate = (amount: number) => ({ amount, unit: "hourly" as const, currency: "PLN", source: "stage" as const, at: null });
  const QA = [{ id: "q1", question: "Ile lat z Javą?", ideal_answer: "", deal_breaker: "" }];
  const pairWith = (jobId: number, anchor: boolean, overrides: Partial<JointPair["state"]>): JointPair => ({
    ...jointPair(jobId, anchor, []),
    state: formState({ job_id: jobId, champion_profile: { screening_questions: QA }, ...overrides }),
  });
  const groups: JointGroup[] = [{ key: "g0", members: [{ jobId: 201, questionId: "q1" }, { jobId: 202, questionId: "q1" }] }];
  const ratePatch = (patches: Array<{ path: string; value: unknown }>, path: string) =>
    patches.find((p) => p.path === path)?.value;

  it("a rate typed for one recruitment (different start rates) comes back to that recruitment — joint first", () => {
    const a = pairWith(201, true, { rate: rate(120) });
    const b = pairWith(202, false, { rate: rate(100) });
    const values = jointDefaults([a, b], groups);
    expect(values.shared.same_rate).toBe(false);
    values.jobs.j201.rate_amount = "150";
    const joint = memoryFromJoint(null, {
      anchorJobId: 201,
      pairs: [a, b],
      groups,
      values,
      dirty: { jobs: { j201: { rate_amount: true } } },
      origins: {},
      note: null,
      now: NOW,
    });
    // Odznaczona B — formularz pojedynczy A bierze 150 i zapisuje pamięć po swojemu.
    const single = singleRestore(joint, a.state);
    expect(single.patches).toEqual(expect.arrayContaining([["rate_amount", "150"]]));
    const afterSingle = memoryFromSingle(joint, {
      anchorJobId: 201,
      state: a.state,
      values: { ...formDefaultsFromState(a.state), rate_amount: "150" },
      dirty: {},
      rateTouched: true,
      note: null,
      now: NOW + 1,
    });
    // B z powrotem — stawki osobno, A ma 150 w swoim polu.
    const restore = jointRestore(afterSingle, [a, b], groups, jointDefaults([a, b], groups));
    expect(ratePatch(restore.patches, "jobs.j201.rate_amount")).toBe("150");
  });

  it("a rate typed in the single form goes to that recruitment's own field in the joint form — single first", () => {
    const a = pairWith(201, true, { rate: rate(120) });
    const b = pairWith(202, false, { rate: rate(100) });
    const memory = memoryFromSingle(null, {
      anchorJobId: 201,
      state: a.state,
      values: { ...formDefaultsFromState(a.state), rate_amount: "150" },
      dirty: {},
      rateTouched: true,
      note: null,
      now: NOW,
    });
    const restore = jointRestore(memory, [a, b], groups, jointDefaults([a, b], groups));
    expect(ratePatch(restore.patches, "jobs.j201.rate_amount")).toBe("150");
  });

  it("a remembered answer equal to another recruitment's saved answer stays in memory", () => {
    const sheet = (response: string) =>
      ({ answers: [{ question_id: "q1", response, deal_breaker_hit: false }], overall_fit: "uncertain", notes: "" }) as never;
    const a = pairWith(201, true, {});
    const b = pairWith(202, false, { sheet: sheet("Tak") });
    const typed: ScreeningMemory = { ...emptyMemory(201, NOW), pairs: { "201": { touchedAt: NOW, answers: { q1: "Tak" } } } };
    // W formularzu wspólnym pole ma już „Tak” (odpowiedź B), więc przywrócenie nie robi go „ruszonym”.
    const values = jointDefaults([a, b], groups);
    expect(values.answers.g0).toBe("Tak");
    const memory = memoryFromJoint(typed, {
      anchorJobId: 201,
      pairs: [a, b],
      groups,
      values,
      dirty: {},
      origins: {},
      note: null,
      now: NOW + 1,
    });
    expect(memory?.pairs["201"]?.answers).toEqual({ q1: "Tak" });
  });

  it("„Czy pracował u Klienta” from the joint form comes back in the single form without the client id", () => {
    const card = { ...formState().card, editable_fields: ["worked_at_client", "rate"] } as JointPair["state"]["card"];
    const a = pairWith(201, true, { card });
    const values = jointDefaults([a], [{ key: "g0", members: [{ jobId: 201, questionId: "q1" }] }]);
    values.clients.c201 = "Tak, 2019–2021";
    const memory = memoryFromJoint(null, {
      anchorJobId: 201,
      pairs: [a],
      groups: [{ key: "g0", members: [{ jobId: 201, questionId: "q1" }] }],
      values,
      dirty: { clients: { c201: true } },
      origins: {},
      note: null,
      now: NOW,
    });
    expect(singleRestore(memory, a.state).patches).toEqual(
      expect.arrayContaining([["card.worked_at_client", "Tak, 2019–2021"]]),
    );
  });
});
