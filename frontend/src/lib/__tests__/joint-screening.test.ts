import { describe, expect, it } from "vitest";

import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";
import {
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
    const a = projectPair(values, A, groups);
    const b = projectPair(values, B, groups);
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
      card: { ...formState().card, fields: { work_mode: { raw: "zdalnie", source: "manual" } as never } },
    });
    const g = completeGroups([A, filled], SERVER);
    const values = jointDefaults([A, filled], g);
    values.shared.card.work_mode = "hybrydowo";
    expect(projectPair(values, A, g).card.work_mode).toBe("hybrydowo");
    expect(projectPair(values, filled, g).card.work_mode).toBe("zdalnie");
    expect(projectPair(values, filled, g, { shared: { card: { work_mode: true } } }).card.work_mode).toBe("hybrydowo");
  });

  it("an untouched shared rate keeps each pair's own start rate; touched — the shared one", () => {
    const values = jointDefaults([A, B], groups);
    values.jobs[jobKey(2)].rate_amount = "120";
    values.shared.rate_amount = "110";
    expect(projectPair(values, B, groups).rate_amount).toBe("120");
    expect(projectPair(values, B, groups, { shared: { rate_amount: true } }).rate_amount).toBe("110");
    values.shared.same_rate = false;
    expect(projectPair(values, B, groups, { shared: { rate_amount: true } }).rate_amount).toBe("120");
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
    values.shared.card.work_mode = "hybrydowo";
    const proposal = {
      fields: [
        { key: "availability", proposed: "od 1.11" },
        { key: "work_mode", proposed: "zdalnie" },
        { key: "rate", proposed: "110 zł/h", rate: { amount: 110, unit: "hourly", currency: "PLN" } },
        { key: "recommendation", proposed: "Mocny w RxJS" },
      ],
      answers: [{ question_id: "q2", sentence: "Strumienie w formularzach", keywords: "rxjs" }],
    } as never;
    const patches = Object.fromEntries(noteFillPatches(values, B, groups, proposal));
    expect(patches["shared.card.availability"]).toBe("od 1.11");
    expect(patches).not.toHaveProperty("shared.card.work_mode");
    expect(patches[`answers.${groups[0].key}`]).toBe("Strumienie w formularzach");
    expect(patches["shared.rate_amount"] ?? patches[`jobs.${jobKey(2)}.rate_amount`]).toBe("110");
    expect(patches[`jobs.${jobKey(2)}.card.recommendation`]).toBe("Mocny w RxJS");
  });
});
