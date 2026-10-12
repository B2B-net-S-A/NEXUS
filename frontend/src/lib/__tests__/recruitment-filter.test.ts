import { describe, expect, it } from "vitest";

import {
  patchForRecruitmentMode,
  patchForRecruitmentScope,
  patchForRemovedRecruitment,
  patchForRemovedRecruitmentClient,
  recruitmentLocksStageFields,
  recruitmentMode,
  type RecruitmentMode,
} from "@/lib/recruitment-filter";
import { DEFAULT_FILTERS, type CandidateFilters } from "@/lib/url-filters";

const f = (patch: Partial<CandidateFilters> = {}): CandidateFilters => ({
  ...DEFAULT_FILTERS,
  ...patch,
});
const apply = (filters: CandidateFilters, patch: Partial<CandidateFilters>): CandidateFilters => ({
  ...filters,
  ...patch,
});

const STAGE_SET: Partial<CandidateFilters> = {
  pipelineStage: ["cv_sent"],
  stageCurrentOnly: true,
  stageClientIds: [3],
  stageMovedByIds: [4],
  stageMovedAfter: "2026-05-01",
  stageMovedBefore: "2026-05-31",
  sentToClientFrom: "2026-06-01",
  sentToClientTo: "2026-06-30",
};
const STAGE_EMPTY: Partial<CandidateFilters> = {
  pipelineStage: [],
  stageCurrentOnly: false,
  stageClientIds: [],
  stageMovedByIds: [],
  stageMovedAfter: "",
  stageMovedBefore: "",
  sentToClientFrom: "",
  sentToClientTo: "",
};

describe("recruitmentMode — tryb bloku „Rekrutacje” wyliczany z czterech pól", () => {
  it("bez zakresu decyduje pytanie o jakąkolwiek rekrutację", () => {
    expect(recruitmentMode(f())).toBe("any");
    expect(recruitmentMode(f({ recruitmentPresence: "ever" }))).toBe("took_part");
    expect(recruitmentMode(f({ recruitmentPresence: "never" }))).toBe("did_not");
    expect(recruitmentMode(f({ recruitmentPresence: "not_in_process" }))).toBe("idle");
  });

  it("z zakresem decyduje kierunek — także gdy zakres to sam klient", () => {
    expect(recruitmentMode(f({ recruitmentIds: [7] }))).toBe("took_part");
    expect(recruitmentMode(f({ recruitmentIds: [7], recruitmentMatch: "not_assigned" }))).toBe(
      "did_not",
    );
    expect(
      recruitmentMode(f({ recruitmentClientIds: [3], recruitmentMatch: "not_assigned" })),
    ).toBe("did_not");
  });

  it("kierunek bez zakresu nic nie znaczy (stary adres z samym recr_mode)", () => {
    expect(recruitmentMode(f({ recruitmentMatch: "not_assigned" }))).toBe("any");
  });

  it("w oknie rekrutacji zakres wymusza zapytanie, więc ekran czyta sam tryb", () => {
    const forced = f({
      recruitmentIds: [7],
      recruitmentMatch: "not_assigned",
      recruitmentPresence: "not_in_process",
    });
    expect(recruitmentMode(forced, true)).toBe("idle");
    expect(recruitmentMode(f({ recruitmentIds: [7] }), true)).toBe("any");
  });
});

describe("patchForRecruitmentMode — wybór opcji", () => {
  const scoped = f({
    recruitmentIds: [7, 9],
    recruitmentClientIds: [3],
    recruitmentMatch: "assigned",
  });

  it("„Dowolnie” i „Bez procesu w toku” zdejmują zakres", () => {
    expect(patchForRecruitmentMode("any", scoped)).toEqual({
      recruitmentIds: [],
      recruitmentClientIds: [],
      recruitmentMatch: "assigned",
      recruitmentPresence: "",
    });
    expect(patchForRecruitmentMode("idle", scoped)).toEqual({
      recruitmentIds: [],
      recruitmentClientIds: [],
      recruitmentMatch: "assigned",
      recruitmentPresence: "not_in_process",
    });
  });

  it("przełączenie „brał / nie brał” zostawia wybrane rekrutacje i odwraca kierunek", () => {
    expect(patchForRecruitmentMode("did_not", scoped)).toEqual({
      recruitmentIds: [7, 9],
      recruitmentClientIds: [3],
      recruitmentMatch: "not_assigned",
      recruitmentPresence: "",
    });
    const negative = apply(scoped, { recruitmentMatch: "not_assigned" });
    expect(patchForRecruitmentMode("took_part", negative)).toMatchObject({
      recruitmentIds: [7, 9],
      recruitmentClientIds: [3],
      recruitmentMatch: "assigned",
      recruitmentPresence: "",
    });
  });

  it("bez zakresu „Brał udział” znaczy w jakiejkolwiek, „Nie brał udziału” — w żadnej", () => {
    expect(patchForRecruitmentMode("took_part", f())).toEqual({
      recruitmentIds: [],
      recruitmentClientIds: [],
      recruitmentMatch: "assigned",
      recruitmentPresence: "ever",
    });
    expect(patchForRecruitmentMode("did_not", f(STAGE_SET))).toEqual({
      recruitmentIds: [],
      recruitmentClientIds: [],
      recruitmentMatch: "assigned",
      recruitmentPresence: "never",
      // „W żadnej rekrutacji” z filtrem etapu dałoby zawsze zero wyników.
      ...STAGE_EMPTY,
    });
  });

  it("każda opcja prowadzi do stanu, który ekran odczyta jako tę opcję", () => {
    const modes: RecruitmentMode[] = ["any", "took_part", "did_not", "idle"];
    const starts = [
      f(),
      scoped,
      apply(scoped, { recruitmentMatch: "not_assigned" }),
      f({ recruitmentPresence: "never" }),
      f({ recruitmentPresence: "ever" }),
      f({ recruitmentPresence: "not_in_process" }),
    ];
    for (const start of starts) {
      for (const mode of modes) {
        expect(recruitmentMode(apply(start, patchForRecruitmentMode(mode, start)))).toBe(mode);
      }
    }
  });

  it("w oknie rekrutacji zmienia się tylko tryb — zakres należy do zapytania okna", () => {
    const start = f(STAGE_SET);
    expect(patchForRecruitmentMode("idle", start, true)).toEqual({
      recruitmentPresence: "not_in_process",
    });
    expect(patchForRecruitmentMode("took_part", start, true)).toEqual({
      recruitmentPresence: "ever",
    });
    expect(patchForRecruitmentMode("any", start, true)).toEqual({ recruitmentPresence: "" });
    expect(patchForRecruitmentMode("did_not", start, true)).toEqual({
      recruitmentPresence: "never",
      ...STAGE_EMPTY,
    });
  });
});

