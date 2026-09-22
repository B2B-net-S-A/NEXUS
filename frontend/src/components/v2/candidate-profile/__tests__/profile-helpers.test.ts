import { describe, expect, it } from "vitest";

import {
  candidateHeadline,
  isRecruitmentEnded,
  pickHeaderWarning,
  screeningConfirmedSkills,
  splitRecruitments,
  yearsLabel,
} from "../profile-helpers";

describe("candidateHeadline", () => {
  it("składa stanowisko i lata doświadczenia — bez lokalizacji i dostępności", () => {
    expect(
      candidateHeadline({
        position: "Senior Java Developer",
        years_it_experience: 8,
        // Pola, które NIE mogą trafić do nagłówka (mają pasek faktów):
        ...({ city: "Warszawa", availability_status: "actively_looking" } as object),
      }),
    ).toBe("Senior Java Developer · 8 lat doświadczenia");
  });

  it("pomija brakujące części", () => {
    expect(candidateHeadline({ years_it_experience: 3 })).toBe("3 lata doświadczenia");
    expect(candidateHeadline({ position: "Tester" })).toBe("Tester");
    expect(candidateHeadline({ years_it_experience: 0 })).toBeNull();
  });

  it("odmienia lata po polsku", () => {
    expect(yearsLabel(1)).toBe("1 rok");
    expect(yearsLabel(2)).toBe("2 lata");
    expect(yearsLabel(5)).toBe("5 lat");
    expect(yearsLabel(12)).toBe("12 lat");
    expect(yearsLabel(22)).toBe("22 lata");
  });
});

describe("pickHeaderWarning — najwyżej jedno ostrzeżenie", () => {
  it("czarna lista wygrywa ze wszystkim", () => {
    expect(
      pickHeaderWarning({
        status: "blacklisted",
        employmentState: "employed_at_client",
        riskLevel: "high",
      }),
    ).toEqual({ kind: "blacklist" });
  });

  it("zatrudnienie u klienta ma własny baner — bez odznaki i bez ryzyka", () => {
    expect(
      pickHeaderWarning({ employmentState: "employed_at_client", riskLevel: "high" }),
    ).toBeNull();
  });

  it("ryzyko tylko średnie i wysokie", () => {
    expect(pickHeaderWarning({ riskLevel: "medium" })).toEqual({ kind: "risk" });
    expect(pickHeaderWarning({ riskLevel: "low" })).toBeNull();
    expect(pickHeaderWarning({})).toBeNull();
  });
});

describe("splitRecruitments", () => {
  it("odrzucenie, wycofanie i zamknięta rekrutacja są zakończone", () => {
    const history = [
      { job_id: 1, latest_stage: "cv_sent", job_status: "published" },
      { job_id: 2, latest_stage: "rejected", job_status: "published" },
      { job_id: 3, latest_stage: "verified", job_status: "closed" },
      { job_id: 4, latest_stage: "withdrawn" },
      { job_id: 5, latest_stage: "hired", job_status: "published" },
    ];
    const { active, ended } = splitRecruitments(history);
    expect(active.map((j) => j.job_id)).toEqual([1, 5]);
    expect(ended.map((j) => j.job_id)).toEqual([2, 3, 4]);
    expect(isRecruitmentEnded({ latest_stage: "screening" })).toBe(false);
  });
});

describe("screeningConfirmedSkills", () => {
  it("łączy verified_tech i potwierdzone umiejętności ze screeningów bez duplikatów", () => {
    expect(
      screeningConfirmedSkills(
        ["Java", { name: "Kafka" }, "  "],
        [
          { skill: "java", level: "confirmed" },
          { skill: "Spring", level: "confirmed" },
          { skill: "AWS", level: "declared" },
        ],
      ),
    ).toEqual(["Java", "Kafka", "Spring"]);
    expect(screeningConfirmedSkills(null, undefined)).toEqual([]);
  });
});
