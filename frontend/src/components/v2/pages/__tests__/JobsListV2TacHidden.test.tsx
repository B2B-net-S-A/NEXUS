/**
 * Funkcja TAC wyłączona (decyzja 22.09.2026, lib/tac-ui.ts): lista nie pokazuje
 * plakietki ani szybkiego filtra „Brak opiekuna TAC", a stary link z
 * `?no_owner=1` nie zawęża listy ukrytym filtrem.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { JobsListV2 } from "@/components/v2/pages/JobsListV2";
import { useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";

const getMock = vi.fn();

const quickCountsMock = vi.fn();

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
  },
  jobsApi: {
    quickCounts: (...args: unknown[]) => quickCountsMock(...args),
  },
}));

const pushMock = vi.fn();
const searchParamsMock = vi.fn(() => new URLSearchParams());

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => searchParamsMock(),
}));

vi.mock("@/hooks/useCapability", () => ({
  useCapabilities: () => ({
    "job.create": false,
    "invite_link.create": false,
  }),
}));


vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showToast: vi.fn(),
    showSuccess: vi.fn(),
    showError: vi.fn(),
    showActionToast: vi.fn(),
  }),
}));

vi.mock("@/components/v2/modals/GenerateInviteLinkV2", () => ({
  GenerateInviteLinkV2: () => null,
}));

vi.mock("@/components/v2/filters/UserMultiSelect", () => ({
  UserMultiSelect: () => null,
}));

vi.mock("@/components/v2/filters/ClientMultiSelect", () => ({
  ClientMultiSelect: () => null,
}));

vi.mock("@/components/v2/filters/CompetenceCategoryMultiSelect", () => ({
  CompetenceCategoryMultiSelect: () => null,
}));

// Dok ma własny plik testów (`JobReadinessDock.test.tsx`) — tu tylko
// potwierdzamy, że dostaje `jobId`/`stageBreakdown` z listy (patrz test
// "przekazuje zaznaczoną rekrutację do doku" niżej).
vi.mock("@/components/v2/jobs/JobReadinessDock", () => ({
  JobReadinessDock: ({
    jobId,
    listNav,
  }: {
    jobId: number | null;
    // Prop dokłada `JobsListV2` (kontrakt `job-list-nav.ts`); dok kroku 01
    // dostaje go od tej fali programu. Atrapa czyta go, żeby test wiązał się
    // z tym, CO lista przekazuje, a nie z tym, co dok z tym robi.
    listNav?: { index: number; total: number };
  }) => (
    <div data-testid="mock-dock">
      dock:{String(jobId)}
      {listNav ? (
        <span data-testid="mock-nav">
          nav:{listNav.index}/{listNav.total}
        </span>
      ) : null}
    </div>
  ),
}));

// Domyślny zakres zależy od roli, a zapytanie czeka na hydratację store'u.
function signInAs(...roles: string[]) {
  useAuthStore.setState({
    user: { id: 7, name: "Test", email: "t@example.com", role: roles[0], roles } as never,
    hydrated: true,
  });
}

beforeEach(() => {
  signInAs("recruiter");
});

function jobRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 101,
    title: "Senior Java Developer",
    status: "published",
    headcount: 1,
    candidate_count: 0,
    tac_id: 7,
    recruitment_type: "body_leasing",
    ...overrides,
  };
}

function mockJobsResponse(items: ReturnType<typeof jobRow>[]) {
  getMock.mockResolvedValue({
    data: { items, total: items.length, page: 1, page_size: 20 },
  });
}

/** Liczniki „Szybkich" — GLOBALNE, z `GET /api/jobs/quick-counts`. */
function mockQuickCounts(overrides: Record<string, number> = {}) {
  quickCountsMock.mockResolvedValue({
    data: {
      all: 4241,
      mine: 12,
      open: 318,
      needs_sourcing: 41,
      active_in_search: 27,
      owner_missing: 63,
      deadline_7d: 9,
      ...overrides,
    },
  });
}

function renderJobs() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <JobsListV2 />
    </QueryClientProvider>,
  );
}

function jobsCalls() {
  return getMock.mock.calls.filter((call) => call[0] === "/api/jobs");
}

function latestParams(): Record<string, unknown> {
  const call = jobsCalls().at(-1);
  return (call?.[1] as { params?: Record<string, unknown> } | undefined)
    ?.params ?? {};
}


describe("JobsListV2 — funkcja TAC wyłączona", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    searchParamsMock.mockReturnValue(new URLSearchParams());
    useUiStore.setState({ jobsView: "list" });
  });

  it("nie pokazuje plakietki ani szybkiego filtra „Brak opiekuna TAC”", async () => {
    mockJobsResponse([jobRow({ id: 1, title: "Bez opiekuna", tac_id: null })]);
    renderJobs();
    expect(await screen.findByText("Bez opiekuna")).toBeInTheDocument();
    expect(screen.queryByText("Brak opiekuna TAC")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Brak opiekuna TAC/ })).not.toBeInTheDocument();
  });

  it("stary link z ?no_owner=1 nie wysyła owner_missing", async () => {
    searchParamsMock.mockReturnValue(new URLSearchParams("no_owner=1"));
    mockJobsResponse([jobRow({ id: 2, title: "Cokolwiek" })]);
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).not.toMatchObject({ owner_missing: true });
  });
});
