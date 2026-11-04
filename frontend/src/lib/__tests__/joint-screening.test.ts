import { describe, expect, it } from "vitest";

import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";
import {
  JOINT_MAX_OTHERS,
  budgetVerdict,
  completeGroups,
  dealBreakerHit,
  forwardBlockers,
  hitKey,
  jobKey,
  jointDefaults,
  noteFillPatches,
  projectPair,
  type JointPair,
} from "@/lib/joint-screening";
import { buildSavePayload } from "@/lib/screening-form";

const QA = [
  { id: "q1", question: "Jak używałeś RxJS w produkcji?", ideal_answer: "", deal_breaker: "" },
  { id: "q2", question: "Czy 2 dni w biurze są OK?", ideal_answer: "", deal_breaker: "Tylko zdalnie" },
];
const QB = [
  { id: "q1", question: "Od kiedy możesz zacząć?", ideal_answer: "", deal_breaker: "" },
  { id: "q2", question: "Jak używałeś RxJS w produkcji?", ideal_answer: "", deal_breaker: "" },
];

function pair(jobId: number, questions: typeof QA, overrides: Partial<JointPair> = {}, state = {}): JointPair {
  return {
    jobId,
    title: `Rekrutacja ${jobId}`,
    clientId: jobId,
    clientName: `Klient ${jobId}`,
    budgetHourly: 100,
    verifiedStageDefId: 900 + jobId,
    anchor: false,
    state: formState({ job_id: jobId, champion_profile: { screening_questions: questions }, ...state }),
    ...overrides,
  };
}

const A = pair(1, QA, { anchor: true });
const B = pair(2, QB);
const SERVER = [[{ job_id: 1, question_id: "q1" }, { job_id: 2, question_id: "q2" }]];

describe("joint screening — grupy i wartości startowe", () => {
  it("adds every ungrouped question exactly once", () => {
    const groups = completeGroups([A, B], SERVER);
    expect(groups.map((g) => g.members.map((m) => `${m.jobId}:${m.questionId}`))).toEqual([
      ["1:q1", "2:q2"],
      ["1:q2"],
      ["2:q1"],
    ]);
  });

  it("fills shared terms from whichever pair has them, anchor first", () => {
    const withB = pair(2, QB, {}, {
      card: {
        ...formState().card,
        fields: { availability: { raw: "od 1.11", source: "manual" } as never },
      },
    });
    const values = jointDefaults([A, withB], completeGroups([A, withB], SERVER));
    expect(values.shared.card.availability).toBe("od 1.11");
    expect(values.jobs[jobKey(1)].card).toHaveProperty("recommendation", "");
    expect(values.jobs[jobKey(1)].card).not.toHaveProperty("availability");
  });

  it("starts with one shared rate only when the pairs agree", () => {
    const rated = (jobId: number, amount: number) =>
      pair(jobId, QA, {}, { rate: { amount, unit: "hourly", currency: "PLN", source: "stage", at: null } });
    expect(jointDefaults([rated(1, 110), rated(2, 110)], []).shared.same_rate).toBe(true);
    const split = jointDefaults([rated(1, 110), rated(2, 130)], []);
    expect(split.shared.same_rate).toBe(false);
    expect(split.jobs[jobKey(2)].rate_amount).toBe("130");
  });
});

