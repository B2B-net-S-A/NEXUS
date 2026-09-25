import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const bulkAdd = vi.fn();
const scoreArgs = vi.fn();
const onRowVisible = vi.fn();
let urlParams = new URLSearchParams();
let listItems: Array<Record<string, unknown> & { id: number }> = [];
let listTotal = 0;
let listExtra: Record<string, unknown> = {};

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
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => urlParams,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  const get = vi.fn((url: string) => {
    if (url === "/api/candidates") {
      return Promise.resolve({
        data: {
          items: listItems,
          total: listTotal,
          page: 1,
          page_size: 50,
          ...listExtra,
        },
      });
    }
    return Promise.resolve({ data: [] });
  });
  return {
    ...original,
    default: { get, post: vi.fn(), put: vi.fn() },
    competenceCategoriesApi: {
      list: vi.fn(() => Promise.resolve([])),
    },
  };
});

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError, showToast: vi.fn() }),
}));
vi.mock("@/lib/candidate-search-api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/candidate-search-api")>();
  return { ...original, proposalsBulkApi: { add: (...a: unknown[]) => bulkAdd(...a) } };
});
vi.mock("@/hooks/useVisibleMatchScores", () => ({
  useVisibleMatchScores: (jobId: number | null, items: unknown) => {
    scoreArgs(jobId, items);
    return {
      scores: { "1": 82 },
      breakdowns: {},
      failures: {},
      onRowVisible: onRowVisible,
      retry: vi.fn(),
    };
  },
}));
vi.mock("@/hooks/useCandidateContactFeature", () => ({
  useCandidateContactFeature: () => ({ enabled: false }),
}));
vi.mock("@/components/AppShell", () => ({ AddCandidateModal: () => null }));
vi.mock("@/components/v2/modals/ImportCandidatesV2", () => ({
  ImportCandidatesV2: () => null,
}));
vi.mock("@/components/v2/modals/AddCandidateFromCVModal", () => ({
  AddCandidateFromCVModal: () => null,
}));
vi.mock("@/components/v2/modals/QuickAssignV2", () => ({ QuickAssignV2: () => null }));
vi.mock("@/components/v2/modals/GenerateInviteLinkV2", () => ({
  GenerateInviteLinkV2: () => null,
}));
vi.mock("@/components/v2/pages/CandidateQuickView", () => ({
  CandidateQuickView: () => null,
}));
vi.mock("@/components/v2/filters/PinnedCandidatesBar", () => ({
  PinnedCandidatesBar: () => null,
}));
vi.mock("@/components/v2/filters/SavedSearchesMenu", () => ({
  SavedSearchesMenu: () => null,
}));
vi.mock("@/components/v2/filters/CompetenceCategoryMultiSelect", () => ({
  CompetenceCategoryMultiSelect: () => null,
}));
// jsdom nie ma wymiarów — wirtualizacja renderuje wszystkie wiersze strony.
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 64,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ index, start: index * 64, size: 64 })),
    measure: () => undefined,
  }),
}));
vi.mock("@/components/v2/candidates/RequestSearchDialog", () => ({
  RequestSearchDialog: ({
    open,
    initialText,
    onSubmit,
  }: {
    open: boolean;
    initialText?: string;
    onSubmit: (r: unknown) => void;
  }) =>
    open ? (
      <div role="dialog" aria-label="Szukaj z requestu">
        <span data-testid="request-initial-text">{initialText}</span>
        <button type="button" onClick={() => onSubmit({ source: "text", text: "x" })}>
          Dalej
        </button>
      </div>
    ) : null,
}));
vi.mock("@/components/v2/recruitment/AddToRecruitmentDialog", () => ({
  addToRecruitmentSummary: () => "Dodano 4 osoby.",
  AddToRecruitmentDialog: ({
    open,
    candidateIds,
    source,
    onAdded,
  }: {
    open: boolean;
    candidateIds: number[];
    source: string;
    onAdded?: (result: unknown) => void;
  }) =>
    open ? (
      <div role="dialog" aria-label="Dodaj do rekrutacji">
        <span>
          {source}:{candidateIds.join(",")}
        </span>
        <button type="button" onClick={() => onAdded?.({})}>
          Potwierdź dodanie
        </button>
      </div>
    ) : null,
}));

import { useUiStore } from "@/store/ui";
import { CandidatesListV2 } from "@/components/v2/pages/CandidatesListV2";
import { DEFAULT_FILTERS } from "@/lib/url-filters";

