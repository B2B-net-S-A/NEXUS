import { describe, expect, it } from "vitest";

import type { HistoricalCandidate, ProposalCandidateItem } from "@/lib/api";
import type { CandidateSearchRow } from "@/lib/full-candidate-search-api";
import type { ProposalInboxItem } from "@/lib/job-proposals-api";
import {
  DEFAULT_PROPOSAL_FILTERS,
  countBySource,
  filterProposals,
  mergeProposals,
  normalizeFitScore,
  traineeHandoverReason,
} from "@/lib/proposals-merge";
import { PROPOSAL_SOURCE_LABEL } from "@/components/v2/recruitment/types";

function inboxItem(id: number, over: Partial<ProposalInboxItem> = {}, name = "Anna"): ProposalInboxItem {
  return {
    candidate: {
      id, name, lastname: `Nowak${id}`, title: "Java Developer", city: "Warszawa",
      availability_status: "actively_looking", availability_date: null,
      expected_rate_hourly: 150, expected_rate_redacted: false,
    },
    sources: ["new_cv"], score: 70, evidence: null,
    first_seen_at: "2026-09-20T10:00:00Z", last_seen_at: null,
    is_new: false, status: "proposed", eligibility: null,
    ...over,
  };
}

function runRow(id: number, fit: number | null, over: Partial<CandidateSearchRow> = {}): CandidateSearchRow {
  return {
    candidate: { id, name: "Anna", lastname: `Nowak${id}`, location: "Kraków", competence_category: null, years_it_experience: 5, availability_status: null, champion: false, avatar_url: null },
    match: null, fit_score: fit, measurement: fit === null ? "unavailable" : "measured",
    requirements: [
      { any_of: ["Java"], level: "must", status: "met", matched: ["Java"], candidate_updated_at: "" },
      { any_of: ["AWS"], level: "must", status: "unknown", matched: [], candidate_updated_at: "" },
    ],
    eligibility: null,
    ...over,
  };
}

function similar(id: number): HistoricalCandidate {
  return {
    candidate_id: id, name: "Anna", lastname: `Nowak${id}`, avatar_url: null, competence_category: null,
    historical_score: 9.5, tier: "A", negative_signal: false, recommended_count: 1,
    sources: [{ job_id: 7, job_title: "Java dla Banku Alfa", stage: "interview", similarity: 0.9, months_ago: 3, moved_at: "", stage_weight: 1, contribution: 1, client_id: 1 }],
    current_availability: "available", current_status: null, same_client: true, rejected_by_same_client: false,
  };
}

function recommendation(id: number, total: number | null): ProposalCandidateItem {
  return {
    candidate: { id, name: "Anna", lastname: `Nowak${id}`, email: null, location: "Gdańsk", avatar_url: null, competence_category: null, years_it_experience: null, status: null, champion: null },
    total_score: total,
    breakdown: {} as ProposalCandidateItem["breakdown"],
  };
}

describe("normalizeFitScore", () => {
  it("nigdy nie zmyśla wyniku: puste, nieliczbowe i spoza skali → null", () => {
    expect(normalizeFitScore(null)).toBeNull();
    expect(normalizeFitScore("")).toBeNull();
    expect(normalizeFitScore("abc")).toBeNull();
    expect(normalizeFitScore(140)).toBeNull();
    expect(normalizeFitScore("81.26")).toBe(81.3);
    expect(normalizeFitScore(0)).toBe(0);
  });
});