describe("joint screening — rzut na parę", () => {
  const groups = completeGroups([A, B], SERVER);

  it("writes a shared answer under each job's own question id", () => {
    const values = jointDefaults([A, B], groups);
    values.answers[groups[0].key] = "Formularze na strumieniach";
    values.answers[groups[1].key] = "Nie — tylko zdalnie";
    values.hits[hitKey(1, "q2")] = true;
    const dirty = { answers: { [groups[0].key]: true, [groups[1].key]: true }, hits: { [hitKey(1, "q2")]: true } };
    const a = projectPair(values, A, groups, dirty);
    const b = projectPair(values, B, groups, dirty);
    expect(a.answers.q1.response).toBe("Formularze na strumieniach");
    expect(b.answers.q2.response).toBe("Formularze na strumieniach");
    expect(b.answers.q1.response).toBe("");
    expect(a.answers.q2.deal_breaker_hit).toBe(true);
    expect(dealBreakerHit(A, a)).toBe(true);
    expect(dealBreakerHit(B, b)).toBe(false);
    // Zapis każdej pary niesie wyłącznie jej identyfikatory pytań.
    const plan = buildSavePayload(B.state, b);
    expect(plan.payload.job_id).toBe(2);
    expect(plan.payload.sheet?.answers.map((x) => x.question_id)).toEqual(["q1", "q2"]);
  });

  it("an untouched shared field only fills empty pairs; a touched one goes everywhere", () => {
    const filled = pair(2, QB, {}, {
      card: { ...formState().card, fields: { availability: { raw: "od 1.12", source: "manual" } as never } },
    });
    const g = completeGroups([A, filled], SERVER);
    const values = jointDefaults([A, filled], g);
    values.shared.card.availability = "asap";
    expect(projectPair(values, A, g).card.availability).toBe("asap");
    expect(projectPair(values, filled, g).card.availability).toBe("od 1.12");
    expect(projectPair(values, filled, g, { shared: { card: { availability: true } } }).card.availability).toBe("asap");
  });

  // Zgłoszenie rekrutera 29.10.2026: w jednym projekcie 1 dzień z biura,
  // w drugim 2 — tryb pracy wpisuje się osobno dla każdej rekrutacji.
  it("work mode is kept per recruitment, not shared", () => {
    const filled = pair(2, QB, {}, {
      card: { ...formState().card, fields: { work_mode: { raw: "zdalnie", source: "manual" } as never } },
    });
    const g = completeGroups([A, filled], SERVER);
    const values = jointDefaults([A, filled], g);
    expect(values.shared.card).not.toHaveProperty("work_mode");
    expect(values.jobs[jobKey(1)].card.work_mode).toBe("");
    expect(values.jobs[jobKey(2)].card.work_mode).toBe("zdalnie");
    values.jobs[jobKey(1)].card.work_mode = "1 dzień z biura";
    values.jobs[jobKey(2)].card.work_mode = "2 dni z biura";
    const dirty = { jobs: { [jobKey(1)]: { card: { work_mode: true } }, [jobKey(2)]: { card: { work_mode: true } } } };
    expect(projectPair(values, A, g, dirty).card.work_mode).toBe("1 dzień z biura");
    expect(projectPair(values, filled, g, dirty).card.work_mode).toBe("2 dni z biura");
    expect(projectPair(values, filled, g).card.work_mode).toBe("zdalnie");
  });

  const rated = (jobId: number, amount: number | null, overrides: Partial<JointPair> = {}) =>
    pair(jobId, QA, overrides, {
      rate: amount == null ? null : { amount, unit: "hourly", currency: "PLN", source: "stage", at: null },
    });

  it("the shared rate on screen is the rate saved — also for a pair that had none", () => {
    const a = rated(1, null, { anchor: true });
    const b = rated(2, 150);
    const values = jointDefaults([a, b], []);
    expect(values.shared.same_rate).toBe(true);
    expect(values.shared.rate_amount).toBe("150");
    expect(projectPair(values, a, []).rate_amount).toBe("150");
    expect(buildSavePayload(a.state, projectPair(values, a, [])).payload.rate?.amount).toBe(150);
    expect(projectPair(values, b, []).rate_amount).toBe("150");
  });

  it("different rates stay per recruitment until „Ta sama stawka” is ticked", () => {
    const a = rated(1, 110, { anchor: true });
    const b = rated(2, 130);
    const values = jointDefaults([a, b], []);
    expect(values.shared.same_rate).toBe(false);
    expect(projectPair(values, b, []).rate_amount).toBe("130");
    values.jobs[jobKey(2)].rate_amount = "125";
    expect(projectPair(values, b, [], { jobs: { [jobKey(2)]: { rate_amount: true } } }).rate_amount).toBe("125");
    // Zaznaczenie „Ta sama stawka” bez zmiany kwoty: zapis = kwota widoczna w polu.
    values.shared.same_rate = true;
    expect(projectPair(values, b, [], { shared: { same_rate: true } }).rate_amount).toBe("110");
    values.shared.rate_amount = "140";
    expect(projectPair(values, a, [], { shared: { same_rate: true, rate_amount: true } }).rate_amount).toBe("140");
  });

  it("untouched per-recruitment fields follow the fresh server state; touched ones win", () => {
    const withCard = (raw: string) =>
      pair(2, QB, {}, { card: { ...formState().card, fields: { recommendation: { raw, source: "manual" } as never } } });
    const old = withCard("R1");
    const values = jointDefaults([A, old], completeGroups([A, old], SERVER));
    // Ktoś zapisał tę parę obok — formularz wspólny ma jeszcze R1.
    const fresh = { ...withCard("R2 od kogoś"), state: { ...withCard("R2 od kogoś").state, version: 4, state_token: "T2" } };
    const g = completeGroups([A, fresh], SERVER);
    const untouched = buildSavePayload(fresh.state, projectPair(values, fresh, g));
    expect(untouched.payload.card?.fields ?? {}).not.toHaveProperty("recommendation");
    values.jobs[jobKey(2)].card.recommendation = "Moja";
    const touched = projectPair(values, fresh, g, { jobs: { [jobKey(2)]: { card: { recommendation: true } } } });
    expect(touched.card.recommendation).toBe("Moja");
  });

  it("an untouched shared question keeps the answer another recruitment already has", () => {
    const sheet = (question_id: string, response: string) =>
      ({ answers: [{ question_id, response, deal_breaker_hit: false }], overall_fit: "uncertain", notes: "" }) as never;
    const a = pair(1, QA, { anchor: true }, { sheet: sheet("q1", "Odpowiedź A") });
    const b = pair(2, QB, {}, { sheet: sheet("q2", "Odpowiedź B zapisana") });
    const g = completeGroups([a, b], SERVER);
    const values = jointDefaults([a, b], g);
    expect(values.answers[g[0].key]).toBe("Odpowiedź A");
    expect(projectPair(values, b, g).answers.q2.response).toBe("Odpowiedź B zapisana");
    values.answers[g[0].key] = "Nowa w rozmowie";
    expect(projectPair(values, b, g, { answers: { [g[0].key]: true } }).answers.q2.response).toBe("Nowa w rozmowie");
  });

  it("question groups accept at most four recruitments, so at most three besides the anchor", () => {
    expect(JOINT_MAX_OTHERS).toBe(3);
  });

  it("names what blocks forwarding a pair", () => {
    const values = jointDefaults([A, B], groups);
    values.answers[groups[0].key] = "tak";
    expect(forwardBlockers(A, projectPair(values, A, groups))).toEqual(["1 pytanie bez odpowiedzi"]);
    values.answers[groups[2].key] = "od zaraz";
    expect(forwardBlockers(B, projectPair(values, B, groups))).toEqual([]);
  });
});

