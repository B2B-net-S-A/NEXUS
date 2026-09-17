import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const search = vi.fn();
const diagnostics = vi.fn();
const compareProps = vi.fn();
let urlParams = new URLSearchParams();

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => urlParams,
}));

vi.mock("@/lib/candidate-search-api", () => ({
  candidateSearchApi: {
    search: (...args: unknown[]) => search(...args),
    diagnostics: (...args: unknown[]) => diagnostics(...args),
    matchScores: vi.fn(() => Promise.resolve({ scores: {}, breakdowns: {} })),
  },
  proposalsBulkApi: { assignableStages: () => Promise.resolve([]) },
  shortlistApi: {},
  savedSearchesApi: { list: () => Promise.resolve([]) },
}));

vi.mock("@/components/v2/filters/FiltersPanel", () => ({
  FiltersPanel: () => null,
}));
vi.mock("@/components/v2/pages/JobShortlistPanel", () => ({
  JobShortlistPanel: () => null,
}));
vi.mock("@/components/v2/pages/CandidateCompareModal", () => ({
  CandidateCompareModal: (props: unknown) => {
    compareProps(props);
    return <div data-testid="compare-modal" />;
  },
}));

import {
  CandidateSearchView,
  availabilityLabel,
  clampedSearchPage,
} from "@/components/v2/pages/CandidateSearchView";

function item(id: number, extra: Record<string, unknown> = {}) {
  return {
    id,
    name: "Kandydat",
    lastname: `Nr${id}`,
    email: null,
    phone: null,
    location: null,
    status: "active",
    availability_status: null,
    source: null,
    competence_category: null,
    competence_category_id: null,
    availability_date: null,
    years_it_experience: null,
    tags: null,
    skills: null,
    languages: null,
    ai_summary: null,
    avatar_url: null,
    relevance_score: 0,
    has_cv: true,
    has_linkedin: false,
    is_champion: false,
    created_at: null,
    updated_at: null,
    ...extra,
  };
}

function page(items: ReturnType<typeof item>[], total: number, pageNo = 1, pageSize = 50) {
  return {
    total,
    page: pageNo,
    page_size: pageSize,
    items,
    facets: { competence_categories: [] },
    meta: { ai_status: "ok", took_ms: 1 },
  };
}

function renderView(props: Parameters<typeof CandidateSearchView>[0] = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CandidateSearchView {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  search.mockReset();
  diagnostics.mockReset().mockResolvedValue({
    base_count: 10,
    stages: [],
    total: 0,
    first_zeroing_stage: null,
  });
  urlParams = new URLSearchParams();
  window.history.replaceState(null, "", "/candidates/search");
});

