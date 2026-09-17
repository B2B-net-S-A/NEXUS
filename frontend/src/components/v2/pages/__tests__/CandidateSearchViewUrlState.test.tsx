import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EXPERIENCE_RANGE_REVERSED_MSG } from "@/lib/candidate-search-request";

const search = vi.fn();
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
    diagnostics: vi.fn(() => Promise.resolve(null)),
    matchScores: vi.fn(),
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
  CandidateCompareModal: () => null,
}));

import { CandidateSearchView } from "@/components/v2/pages/CandidateSearchView";

const EMPTY = {
  total: 0,
  page: 1,
  page_size: 50,
  items: [],
  facets: { competence_categories: [] },
  meta: { ai_status: "ok", took_ms: 1 },
};

function renderView(props: { syncUrl?: boolean } = {}) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <CandidateSearchView backHref="/candidates" {...props} />
    </QueryClientProvider>,
  );
}

describe("CandidateSearchView — stan wyszukiwania w URL (UAT B29)", () => {
  beforeEach(() => {
    // Od vitest 4 `vi.spyOn` na już podsłuchiwanej metodzie zwraca TEN SAM
    // szpieg — bez przywrócenia oryginału reset adresu poniżej liczyłby się
    // jako wywołanie `replaceState` w kolejnym teście.
    vi.restoreAllMocks();
    vi.clearAllMocks();
    search.mockResolvedValue(EMPTY);
    window.history.replaceState(null, "", "/candidates/search");
    urlParams = new URLSearchParams();
  });

  it("montuje się z filtrów i strony zapisanych w ?s= (Wstecz z profilu)", async () => {
    urlParams = new URLSearchParams({
      s: JSON.stringify({
        q_none: ["Selenium"],
        experience_years_min: 2,
        experience_years_max: 6,
        page: 2,
      }),
    });
    renderView({ syncUrl: true });
    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(search).toHaveBeenLastCalledWith(
      expect.objectContaining({
        q_none: ["Selenium"],
        experience_years_min: 2,
        experience_years_max: 6,
        page: 2,
      }),
    );
  });

  it("zapisuje bieżący request do URL-a bez nowego wpisu w historii", async () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    urlParams = new URLSearchParams({ s: JSON.stringify({ q: "tester", page: 3 }) });
    renderView({ syncUrl: true });
    await waitFor(() => expect(replaceState).toHaveBeenCalled());
    const written = new URLSearchParams(window.location.search);
    expect(JSON.parse(written.get("s") ?? "{}")).toEqual({ q: "tester", page: 3 });
    expect(window.location.pathname).toBe("/candidates/search");
  });

  it("bez syncUrl (zakładka rekrutacji) URL jest ignorowany i nie jest pisany", async () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    urlParams = new URLSearchParams({ s: JSON.stringify({ page: 2 }) });
    renderView();
    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(search).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1 }));
    expect(replaceState).not.toHaveBeenCalled();
  });
});

describe("CandidateSearchView — odwrócony przedział lat (UAT B28)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    search.mockResolvedValue(EMPTY);
    window.history.replaceState(null, "", "/candidates/search");
  });

  it("min > max: pokazuje błąd i NIE wysyła zapytania", async () => {
    urlParams = new URLSearchParams({
      s: JSON.stringify({ experience_years_min: 10, experience_years_max: 2 }),
    });
    renderView({ syncUrl: true });
    expect(await screen.findByText(EXPERIENCE_RANGE_REVERSED_MSG)).toBeTruthy();
    // Debounce wyszukiwania to 300 ms — dajemy mu czas, żeby udowodnić brak wywołania.
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(search).not.toHaveBeenCalled();
  });
});