describe("patchForRecruitmentScope — zmiana na liście rekrutacji", () => {
  it("zaznaczenie pozycji zamienia „w jakiejkolwiek / w żadnej” na zakres", () => {
    expect(patchForRecruitmentScope([7], [3], f({ recruitmentPresence: "never" }))).toEqual({
      recruitmentIds: [7],
      recruitmentClientIds: [3],
      recruitmentMatch: "not_assigned",
      recruitmentPresence: "",
    });
    expect(patchForRecruitmentScope([7], [], f({ recruitmentPresence: "ever" }))).toEqual({
      recruitmentIds: [7],
      recruitmentClientIds: [],
      recruitmentMatch: "assigned",
      recruitmentPresence: "",
    });
  });

  it("odznaczenie wszystkiego w liście wraca do „Wszystkie rekrutacje”, nie do „Dowolnie”", () => {
    const negative = f({ recruitmentIds: [7], recruitmentMatch: "not_assigned", ...STAGE_SET });
    const emptied = patchForRecruitmentScope([], [], negative);
    expect(emptied).toEqual({
      recruitmentIds: [],
      recruitmentClientIds: [],
      recruitmentMatch: "assigned",
      recruitmentPresence: "never",
      ...STAGE_EMPTY,
    });
    expect(recruitmentMode(apply(negative, emptied))).toBe("did_not");

    const positive = f({ recruitmentClientIds: [3], ...STAGE_SET });
    expect(patchForRecruitmentScope([], [], positive)).toEqual({
      recruitmentIds: [],
      recruitmentClientIds: [],
      recruitmentMatch: "assigned",
      recruitmentPresence: "ever",
    });
  });
});

describe("zdjęcie chipa nad tabelą", () => {
  it("ostatnia pozycja zakresu zdejmuje cały filtr — nie zamienia go w „w żadnej”", () => {
    const one = f({ recruitmentIds: [7], recruitmentMatch: "not_assigned" });
    const after = apply(one, patchForRemovedRecruitment(one, 7));
    expect(after.recruitmentIds).toEqual([]);
    expect(after.recruitmentMatch).toBe("assigned");
    expect(recruitmentMode(after)).toBe("any");
  });

  it("zostaje reszta zakresu i jego kierunek", () => {
    const two = f({
      recruitmentIds: [7],
      recruitmentClientIds: [3],
      recruitmentMatch: "not_assigned",
    });
    expect(patchForRemovedRecruitment(two, 7)).toEqual({ recruitmentIds: [] });
    expect(patchForRemovedRecruitmentClient(two, 3)).toEqual({ recruitmentClientIds: [] });
    const after = apply(two, patchForRemovedRecruitmentClient(two, 3));
    expect(recruitmentMode(after)).toBe("did_not");
  });
});

describe("recruitmentLocksStageFields", () => {
  it("wyłącza etap i datę wysłania tylko przy „w żadnej rekrutacji”", () => {
    expect(recruitmentLocksStageFields(f({ recruitmentPresence: "never" }))).toBe(true);
    expect(recruitmentLocksStageFields(f({ recruitmentPresence: "ever" }))).toBe(false);
    expect(recruitmentLocksStageFields(f({ recruitmentPresence: "not_in_process" }))).toBe(false);
    expect(
      recruitmentLocksStageFields(f({ recruitmentIds: [7], recruitmentMatch: "not_assigned" })),
    ).toBe(false);
  });
});
