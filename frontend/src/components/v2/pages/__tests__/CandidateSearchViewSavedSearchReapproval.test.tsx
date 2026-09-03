import type { ComponentProps } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const search = vi.fn(
  (..._args: unknown[]) => new Promise<never>(() => undefined),
);
const diagnostics = vi.fn();
const list = vi.fn();
const update = vi.fn();
const remove = vi.fn();

vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: {
    search: (...args: unknown[]) => search(...args),
    diagnostics: (...args: unknown[]) => diagnostics(...args),
  },
  proposalsBulkApi: {},
  shortlistApi: {},
  savedSearchesApi: {
    list: (...args: unknown[]) => list(...args),
    update: (...args: unknown[]) => update(...args),
    remove: (...args: unknown[]) => remove(...args),
  },
}));

vi.mock("@/components/v2/filters/FiltersPanel", () => ({
  FiltersPanel: ({
    value,
  }: {
    value: { q?: string | null };
  }) => <div data-testid="active-query">{value.q ?? "brak"}</div>,
}));

vi.mock("@/components/v2/pages/JobShortlistPanel", () => ({
  JobShortlistPanel: ({
    jobId,
    readOnly,
  }: {
    jobId: number;
    readOnly?: boolean;
  }) => (
    <div
      data-testid="job-shortlist"
      data-job-id={jobId}
      data-read-only={String(Boolean(readOnly))}
    />
  ),
}));

vi.mock("@/components/v2/pages/CandidateCompareModal", () => ({
  CandidateCompareModal: () => null,
}));

import { CandidateSearchView } from "@/components/v2/pages/CandidateSearchView";

const savedSearch = {
  id: 71,
  user_id: 9,
  name: "Backend po migracji",
  entity: "candidates",
  filters: { q: "python", search_mode: "boolean" },
  shared: false,
  description: null,
  pinned_to_job_id: null,
  requires_reapproval: true,
  created_at: "2026-07-29T10:00:00Z",
  updated_at: "2026-07-30T10:00:00Z",
};

function renderView(
  props: ComponentProps<typeof CandidateSearchView> = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CandidateSearchView {...props} />
    </QueryClientProvider>,
  );
}

describe("CandidateSearchView saved-search reapproval", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    list.mockResolvedValue([savedSearch]);
  });

  it("does not apply a migrated search until a separate explicit approval", async () => {
    update.mockResolvedValue({
      ...savedSearch,
      requires_reapproval: false,
    });
    renderView();

    fireEvent.click(
      await screen.findByRole("button", { name: savedSearch.name }),
    );

    expect(screen.getByTestId("active-query")).toHaveTextContent("brak");
    expect(update).not.toHaveBeenCalled();
    expect(
      screen.getByText(/Nie zastosujemy pozostałych filtrów/i),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Zatwierdź i zastosuj" }),
    );

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(savedSearch.id, {
        confirm_reapproval: true,
      }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("active-query")).toHaveTextContent("python"),
    );
    expect(
      screen.queryByRole("button", { name: "Zatwierdź i zastosuj" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the search unapplied when the user cancels reapproval", async () => {
    renderView();

    fireEvent.click(
      await screen.findByRole("button", { name: savedSearch.name }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Anuluj" }));

    expect(screen.getByTestId("active-query")).toHaveTextContent("brak");
    expect(update).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "Zatwierdź i zastosuj" }),
    ).not.toBeInTheDocument();
  });

  it("fails closed when the backend does not clear requires_reapproval", async () => {
    update.mockResolvedValue(savedSearch);
    renderView();

    fireEvent.click(
      await screen.findByRole("button", { name: savedSearch.name }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Zatwierdź i zastosuj" }),
    );

    expect(
      await screen.findByText(
        "Backend nie potwierdził ponownej akceptacji zapisu.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("active-query")).toHaveTextContent("brak");
    expect(
      screen.getByRole("button", { name: "Zatwierdź i zastosuj" }),
    ).toBeInTheDocument();
  });

  it("zachowuje job-scoped odczyt w read-only bez mutacji zapisanych wyszukiwań", async () => {
    list.mockResolvedValue([
      {
        ...savedSearch,
        requires_reapproval: false,
        pinned_to_job_id: 7,
      },
    ]);

    renderView({
      addToJob: { id: 7, title: "Backend Developer" },
      readOnly: true,
    });

    const shortlist = await screen.findByTestId("job-shortlist");
    expect(shortlist).toHaveAttribute("data-job-id", "7");
    expect(shortlist).toHaveAttribute("data-read-only", "true");
    await waitFor(() =>
      expect(list).toHaveBeenCalledWith({
        entity: "candidates",
        pinned_to_job_id: 7,
        only_mine: undefined,
      }),
    );
    expect(
      screen.queryByRole("button", { name: /Zapisz wyszukiwanie/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Zapisz to wyszukiwanie/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: `Usuń ${savedSearch.name}` }),
    ).not.toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
    expect(remove).not.toHaveBeenCalled();
  });
});
