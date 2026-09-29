import { describe, expect, it } from "vitest";

import {
  changedFormKeys,
  duplicateMatchesFromConflict,
  extraFieldsForCv,
  cvKnownFields,
  fillEmptyFromCv,
  fromCvOverrides,
  type CandidateCvPreview,
} from "@/lib/add-candidate-cv";

const preview: CandidateCvPreview = {
  cv_sha256: "a".repeat(64),
  name: "Anna",
  lastname: "Nowak",
  email: "anna@firma.pl",
  phone: " +48 500 600 700 ",
  city: null,
  linkedin: "https://linkedin.com/in/anna",
  current_position: "Tester",
  confidence: {},
  source: "claude",
};

const emptyForm = { name: "", lastname: "", email: "", phone: "", city: "", linkedin: "", tags: "" };

describe("add-candidate-cv", () => {
  it("wypełnia tylko puste pola i mówi które", () => {
    const { form, filled } = fillEmptyFromCv({ ...emptyForm, name: "Ania" }, preview);
    expect(form.name).toBe("Ania");
    expect(form.lastname).toBe("Nowak");
    expect(form.phone).toBe("+48 500 600 700");
    expect(form.city).toBe("");
    expect(filled).toEqual(["lastname", "email", "phone", "linkedin"]);
  });

  it("pola dla /from-cv: niepuste bez spacji na brzegach", () => {
    expect(fromCvOverrides({ ...emptyForm, name: " Anna ", email: "a@b.pl" })).toEqual({
      name: "Anna",
      email: "a@b.pl",
    });
  });

  it("pole wyczyszczone po odczycie CV idzie jako jawne \"\" — wartość z CV nie wraca", () => {
    const known = cvKnownFields(preview);
    expect(known).toEqual(["name", "lastname", "email", "phone", "linkedin"]);
    expect(
      fromCvOverrides({ ...emptyForm, name: "Anna", lastname: "Nowak" }, known),
    ).toEqual({ name: "Anna", lastname: "Nowak", email: "", phone: "", linkedin: "" });
    // Bez odczytu (albo pole, którego CV nie miało) — puste pole nic nie znaczy.
    expect(fromCvOverrides({ ...emptyForm, name: "Anna" }, [])).toEqual({ name: "Anna" });
  });

  it("reszta formularza w tym samym żądaniu: tylko ustawione pola, bez pustych preferencji", () => {
    const empty = { name: "", tags: "", notice_period: "", pref_remote_modes: [] as string[], status: "active" };
    const form = { name: "Anna", tags: "java", notice_period: "30", pref_remote_modes: ["remote"], status: "active" };
    const changed = changedFormKeys(form, empty, new Set(["name"]));
    expect(changed).toEqual(["tags", "notice_period", "pref_remote_modes"]);
    const payload = {
      name: "Anna",
      tags: ["java"],
      notice_period: 30,
      notice_period_unit: "days",
      status: "active",
      preferences: { remote_modes: ["remote"], industries: null },
    };
    expect(extraFieldsForCv(payload, changed)).toEqual({
      tags: ["java"],
      notice_period: 30,
      notice_period_unit: "days",
      preferences: { remote_modes: ["remote"] },
    });
    expect(extraFieldsForCv(payload, [])).toEqual({});
  });

  it("czyta trafienia z 409 i ignoruje inne błędy", () => {
    const match = {
      candidate_id: 5,
      name: "Anna",
      lastname: "Nowak",
      email: null,
      match_score: 0.9,
      match_reasons: ["email"],
    };
    const error = {
      response: {
        status: 409,
        data: {
          detail: {
            detail: "duplikat",
            existing_candidate_id: 5,
            matches: [match, { name: "bez id" }],
          },
        },
      },
    };
    expect(duplicateMatchesFromConflict(error)).toEqual([match]);
    expect(duplicateMatchesFromConflict({ response: { status: 422, data: {} } })).toBeNull();
    expect(duplicateMatchesFromConflict(new Error("x"))).toBeNull();
  });
});
