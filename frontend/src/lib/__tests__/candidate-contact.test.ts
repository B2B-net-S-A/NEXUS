import { AxiosError, type AxiosResponse } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";

const http = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: http }));

import {
  buildCandidateContactAttemptInput,
  candidateContactApi,
  candidateContactFullName,
  candidateContactQueryKeys,
  isCandidateContactVersionConflict,
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

describe("buildCandidateContactAttemptInput — brzegi i odmowy", () => {
  const empty = { callbackAt: "", notes: "", opportunityOutcomes: {} };

  it("bez wyniku próby: tylko błąd wyniku, bez wymagań dla rekrutacji", () => {
    const result = buildCandidateContactAttemptInput(contactCase, {
      ...empty,
      outcome: null,
    });
    expect(result).toEqual({
      input: null,
      errors: { outcome: "Wybierz wynik próby." },
    });
  });

  it("rozmowa z wynikiem „może” wymaga terminu oddzwonienia", () => {
    const result = buildCandidateContactAttemptInput(contactCase, {
      ...empty,
      outcome: "connected",
      opportunityOutcomes: { 11: "interested", 12: "maybe" },
    });
    expect(result.input).toBeNull();
    expect(result.errors).toEqual({
      callback_at: "Wskaż prawidłowy termin oddzwonienia.",
    });
  });

  it("nieprawidłowa data oddzwonienia to błąd, a nie „Invalid Date” w payloadzie", () => {
    const result = buildCandidateContactAttemptInput(contactCase, {
      ...empty,
      outcome: "callback_requested",
      callbackAt: "jutro rano",
      opportunityOutcomes: { 11: "interested", 12: "interested" },
    });
    expect(result.input).toBeNull();
    expect(result.errors.callback_at).toBe("Wskaż prawidłowy termin oddzwonienia.");
  });

  it("wynik bez rozmowy ignoruje śmieciową datę i puste notatki", () => {
    const result = buildCandidateContactAttemptInput(contactCase, {
      outcome: "wrong_number",
      callbackAt: "nie-data",
      notes: "   ",
      opportunityOutcomes: {},
    });
    expect(result.errors).toEqual({});
    expect(result.input).toEqual({
      expected_version: 9,
      outcome: "wrong_number",
      callback_at: null,
      notes: null,
      opportunity_outcomes: [],
    });
  });

  it("rozmowa bez otwartych rekrutacji nie wymaga wyników procesów", () => {
    const result = buildCandidateContactAttemptInput(
      { ...contactCase, opportunities: [] },
      { ...empty, outcome: "connected" },
    );
    expect(result.errors).toEqual({});
    expect(result.input?.opportunity_outcomes).toEqual([]);
  });
});

describe("candidateContactFullName i konflikt wersji", () => {
  it("skleja imię i nazwisko, a bez obu pokazuje „Kandydat”", () => {
    expect(candidateContactFullName({ id: 1, name: "Anna", lastname: "Testowa" })).toBe(
      "Anna Testowa",
    );
    expect(candidateContactFullName({ id: 1, name: "Anna", lastname: null })).toBe("Anna");
    expect(candidateContactFullName({ id: 1, lastname: "Testowa" })).toBe("Testowa");
    expect(candidateContactFullName({ id: 1, name: " ", lastname: "" })).toBe("Kandydat");
  });

  it("konflikt to wyłącznie odpowiedź 409 z axiosa", () => {
    const axiosError = (status: number) =>
      new AxiosError("x", "ERR", undefined, undefined, {
        status,
      } as AxiosResponse);
    expect(isCandidateContactVersionConflict(axiosError(409))).toBe(true);
    expect(isCandidateContactVersionConflict(axiosError(422))).toBe(false);
    expect(isCandidateContactVersionConflict(new AxiosError("sieć"))).toBe(false);
    const lookalike = Object.assign(new Error("409"), { response: { status: 409 } });
    expect(isCandidateContactVersionConflict(lookalike)).toBe(false);
    expect(isCandidateContactVersionConflict(null)).toBe(false);
  });

  it("klucze zapytań mają wspólny przedrostek do unieważniania", () => {
    expect(candidateContactQueryKeys.candidate(7)).toEqual(["candidate-contact", "candidate", 7]);
    for (const key of [
      candidateContactQueryKeys.status(),
      candidateContactQueryKeys.queue(),
      candidateContactQueryKeys.oversight(),
    ]) {
      expect(key[0]).toBe(candidateContactQueryKeys.all[0]);
    }
  });
});

describe("candidateContactApi — trasy i treść żądań", () => {
  beforeEach(() => {
    http.get.mockReset().mockResolvedValue({ data: { ok: "get" } });
    http.post.mockReset().mockResolvedValue({ data: { ok: "post" } });
  });

  it("odczyty zwracają samo `data` i przekazują parametry stronicowania", async () => {
    await expect(candidateContactApi.status()).resolves.toEqual({ ok: "get" });
    expect(http.get).toHaveBeenLastCalledWith("/api/candidate-contact/status");

    await candidateContactApi.queue({ cursor: "abc", limit: 20 });
    expect(http.get).toHaveBeenLastCalledWith("/api/candidate-contact/queue", {
      params: { cursor: "abc", limit: 20 },
    });

    await candidateContactApi.queue();
    expect(http.get).toHaveBeenLastCalledWith("/api/candidate-contact/queue", {
      params: undefined,
    });

    await candidateContactApi.forCandidate(42);
    expect(http.get).toHaveBeenLastCalledWith("/api/candidate-contact/candidates/42");

    await candidateContactApi.oversight({ limit: 5 });
    expect(http.get).toHaveBeenLastCalledWith("/api/candidate-contact/oversight", {
      params: { limit: 5 },
    });
  });

  it("próba kontaktu idzie z kluczem idempotencji w nagłówku", async () => {
    const input = {
      expected_version: 3,
      outcome: "no_answer" as const,
      opportunity_outcomes: [],
    };
    await expect(candidateContactApi.logAttempt(40, input, "klucz-1")).resolves.toEqual({
      ok: "post",
    });
    expect(http.post).toHaveBeenCalledWith("/api/candidate-contact/cases/40/attempts", input, {
      headers: { "Idempotency-Key": "klucz-1" },
    });
  });

  it("przepięcie wysyła wersję i powód; błąd serwera przechodzi dalej", async () => {
    const input = { expected_version: 3, target_user_id: null, reason: "urlop" };
    await candidateContactApi.reassign(40, input);
    expect(http.post).toHaveBeenCalledWith("/api/candidate-contact/cases/40/reassign", input);

    http.post.mockRejectedValueOnce(new Error("409"));
    await expect(candidateContactApi.reassign(40, input)).rejects.toThrow("409");
  });
});