describe("CandidateSearchView — błąd wyszukiwania", () => {
  it("czyści stare wyniki, pokazuje komunikat z API i ponawia na „Ponów”", async () => {
    search
      .mockResolvedValueOnce(page([item(1)], 1))
      .mockRejectedValueOnce(
        Object.assign(new Error("Request failed with status code 422"), {
          isAxiosError: true,
          response: {
            status: 422,
            data: { detail: [{ loc: ["body", "q"], msg: "String should have at most 500 characters" }] },
          },
        }),
      )
      .mockResolvedValueOnce(page([item(2)], 1));

    renderView();
    expect(await screen.findByText("Kandydat Nr1")).toBeInTheDocument();

    // Wymuszamy drugie zapytanie tym samym przyciskiem sortowania co użytkownik.
    fireEvent.click(screen.getByRole("button", { name: "Najnowsi" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toMatch(/Request failed with status code/);
    expect(screen.queryByText("Kandydat Nr1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(await screen.findByText("Kandydat Nr2")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("przekazuje sygnał przerwania do zapytania", async () => {
    search.mockResolvedValue(page([], 0));
    renderView();
    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(search.mock.calls[0][1]).toBeInstanceOf(AbortSignal);
  });
});

describe("CandidateSearchView — strona poza zakresem", () => {
  it("clampedSearchPage wskazuje ostatnią istniejącą stronę", () => {
    expect(clampedSearchPage({ items: [], total: 60, page_size: 50 }, 3)).toBe(2);
    expect(clampedSearchPage({ items: [], total: 0, page_size: 50 }, 3)).toBeNull();
    expect(clampedSearchPage({ items: [], total: 60, page_size: 50 }, 1)).toBeNull();
  });

  it("?s= ze starą stroną przechodzi na ostatnią zamiast „Brak wyników”", async () => {
    urlParams = new URLSearchParams({ s: JSON.stringify({ page: 3 }) });
    search.mockImplementation((req: { page: number }) =>
      Promise.resolve(
        req.page === 3 ? page([], 60, 3) : page([item(51)], 60, 2),
      ),
    );
    renderView({ syncUrl: true });
    expect(await screen.findByText("Kandydat Nr51")).toBeInTheDocument();
    expect(search).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 2 }),
      expect.any(AbortSignal),
    );
  });
});

describe("CandidateSearchView — porównanie ze wszystkich stron", () => {
  it("porównuje zaznaczonych z różnych stron; powyżej 5 blokuje z podpisem", async () => {
    search.mockImplementation((req: { page: number }) =>
      Promise.resolve(
        req.page === 1
          ? page([item(1), item(2), item(3)], 60, 1)
          : page([item(4), item(5), item(6), item(7)], 60, 2),
      ),
    );
    renderView({ addToJob: { id: 9, title: "Java" }, readOnly: true });
    fireEvent.click(await screen.findByLabelText("Zaznacz Kandydat Nr1"));
    fireEvent.click(screen.getByLabelText("Zaznacz Kandydat Nr2"));

    fireEvent.click(screen.getByRole("button", { name: "Następna" }));
    fireEvent.click(await screen.findByLabelText("Zaznacz Kandydat Nr4"));

    fireEvent.click(screen.getByRole("button", { name: /Porównaj/ }));
    expect(await screen.findByTestId("compare-modal")).toBeInTheDocument();
    const { candidates } = compareProps.mock.calls.at(-1)?.[0] as {
      candidates: { id: number; name: string }[];
    };
    expect(candidates.map((c) => c.id)).toEqual([1, 2, 4]);
    expect(candidates[2].name).toBe("Kandydat Nr4");

    for (const id of [5, 6, 7]) {
      fireEvent.click(screen.getByLabelText(`Zaznacz Kandydat Nr${id}`));
    }
    const compare = screen.getByRole("button", { name: /Porównaj \(maks\. 5\)/ });
    expect(compare).toBeDisabled();
    expect(compare.getAttribute("title")).toBe("Porównanie obsługuje do 5 osób");
  });
});

describe("CandidateSearchView — wiersz wyniku", () => {
  it("link do profilu niesie powrót do rekrutacji, a dostępność ma etykietę", async () => {
    search.mockResolvedValue(
      page([item(1, { availability_status: "open_to_offers" })], 1),
    );
    renderView({ addToJob: { id: 9, title: "Java" }, readOnly: true });
    const link = await screen.findByRole("link", { name: "Kandydat Nr1" });
    expect(link.getAttribute("href")).toBe("/candidates/1?from=job&jobId=9");
    expect(screen.getByText(availabilityLabel("open_to_offers"))).toBeInTheDocument();
    expect(screen.queryByText("open to offers")).not.toBeInTheDocument();
  });

  it("poza rekrutacją link prowadzi do samego profilu", async () => {
    search.mockResolvedValue(page([item(1)], 1));
    renderView();
    const link = await screen.findByRole("link", { name: "Kandydat Nr1" });
    expect(link.getAttribute("href")).toBe("/candidates/1");
  });
});

describe("CandidateSearchView — diagnostyka pustego wyniku", () => {
  it("wodospad rusza dopiero po zwłoce, nie od razu po pustym wyniku", async () => {
    search.mockResolvedValue(page([], 0));
    renderView();
    await waitFor(() => expect(search).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(diagnostics).not.toHaveBeenCalled();
    await waitFor(() => expect(diagnostics).toHaveBeenCalledTimes(1), {
      timeout: 2000,
    });
  });
});
