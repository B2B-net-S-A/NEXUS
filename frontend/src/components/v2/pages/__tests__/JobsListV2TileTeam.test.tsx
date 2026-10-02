/**
 * Ludzie na kafelku rekrutacji (zgłoszenie 30.09.2026): Delivery Lead, która
 * założyła rekrutację bez rekrutera, widziała samo „Nieprzypisany” i czytała to
 * jako „nie jestem przypisana”. Kafelek mówi, czego brakuje, i pokazuje DL.
 * Od 02.10.2026 te same nazwy co w tabeli: „Rekruter”, „Bez rekrutera”,
 * a osoby pochodzą z `recruiters[]` (zapas: prowadzący + ręczni współpracownicy).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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


describe("JobsListV2 — Rekruter i Delivery Lead na kafelku", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    searchParamsMock.mockReturnValue(new URLSearchParams());
    useUiStore.setState({ jobsView: "tiles" });
  });

  it("bez Rekrutera mówi „Bez rekrutera” i pokazuje Delivery Leada", async () => {
    mockJobsResponse([
      jobRow({
        id: 1,
        title: "Architekt Domenowy",
        recruiters: [],
        delivery_lead_user: { id: 9, name: "Martyna Witkowska" },
      }),
    ]);
    renderJobs();
    expect(await screen.findByText("Architekt Domenowy")).toBeInTheDocument();
    expect(screen.getByText("Rekruter:")).toBeInTheDocument();
    expect(screen.getByTestId("job-no-recruiter")).toHaveTextContent("Bez rekrutera");
    // Stare nazwy zniknęły.
    expect(screen.queryByText("Brak rekrutera")).not.toBeInTheDocument();
    expect(screen.queryByText("Nieprzypisany")).not.toBeInTheDocument();
    expect(screen.getByTitle("Delivery Lead: Martyna Witkowska")).toBeInTheDocument();
  });

  it("pokazuje pierwszą osobę i „+N” z listy `recruiters`; propozycja się nie liczy", async () => {
    mockJobsResponse([
      jobRow({
        id: 2,
        title: "Tester",
        recruiters: [
          { user_id: 3, name: "Anna Nowak", role: "recruiter", via: "owner", proposed: false, assigned_by_name: null },
          { user_id: 4, name: "Jan Kowalski", role: "sourcer", via: "collaborator", proposed: false, assigned_by_name: null },
          { user_id: 5, name: "Ewa Proponowana", role: "recruiter", via: "assignment", proposed: true, assigned_by_name: null },
        ],
      }),
    ]);
    renderJobs();
    expect(await screen.findByText("Tester")).toBeInTheDocument();
    const chips = screen.getByTitle(
      "Rekruterzy: Anna Nowak, Jan Kowalski · Propozycja automatu: Ewa Proponowana",
    );
    expect(within(chips).getByText("Anna N.")).toBeInTheDocument();
    expect(within(chips).getByText("+1")).toBeInTheDocument();
    expect(screen.queryByTestId("job-no-recruiter")).not.toBeInTheDocument();
  });

  it("starszy backend bez `recruiters`: prowadzący i ręczni współpracownicy (bez całej kategorii)", async () => {
    mockJobsResponse([
      jobRow({
        id: 3,
        title: "Analityk",
        primary_owner: { id: 3, name: "Anna Nowak", email: "a@x.pl", role: "recruiter" },
        collaborators: [
          { id: 4, name: "Jan Kowalski", source: "manual" },
          { id: 5, name: "Cała kategoria", source: "auto_cc" },
        ],
      }),
    ]);
    renderJobs();
    expect(await screen.findByText("Analityk")).toBeInTheDocument();
    expect(screen.getByTitle("Rekruterzy: Anna Nowak, Jan Kowalski")).toHaveTextContent("+1");
  });

  it("priorytet stoi przy statusie kafelka: P1 i „Przyjmujemy”, P2 bez plakietki", async () => {
    mockJobsResponse([
      jobRow({ id: 4, title: "Pilna", priority_level: "p1" }),
      jobRow({ id: 5, title: "Zwykła", priority_level: "p2" }),
      jobRow({ id: 6, title: "Otwarta na kandydatów", priority_level: "accepting" }),
    ]);
    renderJobs();
    expect(await screen.findByText("Pilna")).toBeInTheDocument();
    expect(screen.getByTitle("P1 Pilne")).toBeInTheDocument();
    expect(screen.getByTitle("Przyjmujemy kandydatów")).toBeInTheDocument();
    expect(screen.queryByTitle("P2 Standard")).not.toBeInTheDocument();
  });
});
