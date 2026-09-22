import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Wyszukiwarka wysyła wspólną semantykę filtrów (v2, decyzja 21.09.2026):
 * `semantics_version: 2`, jawne kubełki umiejętności, „Otwarty na" jako lista.
 * Stare `?s=` i zapisy legacy (`skills_must` = ranking) otwierają się przez
 * adapter zapisów — „Mile widziane", nie „Musi mieć".
 */

const search = vi.fn();
const listSaved = vi.fn();
const createSaved = vi.fn();
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
  savedSearchesApi: {
    list: (...args: unknown[]) => listSaved(...args),
    create: (...args: unknown[]) => createSaved(...args),
  },
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

function renderView(
  props: Partial<React.ComponentProps<typeof CandidateSearchView>> = {},
) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <CandidateSearchView backHref="/candidates" {...props} />
    </QueryClientProvider>,
  );
}

const lastRequest = () => search.mock.calls.at(-1)?.[0] as Record<string, unknown>;

describe("CandidateSearchView — semantyka v2", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    search.mockResolvedValue(EMPTY);
    listSaved.mockResolvedValue([]);
    createSaved.mockResolvedValue({});
    window.history.replaceState(null, "", "/candidates/search");
    urlParams = new URLSearchParams();
  });

  it("każde wyszukiwanie niesie semantics_version 2 i puste kubełki", async () => {
    renderView();
    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(lastRequest()).toMatchObject({
      semantics_version: 2,
      skills_required: [],
      skills_preferred: [],
      skills_excluded: [],
      open_to: [],
      skills_must: [],
      skills_any: [],
      skills_none: [],
    });
  });

  it("stary ?s= (skills_must / skills_none / open_to_*) otwiera się w kubełkach", async () => {
    urlParams = new URLSearchParams({
      s: JSON.stringify({
        skills_must: ["Java"],
        skills_any: ["Spring"],
        skills_none: ["PHP"],
        open_to_side_projects: true,
        q: "backend",
      }),
    });
    renderView({ syncUrl: true });
    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(lastRequest()).toMatchObject({
      semantics_version: 2,
      q: "backend",
      // `skills_must`/`skills_any` były wyłącznie rankingiem — adapter zapisów
      // przekłada je na „Mile widziane", nie na twarde „Musi mieć".
      skills_preferred: ["Java", "Spring"],
      skills_required: [],
      skills_excluded: ["PHP"],
      open_to: ["side_projects"],
      skills_must: [],
      skills_none: [],
      open_to_side_projects: null,
    });
    // URL przepisany już w nowym kształcie.
    await waitFor(() => {
      const written = JSON.parse(
        new URLSearchParams(window.location.search).get("s") ?? "{}",
      );
      expect(written.skills_preferred).toEqual(["Java", "Spring"]);
      expect(written.skills_must).toBeUndefined();
    });
  });

  it("prefill rekrutacji (skills_must) trafia do „Mile widziane”", async () => {
    renderView({ initial: { skills_must: ["Python"] } });
    await waitFor(() => expect(search).toHaveBeenCalled());
    expect(lastRequest()).toMatchObject({
      skills_preferred: ["Python"],
      skills_required: [],
      skills_must: [],
    });
  });

  it("zapis legacy (surowe żądanie) otwiera się w kubełkach", async () => {
    listSaved.mockResolvedValue([
      {
        id: 7,
        name: "Stary zapis",
        filters: { skills_must: ["Go"], skills_none: ["Perl"], q: "go" },
        requires_reapproval: false,
        pinned_to_job_id: null,
      },
    ]);
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: "Stary zapis" }));
    await waitFor(() =>
      expect(lastRequest()).toMatchObject({
        semantics_version: 2,
        skills_preferred: ["Go"],
        skills_excluded: ["Perl"],
        skills_must: [],
      }),
    );
  });

  it("nowy zapis idzie w formacie v3", async () => {
    urlParams = new URLSearchParams({
      s: JSON.stringify({ skills_required: ["Java", "Spring|Quarkus"], q: "dev" }),
    });
    renderView({ syncUrl: true });
    fireEvent.click(
      await screen.findByRole("button", { name: /Zapisz to wyszukiwanie/ }),
    );
    fireEvent.change(screen.getByPlaceholderText("Nazwa…"), {
      target: { value: "Java senior" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(createSaved).toHaveBeenCalled());
    const body = createSaved.mock.calls[0][0] as {
      filters: Record<string, unknown>;
    };
    expect(body.filters).toMatchObject({
      version: 3,
      semantics_version: 2,
      origin: "search_request",
      request: {
        semantics_version: 2,
        q: "dev",
        skills_required: ["Java", "Spring|Quarkus"],
      },
    });
    expect(body.filters).not.toHaveProperty("legacy");
  });

  it("wiersz z unknown_fields dostaje plakietki „brak …”", async () => {
    search.mockResolvedValue({
      ...EMPTY,
      total: 1,
      items: [
        {
          id: 1,
          name: "Anna",
          lastname: "Nowak",
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
          unknown_fields: ["location", "experience"],
        },
      ],
    });
    renderView();
    expect(await screen.findByText("brak lokalizacji")).toBeInTheDocument();
    expect(screen.getByText("brak stażu")).toBeInTheDocument();
    expect(screen.queryByText("brak stawki")).toBeNull();
  });

  it("hideHeader chowa nagłówek, persistUrlParams zostaje w URL-u", async () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    urlParams = new URLSearchParams({ s: JSON.stringify({ q: "tester" }) });
    renderView({
      syncUrl: true,
      hideHeader: true,
      persistUrlParams: { mode: "search" },
    });
    await waitFor(() => expect(replaceState).toHaveBeenCalled());
    expect(screen.queryByText("Wyszukiwanie kandydatów")).toBeNull();
    expect(screen.queryByRole("link", { name: /Wstecz/ })).toBeNull();
    const written = new URLSearchParams(window.location.search);
    expect(written.get("mode")).toBe("search");
    expect(JSON.parse(written.get("s") ?? "{}")).toEqual({ q: "tester" });
  });
});
