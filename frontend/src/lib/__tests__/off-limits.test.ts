// @vitest-environment jsdom
import { act, fireEvent, render, screen } from "@testing-library/react";
import { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { offLimitsCardBadge } from "@/lib/board-card-badges";
import {
  OFF_LIMITS_CODE,
  OFF_LIMITS_HEADER,
  askOffLimits,
  offLimitsHeaderValue,
  offLimitsOthersInRequest,
  offLimitsPeopleFrom,
  registerOffLimitsHost,
  type OffLimitsAnswers,
  type OffLimitsPerson,
} from "@/lib/off-limits";
import {
  OffLimitsConfirmHost,
  answersFromState,
} from "@/components/v2/recruitment/OffLimitsConfirmHost";

vi.mock("@/lib/telemetry-capability", () => ({
  apiSupportsCorrelation: () => false,
  probeTelemetryCapability: vi.fn().mockResolvedValue(undefined),
}));

const ANNA: OffLimitsPerson = {
  candidate_id: 7,
  name: "Anna Testowa",
  company: "Nordea Bank Abp",
  client_name: "Nordea",
  source: "linkedin",
};

function conflict(config: InternalAxiosRequestConfig, people = [ANNA]): AxiosError {
  const data = { detail: { code: OFF_LIMITS_CODE, message: "…", candidates: people } };
  return new AxiosError("Request failed with status code 409", "409", config, {}, {
    config,
    data,
    headers: {},
    status: 409,
    statusText: "",
  });
}

async function post(
  answer: OffLimitsAnswers | null,
): Promise<{ seenHeaders: (string | undefined)[]; result: unknown; error: unknown }> {
  const unregister = registerOffLimitsHost(async () => answer);
  const seenHeaders: (string | undefined)[] = [];
  try {
    const result = await api.post(
      "/api/pipeline/move",
      { candidate_id: 7 },
      {
        adapter: async (config) => {
          const header = config.headers.get(OFF_LIMITS_HEADER);
          seenHeaders.push(typeof header === "string" ? header : undefined);
          if (!header) throw conflict(config);
          return { data: { ok: true }, status: 200, statusText: "OK", headers: {}, config };
        },
      },
    );
    return { seenHeaders, result: result.data, error: null };
  } catch (error) {
    return { seenHeaders, result: null, error };
  } finally {
    unregister();
  }
}

afterEach(() => vi.restoreAllMocks());

describe("odpowiedź 409 off-limits", () => {
  it("czyta osoby tylko z właściwego kodu", () => {
    const config = {} as InternalAxiosRequestConfig;
    expect(offLimitsPeopleFrom(conflict(config))).toEqual([ANNA]);
    expect(offLimitsPeopleFrom(new Error("x"))).toBeNull();
    const other = conflict(config);
    (other.response!.data as { detail: { code: string } }).detail.code = "eligibility_warning";
    expect(offLimitsPeopleFrom(other)).toBeNull();
  });

  it("nagłówek nie powstaje, gdy wszyscy dostali „Nie, to my”", () => {
    expect(offLimitsHeaderValue({ 7: "skip" })).toBeNull();
    expect(offLimitsHeaderValue({})).toBeNull();
    expect(JSON.parse(offLimitsHeaderValue({ 7: "job_ad", 8: "skip" })!)).toEqual({
      7: "job_ad",
      8: "skip",
    });
  });
});

describe("interceptor `api`", () => {
  it("po potwierdzeniu ponawia to samo żądanie z nagłówkiem — raz", async () => {
    const { seenHeaders, result, error } = await post({ 7: "linkedin_inbound" });
    expect(error).toBeNull();
    expect(result).toEqual({ ok: true });
    expect(seenHeaders).toEqual([undefined, JSON.stringify({ 7: "linkedin_inbound" })]);
  });

  it("„Nie, to my” kończy się czytelnym błędem bez ponowienia", async () => {
    const { seenHeaders, error } = await post({ 7: "skip" });
    expect(seenHeaders).toHaveLength(1);
    expect(apiErrorMessage(error, "fallback")).toBe(
      "Nie dodano — Anna Testowa pracuje w firmie Nordea, a stamtąd nie wyciągamy ludzi.",
    );
  });

  it("zamknięte okno = brak potwierdzenia", async () => {
    const { seenHeaders, error } = await post(null);
    expect(seenHeaders).toHaveLength(1);
    expect(error).not.toBeNull();
  });
});

describe("partia z osobą off-limits (audyt 22.10, F72)", () => {
  it("rozpoznaje w żądaniu osoby spoza okna", () => {
    expect(offLimitsOthersInRequest(JSON.stringify({ candidate_ids: [7, 8, 9] }), [ANNA])).toBe(
      true,
    );
    expect(offLimitsOthersInRequest({ candidate_ids: [7] }, [ANNA])).toBe(false);
    expect(offLimitsOthersInRequest(JSON.stringify({ candidate_id: 7 }), [ANNA])).toBe(false);
    expect(offLimitsOthersInRequest("nie-json", [ANNA])).toBe(false);
    expect(offLimitsOthersInRequest(undefined, [ANNA])).toBe(false);
  });

  it("same „Nie, to my” dają nagłówek, gdy reszta partii ma się dodać", () => {
    expect(JSON.parse(offLimitsHeaderValue({ 7: "skip" }, true)!)).toEqual({ 7: "skip" });
    expect(offLimitsHeaderValue({ 7: "skip" }, false)).toBeNull();
  });

  it("„Nie, to my” przy jednej z trzech osób ponawia partię — reszta się dodaje", async () => {
    const unregister = registerOffLimitsHost(async () => ({ 7: "skip" }));
    const seenHeaders: (string | undefined)[] = [];
    try {
      const result = await api.post(
        "/api/proposals/bulk",
        { job_id: 1, candidate_ids: [7, 8, 9] },
        {
          adapter: async (config) => {
            const header = config.headers.get(OFF_LIMITS_HEADER);
            seenHeaders.push(typeof header === "string" ? header : undefined);
            if (!header) throw conflict(config);
            return {
              data: { total_added: 2 },
              status: 200,
              statusText: "OK",
              headers: {},
              config,
            };
          },
        },
      );
      expect(result.data).toEqual({ total_added: 2 });
      expect(seenHeaders).toEqual([undefined, JSON.stringify({ 7: "skip" })]);
    } finally {
      unregister();
    }
  });

  it("okno partii mówi „Pomiń te osoby”, a nie „Nie dodawaj”", async () => {
    render(createElement(OffLimitsConfirmHost));
    let answered: Promise<OffLimitsAnswers | null> = Promise.resolve(null);
    act(() => {
      answered = askOffLimits([ANNA], { othersInRequest: true });
    });
    fireEvent.click(await screen.findByLabelText(/Nie, to my się odezwaliśmy/));
    fireEvent.click(screen.getByRole("button", { name: "Pomiń te osoby" }));
    await expect(answered).resolves.toEqual({ 7: "skip" });
  });
});

describe("okno potwierdzenia", () => {
  const people = [ANNA, { ...ANNA, candidate_id: 8, name: "Jan Testowy" }];

  it("bez odpowiedzi przy każdej osobie nie ma czego wysłać", () => {
    expect(answersFromState(people, { 7: { choice: "self", how: "job_ad" } })).toBeNull();
  });

  it("zamienia wybory na odpowiedzi serwera", () => {
    expect(
      answersFromState(people, {
        7: { choice: "self", how: "referral" },
        8: { choice: "us", how: "linkedin_inbound" },
      }),
    ).toEqual({ 7: "referral", 8: "skip" });
    expect(answersFromState([ANNA], { 7: { choice: "left", how: "job_ad" } })).toEqual({
      7: "left_company",
    });
  });
});

describe("plakietka na karcie", () => {
  it("mówi, kto i jak potwierdził", () => {
    const badge = offLimitsCardBadge({
      client_name: "Nordea",
      company: "Nordea Bank Abp",
      how: "linkedin_inbound",
      how_label: "Napisał(a) do nas na LinkedInie",
      confirmed_by_id: 3,
      confirmed_by_name: "Jan Rekruter",
      confirmed_at: "2026-10-21T10:00:00+00:00",
    });
    expect(badge?.label).toBe("Off-limits · sam(a) się zgłosił(a)");
    expect(badge?.tone).toBe("wait");
    expect(badge?.title).toBe(
      "Nordea: stamtąd nie wyciągamy ludzi. Napisał(a) do nas na LinkedInie — potwierdził(a) Jan Rekruter, 21.10.",
    );
    expect(offLimitsCardBadge(null)).toBeNull();
  });
});