describe("mergeProposals", () => {
  it("skleja źródła po kandydacie: suma źródeł, najlepszy wynik, runId z żywego przeglądu", () => {
    const [entry, ...rest] = mergeProposals({
      inbox: [inboxItem(1, { is_new: true, evidence: { previously_dismissed: true } })],
      run: { runId: "run-1", rows: [runRow(1, 91)] },
      similar: [similar(1)],
      recommendations: { items: [recommendation(1, 60)], degraded: false },
    });
    expect(rest).toHaveLength(0);
    expect(entry.row.sources).toEqual(["full_base", "new_cv", "similar_projects", "recommendation"]);
    expect(entry.row.fitScore).toBe(91);
    expect(entry.row.runId).toBe("run-1");
    expect(entry.row.isNew).toBe(true);
    expect(entry.row.previouslyDismissed).toBe(true);
    // Najbogatsze źródło powodu = przegląd (spełnione wymagania).
    expect(entry.row.reason).toBe("Spełnia: Java");
    expect(entry.detail.origins.sort()).toEqual(["inbox", "recommendation", "run", "similar"]);
    expect(entry.detail.rateHourly).toBe(150);
    expect(entry.row.rateLabel).toBe("150 zł/h");
  });

  it("punktacja z podobnych projektów NIE jest dopasowaniem; nieznany wynik zostaje null", () => {
    const [entry] = mergeProposals({ similar: [similar(2)] });
    expect(entry.row.fitScore).toBeNull();
    expect(entry.row.reason).toContain("Java dla Banku Alfa");
    expect(entry.detail.sameClient).toBe(true);
  });

  it("rekomendacje NIGDY nie wnoszą liczby do „Dop.” — to inna skala niż kanoniczne dopasowanie", () => {
    for (const degraded of [true, false]) {
      const [entry] = mergeProposals({ recommendations: { items: [recommendation(3, 88)], degraded } });
      expect(entry.row.fitScore).toBeNull();
      expect(entry.row.sources).toEqual(["recommendation"]);
    }
  });

  it("run_id ze skrzynki jedzie na wiersz; żywy przegląd go nadpisuje", () => {
    const [fromInbox] = mergeProposals({ inbox: [inboxItem(1, { run_id: "auto-3" })] });
    expect(fromInbox.row.runId).toBe("auto-3");
    const [both] = mergeProposals({ inbox: [inboxItem(1, { run_id: "auto-3" })], run: { runId: "run-9", rows: [runRow(1, 70)] } });
    expect(both.row.runId).toBe("run-9");
  });

  it("osoby już w pipeline'ie znikają niezależnie od źródła", () => {
    const entries = mergeProposals({
      inbox: [inboxItem(1), inboxItem(2)],
      run: { runId: "r", rows: [runRow(1, 80), runRow(3, 75)] },
      pipelineCandidateIds: [1, 3],
    });
    expect(entries.map((e) => e.row.candidateId)).toEqual([2]);
  });

  it("sortuje stabilnie: wynik malejąco (null na końcu), potem nowe, potem nazwisko", () => {
    const entries = mergeProposals({
      inbox: [
        inboxItem(1, { score: null }, "Zofia"),
        inboxItem(2, { score: null, is_new: true }, "Zenon"),
        inboxItem(3, { score: 50 }),
        inboxItem(4, { score: 90 }),
        inboxItem(5, { score: null }, "Adam"),
      ],
    });
    expect(entries.map((e) => e.row.candidateId)).toEqual([4, 3, 2, 5, 1]);
  });

  it("weto HM i konflikt z klientem to różne kody ostrzeżeń; stawka ponad budżet też", () => {
    const veto = { reason_code: "rejected_by_hiring_manager", reason: "HM odrzucił", assignment_allowed: false, visibility: "warn" as const, severity: "hard", secondary: [] };
    const nda = { ...veto, reason_code: "client_nda", reason: "NDA", assignment_allowed: true, severity: "warning" };
    const entries = mergeProposals({
      inbox: [inboxItem(1, { eligibility: veto }), inboxItem(2, { eligibility: nda })],
      budgetHourly: 120,
    });
    const byId = new Map(entries.map((e) => [e.row.candidateId, e.row.warnings]));
    expect(byId.get(1)).toEqual(["hm_veto", "over_budget"]);
    expect(byId.get(2)).toEqual(["client_nda", "over_budget"]);
  });

  it("podsumowanie AI i bramka must-have jadą WYŁĄCZNIE z wiersza żywego przeglądu (jak dawny dok dopasowania)", () => {
    const match = {
      candidate: { id: 1, name: "Anna", lastname: "Nowak1", ai_summary: "  Senior Java, 8 lat w bankowości.  " },
      match_score: 0.8, matching_skills: ["Java"], gaps: ["AWS"],
      missing_must: ["AWS", ""],
    } as unknown as CandidateSearchRow["match"];
    const entries = mergeProposals({
      // Starszy kształt dowodu skrzynki ma `missing_must`, ale to lista braków
      // wymagań, nie bramka dealbreakera — do linii „Bramka must-have" nie trafia.
      inbox: [inboxItem(2, { evidence: { missing_must: ["Kafka"] } })],
      run: { runId: "run-1", rows: [runRow(1, 80, { match })] },
    });
    const byId = new Map(entries.map((e) => [e.row.candidateId, e.detail]));
    expect(byId.get(1)?.aiSummary).toBe("Senior Java, 8 lat w bankowości.");
    expect(byId.get(1)?.missingMustGate).toEqual(["AWS"]);
    expect(byId.get(2)?.aiSummary).toBeNull();
    expect(byId.get(2)?.missingMustGate).toEqual([]);
  });

  it("przekazanie od praktykanta (0372): źródło, powód z datą, notatka, zaraz za przepięciem", () => {
    const entries = mergeProposals({
      inbox: [
        inboxItem(1, { score: 95 }),
        inboxItem(2, {
          score: 40,
          sources: ["trainee"],
          trainee_handover: {
            by_name: "Ola Kamińska",
            note: "Minimum 145 zł/h netto B2B, maks. 2 dni w biurze.",
            at: "2026-09-24T10:12:00Z",
          },
        }),
        inboxItem(3, {
          sources: ["reassign"],
          reassign_from: {
            job_id: 7, title: "Java", reference_number: null, client_name: "PKO BP",
            stage: "cv_sent", sent_at: "2026-09-01",
          },
        }),
      ],
    });
    expect(entries.map((e) => e.row.candidateId)).toEqual([3, 2, 1]);
    const trainee = entries[1];
    expect(trainee.row.sources).toEqual(["trainee"]);
    expect(PROPOSAL_SOURCE_LABEL.trainee).toBe("Od praktykanta");
    expect(trainee.row.reason).toBe("Od praktykanta: Ola Kamińska · 24.09");
    expect(trainee.row.handoverNote).toBe("Minimum 145 zł/h netto B2B, maks. 2 dni w biurze.");
    expect(trainee.detail.traineeHandover?.by_name).toBe("Ola Kamińska");
    // Bez przekazania wiersz nie niesie notatki.
    expect(entries[2].row.handoverNote).toBeUndefined();
  });

  it("przekazanie bez nazwiska i daty nie zmyśla danych", () => {
    expect(traineeHandoverReason({ by_name: null, note: null, at: null })).toBe(
      "Od praktykanta: praktykant",
    );
  });

  it("nieznane źródło z backendu nie wywraca scalenia", () => {
    const [entry] = mergeProposals({ inbox: [inboxItem(1, { sources: ["jarvis_pick"] })] });
    expect(entry.row.sources).toEqual(["full_base"]);
  });
});

