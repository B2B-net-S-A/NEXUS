import { describe, expect, it } from "vitest";

import { CV_FEEDBACK_REASONS, cvFeedbackReasonLabel, isRecruiterOnly } from "../cv-download-access";

describe("isRecruiterOnly", () => {
  it.each([
    [{ role: "recruiter", roles: ["recruiter"] }, true],
    [{ role: "recruiter", roles: [] }, true],
    [{ role: "delivery_lead", roles: ["delivery_lead", "recruiter"] }, false],
    [{ role: "recruiter", roles: ["recruiter", "delivery_lead"] }, false],
    [{ role: "talent_community_manager", roles: ["talent_community_manager", "recruiter"] }, false],
    [{ role: "admin", roles: ["admin", "head_of_recruitment", "recruiter"] }, false],
    [{ role: "finance", roles: ["finance"] }, false],
  ] as const)("%j → %s", (user, expected) => {
    expect(isRecruiterOnly(user as never)).toBe(expected);
  });

  it("brak użytkownika niczego nie ogranicza", () => {
    expect(isRecruiterOnly(null)).toBe(false);
  });
});

describe("powody", () => {
  it("mają kod zgodny z serwerem i czytelną etykietę", () => {
    expect(CV_FEEDBACK_REASONS.map((reason) => reason.code)).toEqual([
      "why_candidate",
      "requirements_in_roles",
      "lost_experience",
      "invented",
      "years",
      "tone",
      "skills",
      "layout",
      "client_asked",
      "other",
    ]);
    expect(cvFeedbackReasonLabel("layout")).toBe("Układ, format");
    expect(cvFeedbackReasonLabel("nieznany")).toBe("nieznany");
  });
});
