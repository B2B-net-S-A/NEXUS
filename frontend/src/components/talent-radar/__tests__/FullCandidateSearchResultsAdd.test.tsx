import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CandidateSearchPage } from "@/lib/full-candidate-search-api";

const dialogProps = vi.hoisted(() => ({ last: null as null | Record<string, unknown> }));

vi.mock("@/components/v2/recruitment/AddToRecruitmentDialog", () => ({
  AddToRecruitmentDialog: (props: Record<string, unknown>) => {
    dialogProps.last = props;
    return <div role="dialog">Okno dodawania</div>;
  },
}));

import { FullCandidateSearchResults } from "@/components/talent-radar/FullCandidateSearchResults";

const data: CandidateSearchPage = {
  run_id: "run-7", state: "complete", versions: {},
  counts: { population: 10, pending: 0, failed: 0, evaluated: 10, eligible: 1, excluded: 9, needs_verification: 0 },
  total_after_threshold: 1, next_offset: null, ranking_complete: true,
  results: [{ candidate: { id: 4, name: "Anna", lastname: "Testowa", location: null, competence_category: null, years_it_experience: null, availability_status: null, champion: false, avatar_url: null },
    fit_score: 72, measurement: "measured", match: null, eligibility: null, requirements: [] }],
};

function renderResults(addToRecruitment?: React.ComponentProps<typeof FullCandidateSearchResults>["addToRecruitment"]) {
  render(<FullCandidateSearchResults data={data} error={null} loading={false} fetching={false} offset={0} onPage={vi.fn()} onRetry={vi.fn()} canOpenProfile addToRecruitment={addToRecruitment} />);
}

describe("FullCandidateSearchResults — „Dodaj do rekrutacji” (B3)", () => {
  beforeEach(() => { dialogProps.last = null; });

  it("bez uprawnienia nie ma przycisku", () => {
    renderResults();
    expect(screen.getByRole("link", { name: "Otwórz profil" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj do rekrutacji" })).not.toBeInTheDocument();
  });

  it("otwiera okno dla tej osoby ze źródłem talent_radar i przeglądem", () => {
    const onAdded = vi.fn();
    renderResults({ source: "talent_radar", onAdded });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do rekrutacji" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(dialogProps.last).toMatchObject({ candidateIds: [4], source: "talent_radar", runId: "run-7", onAdded, subject: "Wybierz rekrutację dla: Anna Testowa." });
  });
});
