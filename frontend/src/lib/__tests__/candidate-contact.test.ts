import { describe, expect, it } from "vitest";

import {
  buildCandidateContactAttemptInput,
  type CandidateContactCase,
} from "@/lib/candidate-contact";

const contactCase: CandidateContactCase = {
  id: 40,
  status: "queued",
  due_at: "2026-07-28T16:00:00Z",
  callback_at: null,
  attempts_in_cycle: 0,
  version: 9,
  owner: { id: 2, name: "Marta Nowak" },
  candidate: {
    id: 7,
    name: "Jan",
    lastname: "Kowalski",
    phone: "+48 500 100 200",
  },
  opportunities: [
    { job_id: 11, job_title: "Java Developer" },
    { job_id: 12, job_title: "Tech Lead" },
  ],
};

describe("buildCandidateContactAttemptInput", () => {
  it("requires a result for every open job after a connected call", () => {
    const result = buildCandidateContactAttemptInput(contactCase, {
      outcome: "connected",
      callbackAt: "",
      notes: "",
      opportunityOutcomes: {
        11: "interested",
      },
    });

    expect(result.input).toBeNull();
    expect(result.errors).toEqual({
      "job-12": "Wybierz wynik dla tej rekrutacji.",
    });
  });

  it("keeps one expected version and all job outcomes in the payload", () => {
    const result = buildCandidateContactAttemptInput(contactCase, {
      outcome: "connected",
      callbackAt: "",
      notes: " Kandydat zna obie oferty. ",
      opportunityOutcomes: {
        11: "interested",
        12: "not_interested",
      },
    });

    expect(result.errors).toEqual({});
    expect(result.input).toEqual({
      expected_version: 9,
      outcome: "connected",
      callback_at: null,
      notes: "Kandydat zna obie oferty.",
      opportunity_outcomes: [
        { job_id: 11, outcome: "interested" },
        { job_id: 12, outcome: "not_interested" },
      ],
    });
  });

  it("requires callback for a requested callback and a maybe result", () => {
    const withoutDate = buildCandidateContactAttemptInput(contactCase, {
      outcome: "callback_requested",
      callbackAt: "",
      notes: "",
      opportunityOutcomes: {
        11: "maybe",
        12: "not_presented",
      },
    });
    expect(withoutDate.input).toBeNull();
    expect(withoutDate.errors.callback_at).toBeTruthy();

    const withDate = buildCandidateContactAttemptInput(contactCase, {
      outcome: "callback_requested",
      callbackAt: "2026-07-30T10:30",
      notes: "",
      opportunityOutcomes: {
        11: "maybe",
        12: "not_presented",
      },
    });
    expect(withDate.input?.callback_at).toBe(
      new Date("2026-07-30T10:30").toISOString(),
    );
  });

  it("ignores stale job decisions after switching to a non-conversation result", () => {
    const result = buildCandidateContactAttemptInput(contactCase, {
      outcome: "no_answer",
      callbackAt: "",
      notes: "",
      opportunityOutcomes: {
        11: "maybe",
        12: "not_presented",
      },
    });

    expect(result.errors).toEqual({});
    expect(result.input).toMatchObject({
      outcome: "no_answer",
      callback_at: null,
      opportunity_outcomes: [],
    });
  });
});
