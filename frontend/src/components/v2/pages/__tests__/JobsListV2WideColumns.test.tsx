/**
 * Szeroka tabela rekrutacji (zgłoszenie 02.10.2026): na dużym monitorze lista
 * kończyła się na 1400 px. Klient, kategoria, data otwarcia i nazwiska zespołu
 * mają własne kolumny, widoczne od 1700 px szerokości tabeli; poniżej zostają
 * drobnym drukiem pod tytułem. jsdom nie liczy CSS, więc test sprawdza treść
 * komórek i klasy, które je przełączają — widoczność mierzy przeglądarka.
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
  competenceCategoriesApi: {
    list: () =>
      Promise.resolve([
        { id: 2, slug: "software_development", name_pl: "Development" },
      ]),
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



const WIDE_CELL = "@min-[1700px]:table-cell";
const WIDE_HIDE = "@min-[1700px]:hidden";

describe("JobsListV2 — kolumny szerokiej tabeli", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    searchParamsMock.mockReturnValue(new URLSearchParams());
    useUiStore.setState({ jobsView: "list" });
  });

  it("strona bez limitu szerokości, cztery kolumny tylko w szerokiej tabeli", async () => {
    mockJobsResponse([jobRow({ client_name: "Bank Przykładowy" })]);
    renderJobs();
    await screen.findByText("Senior Java Developer");

    // Jak pulpit: żadnego `max-w-*` ani wyśrodkowania na stronie listy.
    expect(screen.getByTestId("jobs-list-page").className).not.toMatch(/max-w-|mx-auto/);
    const headers = screen.getAllByRole("columnheader");
    expect(
      headers
        .filter((h) => h.className.includes(WIDE_CELL))
        .map((h) => h.textContent),
    ).toEqual(["Klient", "Kategoria", "Otwarta"]);
    // „Prowadzi” w wąskiej tabeli, „Zespół” w szerokiej — ten sam nagłówek.
    const owner = headers.find((h) => h.textContent === "ProwadziZespół");
    expect(owner).toBeDefined();
    expect(within(owner as HTMLElement).getByText("Prowadzi")).toHaveClass(WIDE_HIDE);
  });

  it("klient, kategoria, data otwarcia i nazwiska zespołu mają własne komórki", async () => {
    mockJobsResponse([
      jobRow({
        client_name: "Bank Przykładowy",
        competence_category_id: 2,
        opened_at: "2026-09-30T08:00:00Z",
        created_at: "2026-05-05T10:00:00Z",
        primary_owner: { id: 3, name: "Anna Nowak", email: "a@x.pl", role: "recruiter" },
        collaborators: [
          { id: 4, name: "Jan Kowalski", source: "manual" },
          { id: 5, name: "Cała kategoria", source: "auto_cc" },
        ],
      }),
    ]);
    renderJobs();
    await screen.findByText("Senior Java Developer");

    const clientCell = screen.getByTestId("job-client-cell");
    expect(clientCell).toHaveClass(WIDE_CELL);
    expect(clientCell).toHaveTextContent("Bank Przykładowy");
    // Ten sam klient pod tytułem znika, gdy ma własną kolumnę.
    expect(screen.getByTitle("Klient")).toHaveClass(WIDE_HIDE);

    expect(await screen.findByText("Development")).toBeInTheDocument();
    expect(screen.getByTestId("job-category-cell")).toHaveTextContent("Development");
    expect(screen.getByTestId("job-opened-cell")).toHaveTextContent("30.09.2026");

    expect(screen.getByTestId("job-team-names")).toHaveTextContent("Jan K.");
    expect(screen.getByTitle("Klient").closest("td")).not.toHaveClass(WIDE_CELL);
  });

  it("bez kategorii i bez daty otwarcia: kreska i data dodania", async () => {
    mockJobsResponse([
      jobRow({ competence_category_id: null, created_at: "2026-05-05T10:00:00Z" }),
    ]);
    renderJobs();
    await screen.findByText("Senior Java Developer");

    expect(screen.getByTestId("job-category-cell")).toHaveTextContent("—");
    expect(screen.getByTestId("job-client-cell")).toHaveTextContent("—");
    expect(screen.getByTestId("job-opened-cell")).toHaveTextContent("5.05.2026");
    expect(screen.queryByTestId("job-team-names")).not.toBeInTheDocument();
  });
});