describe("budgetVerdict", () => {
  it("compares per hour and says how much over", () => {
    expect(budgetVerdict({ amount: 110, unit: "hourly", currency: "PLN" }, 95)).toEqual({
      tone: "over",
      label: "ponad budżet 95 zł/h (+16%)",
    });
    expect(budgetVerdict({ amount: 880, unit: "daily", currency: "PLN" }, 130).tone).toBe("ok");
    expect(budgetVerdict({ amount: 30, unit: "hourly", currency: "EUR" }, 130).tone).toBe("unknown");
  });
});

describe("noteFillPatches — notatka tylko w puste miejsca", () => {
  const groups = completeGroups([A, B], SERVER);

  it("fills empty shared terms, the shared answer once and the rate, never what is already there", () => {
    const values = jointDefaults([A, B], groups);
    const proposal = {
      fields: [
        { key: "availability", proposed: "od 1.11" },
        { key: "work_mode", proposed: "zdalnie" },
        { key: "rate", proposed: "110 zł/h", rate: { amount: 110, unit: "hourly", currency: "PLN" } },
        { key: "recommendation", proposed: "Mocny w RxJS" },
      ],
      answers: [{ question_id: "q2", sentence: "Strumienie w formularzach", keywords: "rxjs" }],
    } as never;
    const list = noteFillPatches(values, B, groups, proposal);
    const patches = Object.fromEntries(list.map((p) => [p.path, p.value]));
    expect(patches["shared.card.availability"]).toBe("od 1.11");
    expect(patches[`jobs.${jobKey(2)}.card.work_mode`]).toBe("zdalnie");
    expect(patches[`answers.${groups[0].key}`]).toBe("Strumienie w formularzach");
    expect(patches["shared.rate_amount"] ?? patches[`jobs.${jobKey(2)}.rate_amount`]).toBe("110");
    expect(patches[`jobs.${jobKey(2)}.card.recommendation`]).toBe("Mocny w RxJS");
    // Pochodzenie jedzie z wartością: pole z notatki, odpowiedź ułożona w zdanie.
    const origin = (path: string) => list.find((p) => p.path === path)?.origin;
    expect(origin("shared.card.availability")).toMatchObject({ value: "od 1.11" });
    expect(origin(`answers.${groups[0].key}`)).toEqual({
      value: "Strumienie w formularzach",
      origin: "phrased",
      keywords: "rxjs",
    });
    expect(origin("shared.rate_amount") ?? origin(`jobs.${jobKey(2)}.rate_amount`)).toBeUndefined();
  });
});

