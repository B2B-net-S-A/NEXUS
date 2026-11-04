import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const facts = vi.fn();
const matchScores = vi.fn();
const apiGet = vi.fn();

vi.mock("@/lib/job-proposals-api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/job-proposals-api")>();
  return {
    ...actual,
    jobProposalsApi: { ...actual.jobProposalsApi, facts: (...a: unknown[]) => facts(...a) },
  };
});
vi.mock("@/lib/candidate-search-api", async (importActual) => {
  const actual = await importActual<typeof import("@/lib/candidate-search-api")>();
  return {
    ...actual,
    candidateSearchApi: {
      ...actual.candidateSearchApi,
      matchScores: (...a: unknown[]) => matchScores(...a),
    },
  };
});
vi.mock("@/lib/api", () => {
  const api = { get: (...a: unknown[]) => apiGet(...a) };
  return { default: api, api };
});
vi.mock("@/components/v2/candidates/CandidateCvCell", () => ({
  useCandidateCvPreview: () => ({ open: vi.fn(), loading: false, modal: null }),
}));

import { PersonPreview } from "@/components/v2/recruitment/PersonPreview";

function renderPreview(props: Partial<React.ComponentProps<typeof PersonPreview>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PersonPreview
        jobId={5}
        candidateId={10}
        name="Ewa Przykładowa"
        position={{ index: 0, total: 1 }}
        onPrev={vi.fn()}
        onNext={vi.fn()}
        onClose={vi.fn()}
        canOpenProfile
        selection={{ checked: false, disabled: false, onToggle: vi.fn(), label: "Dodaj tę osobę do „Nowych”" }}
        {...props}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  facts.mockResolvedValue({ job_id: 5, items: [] });
  apiGet.mockResolvedValue({ data: { recent_notes: [] } });
  matchScores.mockResolvedValue({
    scores: { "10": 70 },
    breakdowns: {
      "10": {
        total: 70,
        measurement: "measured",
        matching_must: ["Java"],
        gap_must: ["Minimum 5 lat w bankowości"],
      },
    },
    non_technology_must: ["Minimum 5 lat w bankowości"],
  });
});

describe("PersonPreview — „Zapytaj w rozmowie” (wariant A, 13.10.2026)", () => {
  it("pokazuje listę do rozmowy pod dopasowaniem; zdanie z must-have nie jest „nie znaleziono”", async () => {
    renderPreview({
      talkChecks: [
        { label: "bankowość", kind: "domains" },
        { label: "angielski B2", kind: "language" },
        { label: "Minimum 5 lat w bankowości", kind: "must" },
      ],
    });
    const must = await screen.findByRole("list", { name: "Wymagania must-have" });
    expect(within(must).getByText("Java")).toBeInTheDocument();
    expect(within(must).queryByText(/nie znaleziono/)).toBeNull();
    const talk = screen.getByRole("list", { name: "Zapytaj w rozmowie" });
    expect(within(talk).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "bankowość",
      "Język: angielski B2",
      "Minimum 5 lat w bankowości",
    ]);
  });

  it("bez listy do rozmowy nie ma pustego nagłówka", async () => {
    renderPreview();
    await screen.findByRole("list", { name: "Wymagania must-have" });
    expect(screen.queryByText("Zapytaj w rozmowie")).toBeNull();
  });
});
