/**
 * Nazwa rekrutacji jako tekst — jak nagłówek rekrutacji (16.10.2026):
 * numer u klienta przed tytułem dla rekrutera; bez nich nazwa od klienta.
 */
import { describe, expect, it } from "vitest";

import { candidateJobNames, jobNameText } from "@/lib/job-name-text";

const ROW = {
  job_id: 7,
  job_title: "AI Engineer (ZOB-9001)",
  job_working_title: "Senior AI Engineer · Java, LLM · 5+ lat",
  job_client_reference: "ZOB-9001",
};

describe("candidateJobNames", () => {
  it("maps candidate response fields to the job naming fields", () => {
    expect(candidateJobNames(ROW)).toEqual({
      id: 7,
      title: "AI Engineer (ZOB-9001)",
      working_title: "Senior AI Engineer · Java, LLM · 5+ lat",
      client_reference: "ZOB-9001",
    });
  });

  it("treats a payload from an older backend as names-less", () => {
    expect(candidateJobNames({ job_id: 3, job_title: "Tester" })).toEqual({
      id: 3,
      title: "Tester",
      working_title: null,
      client_reference: null,
    });
  });
});

describe("jobNameText", () => {
  it("puts the client number before the recruiter title, like the job header", () => {
    expect(jobNameText(candidateJobNames(ROW))).toBe("ZOB-9001 Senior AI Engineer · Java, LLM · 5+ lat");
  });

  it("shows the first of several numbers and how many more", () => {
    expect(
      jobNameText({ title: "Analityk (42928)", working_title: "Analityk IT", client_reference: "42928, 42927" }),
    ).toBe("42928 +1 Analityk IT");
  });

  it("falls back to the client title without a recruiter title or number", () => {
    expect(jobNameText({ title: "Tester manualny" })).toBe("Tester manualny");
    expect(jobNameText({ title: "Tester manualny", client_reference: "  " })).toBe("Tester manualny");
  });

  it("names a recruitment without any title by its id", () => {
    expect(jobNameText({ id: 12, title: null })).toBe("Rekrutacja #12");
  });
});