describe("joint screening — pochodzenie i „Pomiń brakujące”", () => {
  const groups = completeGroups([A, B], SERVER);
  const g0 = groups[0].key;

  it("a value from the note keeps its origin in every recruitment until someone edits it", () => {
    const values = jointDefaults([A, B], groups);
    values.shared.card.availability = "od 1.11";
    values.answers[g0] = "Strumienie w formularzach";
    const origins = {
      "shared.card.availability": { value: "od 1.11", origin: "note_ai" as const },
      [`answers.${g0}`]: { value: "Strumienie w formularzach", origin: "phrased" as const, keywords: "rxjs formularze" },
    };
    const dirty = { shared: { card: { availability: true } }, answers: { [g0]: true } };
    const b = buildSavePayload(B.state, projectPair(values, B, groups, dirty, origins)).payload;
    expect(b.card?.origins?.availability).toEqual({ origin: "note_ai" });
    expect(b.sheet?.answers.find((x) => x.question_id === "q2")).toMatchObject({
      origin: "phrased",
      keywords: "rxjs formularze",
    });
    const a = buildSavePayload(A.state, projectPair(values, A, groups, dirty, origins)).payload;
    expect(a.card?.origins?.availability).toEqual({ origin: "note_ai" });
    values.shared.card.availability = "od 15.11";
    const edited = buildSavePayload(B.state, projectPair(values, B, groups, dirty, origins)).payload;
    expect(edited.card?.origins ?? {}).not.toHaveProperty("availability");
  });

  it("an earlier answer used in a shared question is marked as Luna's suggestion, until edited", () => {
    const values = jointDefaults([A, B], groups);
    values.answers[g0] = "Strumienie od 2021";
    const origins = { [`answers.${g0}`]: { value: "Strumienie od 2021", origin: "reassign_suggested" as const } };
    const dirty = { answers: { [g0]: true } };
    expect(projectPair(values, A, groups, dirty, origins).answers.q1.origin).toBe("reassign_suggested");
    expect(projectPair(values, B, groups, dirty, origins).answers.q2.origin).toBe("reassign_suggested");
    values.answers[g0] = "Strumienie od 2021, teraz Signals";
    expect(projectPair(values, B, groups, dirty, origins).answers.q2.origin).toBe("manual");
  });

  it("„Pomiń brakujące” in one recruitment skips only its own empty questions", () => {
    const values = jointDefaults([A, B], groups);
    values.answers[g0] = "tak";
    values.jobs[jobKey(2)].skip_missing = true;
    values.jobs[jobKey(2)].skip_reason = "earlier_screening";
    const dirty = { answers: { [g0]: true }, jobs: { [jobKey(2)]: { skip_missing: true, skip_reason: true } } };
    const b = projectPair(values, B, groups, dirty);
    expect(forwardBlockers(B, b)).toEqual([]);
    expect(forwardBlockers(A, projectPair(values, A, groups, dirty))).toEqual(["1 pytanie bez odpowiedzi"]);
    const sheet = buildSavePayload(B.state, b).payload.sheet!;
    expect(sheet.answers.find((x) => x.question_id === "q1")?.skipped).toBe(true);
    expect(sheet.answers.find((x) => x.question_id === "q2")?.skipped).toBeUndefined();
    expect(sheet.internal_note).toBeTruthy();
  });
});

