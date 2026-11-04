/**
 * „Po ludzku” — reguła samoodświeżania wyjaśnienia rekrutacji.
 * Otwarta rekrutacja z nieaktualnym wyjaśnieniem odświeża się sama; zamknięta
 * i „podgląd jako” nie (generacja kosztuje, a w podglądzie nie wolno pisać).
 */
import { describe, expect, it } from "vitest";

import {
  briefHasContent,
  normalizePlainBrief,
  plainBriefQueryKey,
  RESEARCH_POLL_LIMIT,
  RESEARCH_POLL_MS,
  researchPollInterval,
  plainTermsQueryKey,
  shouldAutoRefresh,
} from "@/lib/api/plainKnowledge";

const base = { status: "ready" as const, stale: false, is_open: true, can_refresh: true };

describe("shouldAutoRefresh", () => {
  it("aktualne wyjaśnienie — bez odświeżania", () => {
    expect(shouldAutoRefresh(base)).toBe(false);
  });

  it("nieaktualne albo jeszcze nieprzygotowane w otwartej rekrutacji — odświeża", () => {
    expect(shouldAutoRefresh({ ...base, stale: true })).toBe(true);
    expect(shouldAutoRefresh({ ...base, status: "none" })).toBe(true);
    expect(shouldAutoRefresh({ ...base, status: "failed", stale: true })).toBe(true);
  });

  it("nieudana generacja bez zmiany profilu nie kręci się w pętli", () => {
    expect(shouldAutoRefresh({ ...base, status: "failed" })).toBe(false);
  });

  it("zamknięta rekrutacja i brak prawa odświeżania — nigdy", () => {
    expect(shouldAutoRefresh({ ...base, stale: true, is_open: false })).toBe(false);
    expect(shouldAutoRefresh({ ...base, status: "none", can_refresh: false })).toBe(false);
    expect(shouldAutoRefresh(undefined)).toBe(false);
  });
});

describe("klucze zapytań", () => {
  it("są stabilne (harness zasiewa je tymi samymi funkcjami)", () => {
    expect(plainBriefQueryKey(4812)).toEqual(["plain-brief", 4812]);
    expect(plainTermsQueryKey({ scope: "outside", q: "kaf" })).toEqual([
      "plain-terms",
      "list",
      "outside",
      "kaf",
    ]);
  });
});

describe("normalizePlainBrief", () => {
  it("odrzuca odpowiedź spoza kontraktu zamiast wywracać dok", () => {
    expect(normalizePlainBrief(undefined)).toBeNull();
    expect(normalizePlainBrief({ stages: [] })).toBeNull();
  });

  it("uzupełnia brakujące listy pustymi tablicami", () => {
    const brief = normalizePlainBrief({ job_id: 1, status: "none", stale: true });
    expect(brief?.candidate_qa).toEqual([]);
    expect(brief?.glossary).toEqual([]);
    expect(briefHasContent(brief)).toBe(false);
  });
});

describe("researchPollInterval", () => {
  const brief = (status: string) =>
    normalizePlainBrief({
      job_id: 1,
      status: "ready",
      glossary: [{ term_key: "kafka", display_name: "Kafka", status }],
    });

  it("dociąga widok, dopóki hasło jest w researchu", () => {
    expect(researchPollInterval(brief("researching"), 0)).toBe(RESEARCH_POLL_MS);
    expect(researchPollInterval(brief("ready"), 0)).toBe(false);
    expect(researchPollInterval(brief("missing"), 0)).toBe(false);
  });

  it("przestaje po limicie, żeby hasło, które utknęło, nie odpytywało bez końca", () => {
    expect(researchPollInterval(brief("researching"), RESEARCH_POLL_LIMIT)).toBe(false);
  });
});
