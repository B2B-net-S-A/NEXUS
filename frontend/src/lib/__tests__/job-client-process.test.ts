import { describe, expect, it } from "vitest";

import {
  PROCESS_PRESETS,
  candidateSentence,
  daysLabel,
  decisionSlowerThanDeclared,
  matchingPreset,
  parseWorkdays,
  processFactLabel,
  sameProcess,
  storedProcess,
  toInput,
  type ClientProcessInput,
  type MeasuredProcess,
} from "@/lib/job-client-process";

const TWO: ClientProcessInput = {
  steps: [
    { kind: "tech_interview", format: "remote", duration: "60 min" },
    { kind: "home_task", format: "remote", duration: "ok. 3 h" },
  ],
  decision_workdays: 10,
};

const MEASURED: MeasuredProcess = {
  cv_to_interview_days: 8,
  interview_to_decision_days: 14,
  cv_to_decision_days: 29,
  decisions: 180,
  months: 18,
};

describe("processFactLabel", () => {
  it("liczy etapy po polsku i tygodnie tylko z czasu zmierzonego", () => {
    expect(processFactLabel(TWO, MEASURED)).toBe("2 etapy · ~4 tyg.");
    expect(processFactLabel(TWO, null)).toBe("2 etapy");
    expect(processFactLabel({ ...TWO, steps: TWO.steps.slice(0, 1) }, null)).toBe("1 etap");
    const five = { ...TWO, steps: Array(5).fill(TWO.steps[0]) };
    expect(processFactLabel(five, null)).toBe("5 etapów");
  });

  it("bez etapów nie ma etykiety (nagłówek mówi „nie podano”)", () => {
    expect(processFactLabel(null, MEASURED)).toBeNull();
    expect(processFactLabel({ steps: [], decision_workdays: 5 }, MEASURED)).toBeNull();
  });

  it("krótki proces to co najmniej tydzień, nie „~0 tyg.”", () => {
    expect(processFactLabel(TWO, { ...MEASURED, cv_to_decision_days: 2 })).toBe("2 etapy · ~1 tyg.");
  });
});

describe("candidateSentence", () => {
  it("wymienia etapy po kolei i termin z historii", () => {
    expect(candidateSentence(TWO, MEASURED)).toBe(
      "Proces u klienta ma 2 etapy: rozmowa techniczna zdalnie (60 min), potem zadanie do wykonania zdalnie (ok. 3 h). Decyzji spodziewaj się po ok. 4 tygodniach od wysłania CV.",
    );
  });

  it("bez historii mówi o obietnicy klienta, bez czasu etapu pomija nawias", () => {
    const one: ClientProcessInput = {
      steps: [{ kind: "tech_interview", format: "onsite", duration: " " }],
      decision_workdays: 5,
    };
    expect(candidateSentence(one, null)).toBe(
      "Proces u klienta ma jeden etap: rozmowa techniczna na miejscu. Klient obiecuje decyzję w ciągu 5 dni roboczych od ostatniego etapu.",
    );
  });

  it("bez etapów nie ma zdania", () => {
    expect(candidateSentence(null, MEASURED)).toBeNull();
  });
});

describe("decisionSlowerThanDeclared", () => {
  it("ostrzega dopiero, gdy rzeczywistość przekracza obietnicę z zapasem", () => {
    // 10 dni roboczych ≈ 14 kalendarzowych, z zapasem 16,8
    expect(decisionSlowerThanDeclared(TWO, { ...MEASURED, interview_to_decision_days: 14 })).toBe(false);
    expect(decisionSlowerThanDeclared(TWO, { ...MEASURED, interview_to_decision_days: 27 })).toBe(true);
  });

  it("bez obietnicy albo bez pomiaru milczy", () => {
    expect(decisionSlowerThanDeclared({ ...TWO, decision_workdays: null }, MEASURED)).toBe(false);
    expect(decisionSlowerThanDeclared(TWO, { ...MEASURED, interview_to_decision_days: null })).toBe(false);
    expect(decisionSlowerThanDeclared(TWO, null)).toBe(false);
  });
});

describe("daysLabel", () => {
  it("zero to „< 1 dnia”, nie „0 dni”", () => {
    expect(daysLabel(0)).toBe("< 1 dnia");
    expect(daysLabel(1)).toBe("1 dzień");
    expect(daysLabel(12)).toBe("12 dni");
  });
});

describe("parseWorkdays i toInput", () => {
  it("przyjmuje puste albo 1–60, resztę odrzuca", () => {
    expect(parseWorkdays("")).toBeNull();
    expect(parseWorkdays(" 10 ")).toBe(10);
    expect(parseWorkdays("0")).toBe("invalid");
    expect(parseWorkdays("61")).toBe("invalid");
    expect(parseWorkdays("2 tyg")).toBe("invalid");
    expect(parseWorkdays("-3")).toBe("invalid");
  });

  it("przycina czasy, limit etapów i termin poza zakresem", () => {
    const many = { steps: Array(9).fill({ ...TWO.steps[0], duration: `  ${"x".repeat(100)} ` }), decision_workdays: 99 };
    const out = toInput(many);
    expect(out.steps).toHaveLength(6);
    expect(out.steps[0].duration).toHaveLength(80);
    expect(out.decision_workdays).toBeNull();
  });
});

describe("układy i porównania", () => {
  it("rozpoznaje układ po rodzaju i formie, nie po czasie", () => {
    expect(matchingPreset(TWO.steps)).toBe("interview_task");
    expect(matchingPreset([{ ...TWO.steps[0], format: "onsite" }])).toBeNull();
    expect(matchingPreset([])).toBeNull();
    for (const preset of PROCESS_PRESETS) expect(matchingPreset(preset.steps)).toBe(preset.key);
  });

  it("sameProcess porównuje etapy i termin", () => {
    expect(sameProcess(TWO, { ...TWO })).toBe(true);
    expect(sameProcess(TWO, { ...TWO, decision_workdays: 5 })).toBe(false);
    expect(sameProcess(null, { steps: [], decision_workdays: null })).toBe(true);
  });

  it("storedProcess: pusty albo zepsuty wpis to brak procesu", () => {
    expect(storedProcess(undefined)).toBeNull();
    expect(storedProcess({ steps: [] })).toBeNull();
    expect(storedProcess({ steps: "x" })).toBeNull();
    expect(storedProcess(TWO)).toEqual(TWO);
  });
});