describe("filterProposals / countBySource", () => {
  const entries = mergeProposals({
    inbox: [
      inboxItem(1, { score: 90, is_new: true }),
      inboxItem(2, { score: 40, sources: ["marketplace"] }),
      inboxItem(3, { score: null, candidate: { ...inboxItem(3).candidate, expected_rate_hourly: null, city: "Łódź", availability_status: "not_looking" } }),
    ],
  });
  const ctx = { budgetHourly: 160 };

  it("próg dopasowania nie usuwa ocen niepełnych", () => {
    const ids = filterProposals(entries, { ...DEFAULT_PROPOSAL_FILTERS, minScore: 60 }, ctx).map((e) => e.row.candidateId);
    expect(ids).toEqual([1, 3]);
  });

  it("źródło, nowe, budżet, dostępność i lokalizacja bez polskich znaków", () => {
    expect(filterProposals(entries, { ...DEFAULT_PROPOSAL_FILTERS, source: "marketplace" }, ctx).map((e) => e.row.candidateId)).toEqual([2]);
    expect(filterProposals(entries, { ...DEFAULT_PROPOSAL_FILTERS, onlyNew: true }, ctx).map((e) => e.row.candidateId)).toEqual([1]);
    // „W budżecie" przepuszcza stawkę NIEZNANĄ (3) — odsiewa tylko „ponad budżet".
    expect(filterProposals(entries, { ...DEFAULT_PROPOSAL_FILTERS, inBudget: true }, ctx).map((e) => e.row.candidateId)).toEqual([1, 2, 3]);
    expect(filterProposals(entries, { ...DEFAULT_PROPOSAL_FILTERS, inBudget: true }, { budgetHourly: 100 }).map((e) => e.row.candidateId)).toEqual([3]);
    expect(filterProposals(entries, { ...DEFAULT_PROPOSAL_FILTERS, rate: "unknown" }, ctx).map((e) => e.row.candidateId)).toEqual([3]);
    expect(filterProposals(entries, { ...DEFAULT_PROPOSAL_FILTERS, availableNow: true }, ctx).map((e) => e.row.candidateId)).toEqual([1, 2]);
    expect(filterProposals(entries, { ...DEFAULT_PROPOSAL_FILTERS, location: "lodz" }, ctx).map((e) => e.row.candidateId)).toEqual([3]);
  });

  it("liczy osoby per źródło", () => {
    expect(countBySource(entries)).toMatchObject({ all: 3, new_cv: 2, marketplace: 1, full_base: 0 });
  });
});