const onAdded = vi.fn();

function renderEmbedded() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CandidatesListV2
        embed={{
          jobId: 7,
          jobTitle: "Analityk Systemowy",
          initialFilters: {
            ...DEFAULT_FILTERS,
            q: "Analityk Systemowy",
            textMode: "semantic",
            status: ["active", "passive"],
          },
          onAdded,
        }}
      />
    </QueryClientProvider>,
  );
}

async function listParams(): Promise<Record<string, unknown>> {
  const api = (await import("@/lib/api")).default as unknown as {
    get: ReturnType<typeof vi.fn>;
  };
  const calls = api.get.mock.calls.filter(
    (call) =>
      call[0] === "/api/candidates" &&
      (call[1] as { params: { page_size?: number } }).params.page_size !== 1,
  );
  return (calls.at(-1)?.[1] as { params: Record<string, unknown> }).params;
}

beforeEach(() => {
  vi.clearAllMocks();
  cleanup();
  // Adres strony rekrutacji — lista w oknie nie może go czytać.
  urlParams = new URLSearchParams("q=inny-tekst&page=4&tab=people");
  listItems = [
    { id: 1, name: "Ewa", lastname: "Marczak", status: "active" },
    { id: 2, name: "Piotr", lastname: "Lis", status: "active" },
  ];
  listTotal = 2;
  listExtra = {};
  useUiStore.setState({ columnPreferences: {} });
});

afterEach(() => cleanup());

describe("CandidatesListV2 — „Szukaj ręcznie” z rekrutacji (embed)", () => {
  it("startuje z filtrów rekrutacji, nie z adresu, i ukrywa osoby z rekrutacji", async () => {
    renderEmbedded();
    await screen.findByText("Ewa Marczak");
    const params = await listParams();
    expect(params.q).toBe("Analityk Systemowy");
    expect(params.page).toBe(1);
    expect(params.recruitment_id).toEqual([7]);
    expect(params.recruitment_match).toBe("not_assigned");
    expect(params.status).toEqual(["active", "passive"]);
    // Ukrycie osób z rekrutacji nie jest chipem do zdjęcia.
    expect(screen.queryByText(/Rekrutacja: /)).not.toBeInTheDocument();
  });

  it("bez nagłówka strony Kandydatów, z dopasowaniem do rekrutacji", async () => {
    renderEmbedded();
    await screen.findByText("Ewa Marczak");
    expect(screen.queryByRole("heading", { name: "Kandydaci" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj kandydata/ })).not.toBeInTheDocument();
    expect(screen.getByText("Dop.")).toBeInTheDocument();
    expect(screen.getByTitle("Dopasowanie do tej rekrutacji")).toHaveTextContent("82");
    expect(scoreArgs).toHaveBeenCalledWith(7, expect.any(Array));
    expect(onRowVisible).toHaveBeenCalledWith(1);
  });

  it("„Dodaj” wpisuje osobę do Nowych tej rekrutacji", async () => {
    bulkAdd.mockResolvedValue({
      added: [1],
      skipped: [],
      warnings: [],
      total_added: 1,
      total_skipped: 0,
    });
    renderEmbedded();
    fireEvent.click(await screen.findByRole("button", { name: "Dodaj Ewa Marczak do Nowych" }));
    await waitFor(() =>
      expect(bulkAdd).toHaveBeenCalledWith(7, {
        candidate_ids: [1],
        initial_stage_legacy: "new",
        source: "manual_search",
      }),
    );
    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    expect(showSuccess).toHaveBeenCalledWith("Dodano do Nowych: 1.");
  });

  it("zbiorczo: „Dodaj N do Nowych” z zaznaczonych", async () => {
    bulkAdd.mockResolvedValue({
      added: [1],
      skipped: [{ candidate_id: 2, reason: "already_in_job" }],
      warnings: [],
      total_added: 1,
      total_skipped: 1,
    });
    renderEmbedded();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Zaznacz Ewa Marczak" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz Piotr Lis" }));
    fireEvent.click(screen.getByRole("button", { name: /Dodaj 2 do Nowych/ }));
    await waitFor(() =>
      expect(bulkAdd).toHaveBeenCalledWith(7, expect.objectContaining({ candidate_ids: [1, 2] })),
    );
    await waitFor(() => expect(showSuccess).toHaveBeenCalled());
    expect(showSuccess.mock.calls[0][0]).toContain("Pominięto:");
  });
});
