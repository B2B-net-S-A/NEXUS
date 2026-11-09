import { describe, expect, it } from "vitest";

import { factsSummary, factsSummaryText } from "@/lib/conversation-facts";
import type { ConversationFact } from "@/lib/api";

const fact = (status: ConversationFact["status"]): ConversationFact => ({
  id: 1,
  kind: "skill",
  value: "PL/SQL",
  status,
  source: "sheet",
  noted_at: "2026-11-03T10:00:00Z",
  job_id: null,
  job_title: null,
  author_name: null,
  evidence: null,
  job_only: false,
});

describe("plakietka faktów z rozmów", () => {
  it("nie ma plakietki bez faktów", () => {
    expect(factsSummary([])).toBeNull();
  });

  it("liczy potwierdzone i braki z odmianą", () => {
    const summary = factsSummary([fact("confirmed"), fact("confirmed"), fact("absent")]);
    expect(summary).toEqual({ confirmed: 2, absent: 1 });
    expect(factsSummaryText(summary!)).toBe("2 potwierdzone · 1 nie ma");
    expect(factsSummaryText({ confirmed: 5, absent: 0 })).toBe("5 potwierdzonych");
    expect(factsSummaryText({ confirmed: 12, absent: 0 })).toBe("12 potwierdzonych");
    expect(factsSummaryText({ confirmed: 22, absent: 0 })).toBe("22 potwierdzone");
  });
});
