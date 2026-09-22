import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getReqs: vi.fn(), view: vi.fn() }));

vi.mock("@/lib/matching-requirements", () => ({
  matchingRequirementsApi: { get: (...a: unknown[]) => mocks.getReqs(...a) },
  // Uproszczone lustro: etykiety pozycji `must`.
  requirementLabels: (data: { must: string[] }) => data.must,
}));
vi.mock("@/lib/job-search-prefill", () => ({
  buildJobSearchPrefill: (job: { title: string }, must: string[] | null) => ({
    fromJob: job.title,
    must,
  }),
}));
vi.mock("@/components/v2/pages/CandidateSearchView", () => ({
  CandidateSearchView: (props: unknown) => {
    mocks.view(props);
    return <div data-testid="candidate-search-view" />;
  },
}));

import { ManualSearchPanel } from "@/components/v2/recruitment/ManualSearchPanel";

const JOB = { id: 7, title: "Java Developer", must_skills: ["Java"] };

function renderPanel(props: Partial<React.ComponentProps<typeof ManualSearchPanel>> = {}) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ManualSearchPanel jobId={7} job={JOB} {...props} />
    </QueryClientProvider>,
  );
}

describe("ManualSearchPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("montuje wyszukiwarkę dopiero PO odczycie wymagań i zasila ją rekrutacją", async () => {
    mocks.getReqs.mockResolvedValue({ must: ["Java 17", "Kafka"] });
    const onBulkAdded = vi.fn();
    renderPanel({ onBulkAdded, readOnly: true });
    expect(screen.getByText("Ładowanie…")).toBeInTheDocument();
    expect(screen.queryByTestId("candidate-search-view")).not.toBeInTheDocument();

    await screen.findByTestId("candidate-search-view");
    expect(mocks.getReqs).toHaveBeenCalledWith(7);
    expect(mocks.view).toHaveBeenLastCalledWith({
      initial: { fromJob: "Java Developer", must: ["Java 17", "Kafka"] },
      addToJob: { id: 7, title: "Java Developer" },
      hideHeader: true,
      onBulkAdded,
      readOnly: true,
    });
  });

  it("błąd odczytu wymagań nie blokuje wyszukiwania — prefill wraca do kolumn rekrutacji", async () => {
    mocks.getReqs.mockRejectedValue(new Error("boom"));
    renderPanel();
    await screen.findByTestId("candidate-search-view");
    expect(mocks.view).toHaveBeenLastCalledWith(
      expect.objectContaining({ initial: { fromJob: "Java Developer", must: null }, readOnly: false }),
    );
  });
});
