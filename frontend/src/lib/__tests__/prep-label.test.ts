import { describe, expect, it } from "vitest";

import { prepStatusLine, type Prep } from "@/lib/api/prepMeetings";

import {
  PREP_NOS,
  prepAgree,
  prepGenitive,
  prepLocative,
  prepName,
  prepNameInSentence,
  prepNoOfStep,
  prepStepKey,
  prepWith,
} from "@/lib/prep-label";

describe("prep-label — trzy prepy (F3, 24.11.2026)", () => {
  it("Przygotowanie jest pierwsze i ma numer 0", () => {
    expect(PREP_NOS).toEqual([0, 1, 2]);
    expect(PREP_NOS.map(prepName)).toEqual(["Przygotowanie", "Prep 1", "Prep 2"]);
    expect(PREP_NOS.map(prepStepKey)).toEqual(["prep0", "prep", "prep2"]);
    expect(["prep0", "prep", "prep2", "interview"].map(prepNoOfStep)).toEqual([0, 1, 2, null]);
  });

  it("odmienia Przygotowanie w rodzaju nijakim, a Prep w męskim", () => {
    expect(prepWith(0, "zaplanowany")).toBe("Przygotowanie zaplanowane");
    expect(prepWith(2, "zaplanowany")).toBe("Prep 2 zaplanowany");
    expect(prepAgree(0, "słaby")).toBe("słabe");
    expect(prepAgree(0, "długi")).toBe("długie");
    expect(`Zaplanuj ${prepNameInSentence(0)}`).toBe("Zaplanuj przygotowanie");
    expect(`brak ${prepGenitive(0)}`).toBe("brak przygotowania");
    expect(`po ${prepLocative(1)}`).toBe("po Prepie 1");
  });
});

describe("prepStatusLine — Przygotowanie bez oceny (F3)", () => {
  const base = { event_id: 1, candidate_id: 1, job_id: 1, start: "2031-06-10T08:00:00Z", transcription_setup: "enabled" };
  it("nagrane przygotowanie nie udaje, że ocena się liczy", () => {
    const line = prepStatusLine({ ...base, prep_no: 0, transcript_status: "fetched", review: null } as unknown as Prep);
    expect(line).toBe("NEXUS jeszcze nie ocenia przygotowania. Przeczytaj transkrypt.");
    expect(prepStatusLine({ ...base, prep_no: 1, transcript_status: "fetched", review: null } as unknown as Prep)).toBe(
      "Transkrypt jest, ocena jeszcze się liczy.",
    );
  });

  it("odwołanie i brak nagrania w rodzaju nijakim", () => {
    expect(prepStatusLine({ ...base, prep_no: 0, transcript_status: "cancelled" } as unknown as Prep)).toBe(
      "Przygotowanie zostało odwołane.",
    );
    expect(prepStatusLine({ ...base, prep_no: 0, transcript_status: "missing" } as unknown as Prep)).toMatch(
      /^Z tego przygotowania nie ma transkryptu/,
    );
  });
});
