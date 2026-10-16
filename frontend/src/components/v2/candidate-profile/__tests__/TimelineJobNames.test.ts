/** Oś czasu nazywa rekrutację wpisu jak jej nagłówek (16.10.2026). */
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));

import { timelineItemLabel } from "@/components/v2/candidate-profile/Timeline";

const NAMES = {
  job_id: 7,
  job_title: "AI Engineer (ZOB-9001)",
  job_working_title: "Senior AI Engineer · Java, LLM",
  job_client_reference: "ZOB-9001",
};

describe("timelineItemLabel", () => {
  it("notatka i etap mówią numer u klienta i tytuł dla rekrutera", () => {
    expect(timelineItemLabel({ type: "stage_change", stage: "screening", ...NAMES })).toMatch(
      /^Etap: .+ \(ZOB-9001 Senior AI Engineer · Java, LLM\)$/,
    );
    expect(timelineItemLabel({ type: "note", note_type: null, ...NAMES })).toBe(
      "Notatka (ZOB-9001 Senior AI Engineer · Java, LLM)",
    );
  });

  it("wpis ze starszego serwera zostaje przy nazwie od klienta, wpis bez rekrutacji bez nawiasu", () => {
    expect(timelineItemLabel({ type: "note", note_type: null, job_id: 7, job_title: "Tester" })).toBe(
      "Notatka (Tester)",
    );
    expect(timelineItemLabel({ type: "note", note_type: null, job_id: null, job_title: null })).toBe("Notatka");
  });
});
