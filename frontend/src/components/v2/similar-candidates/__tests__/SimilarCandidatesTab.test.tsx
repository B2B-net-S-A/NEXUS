import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const list = vi.fn();

vi.mock("@/lib/api/similarCandidates", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/similarCandidates")>(
    "@/lib/api/similarCandidates",
  );
  return {
    ...actual,
    similarCandidatesApi: { list: (...args: unknown[]) => list(...args), check: vi.fn() },
  };
});
vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: { matchScores: vi.fn() },
}));
vi.mock("@/lib/api", () => ({
  jobsApi: { list: vi.fn(() => Promise.resolve({ data: { items: [] } })) },
  skillsApi: { list: vi.fn(() => Promise.resolve({ data: { items: [] } })) },
}));

import { SimilarCandidatesTab } from "../SimilarCandidatesTab";
import type { SimilarCandidate, SimilarCandidatesResponse } from "@/lib/api/similarCandidates";

/**
 * „Możliwy duplikat · Scal…” i profil bez CV w zakładce „Podobni”
 * (pomiar na produkcji 22.10.2026, decyzja Artura).
 */

const person = (id: number, over: Partial<SimilarCandidate> = {}): SimilarCandidate => ({
  id,
  name: "Osoba",
  lastname: `Testowa ${id}`,
  title: "Java Developer",
  company: null,
  city: "Warszawa",
  location: null,
  years_it_experience: 5,
  competence_category: null,
  rate_hourly: null,
  rate_currency: null,
  availability_status: "actively_looking",
  availability_date: null,
  active_processes: 0,
  score: 0.8,
  level: "very",
  shared_skills: ["java"],
  only_source_skills: [],
  only_candidate_skills: [],
  duplicate_signals: [],
  ...over,
});

const response = (over: Partial<SimilarCandidatesResponse>): SimilarCandidatesResponse => ({
  candidate_id: 1,
  status: "ok",
  total: 2,
  source: person(1),
  items: [
    person(2, { score: 0.95, duplicate_signals: ["name", "phone"] }),
    person(3),
  ],
  ...over,
});

function renderTab(onMergeDuplicate?: (id: number) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(
    <SimilarCandidatesTab
      candidateId={1}
      candidateName="Osoba Testowa"
      recruitments={[]}
      canWrite={false}
      onMergeDuplicate={onMergeDuplicate}
    />,
    { wrapper },
  );
}

describe("SimilarCandidatesTab — duplikaty i profile bez CV", () => {
  beforeEach(() => list.mockReset());

  it("marks only the duplicate and opens merge with that person", async () => {
    list.mockResolvedValue(response({}));
    const onMerge = vi.fn();
    renderTab(onMerge);

    expect(await screen.findByText("Możliwy duplikat")).toBeInTheDocument();
    expect(screen.getAllByText("Możliwy duplikat")).toHaveLength(1);
    expect(screen.getByText("to samo imię i nazwisko · ten sam telefon")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Scal/ }));
    expect(onMerge).toHaveBeenCalledWith(2);
  });

  it("shows the badge without „Scal…” for someone who cannot merge", async () => {
    list.mockResolvedValue(response({}));
    renderTab(undefined);

    expect(await screen.findByText("Możliwy duplikat")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Scal/ })).toBeNull();
  });

  it("says there is nothing to compare for a profile without CV", async () => {
    list.mockResolvedValue(response({ status: "no_cv", total: 0, items: [] }));
    renderTab();

    expect(await screen.findByText(/nie ma w profilu CV ani umiejętności/)).toBeInTheDocument();
    expect(screen.queryByText(/Nikt nie pasuje do filtrów/)).toBeNull();
  });
});
