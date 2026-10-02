/**
 * Szeroka tabela rekrutacji (zgłoszenie 02.10.2026): na dużym monitorze lista
 * kończyła się na 1400 px. Klient, kategoria, data otwarcia i nazwiska
 * Rekruterów mają własne kolumny albo pełną postać od 1700 px szerokości
 * tabeli; poniżej zostają drobnym drukiem pod tytułem. jsdom nie liczy CSS,
 * więc test sprawdza treść komórek i klasy, które je przełączają — widoczność
 * mierzy przeglądarka.
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
        { id: 9, slug: "nowa_kategoria", name_pl: "Kategoria bez skrótu" },
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
const WIDE_FLEX = "@min-[1700px]:flex";

const person = (
  user_id: number,
  name: string,
  extra: Record<string, unknown> = {},
) => ({
  user_id,
  name,
  role: "recruiter",
  via: "owner",
  proposed: false,
  assigned_by_name: null,
  ...extra,
});

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
    // Kolumna osób nazywa się „Rekruter” w obu układach — bez „Prowadzi”
    // i „Zespół”, i bez osobnej kolumny Delivery Leada ani priorytetu.
    expect(headers.map((h) => h.textContent)).toContain("Rekruter");
    for (const old of ["Prowadzi", "Zespół", "ProwadziZespół", "Delivery Lead", "Priorytet"]) {
      expect(headers.map((h) => h.textContent)).not.toContain(old);
    }
  });

  it("klient, kategoria, data otwarcia i nazwiska Rekruterów mają własne komórki", async () => {
    mockJobsResponse([
      jobRow({
        client_name: "Bank Przykładowy",
        competence_category_id: 2,
        opened_at: "2026-09-30T08:00:00Z",
        created_at: "2026-05-05T10:00:00Z",
        recruiters: [
          person(3, "Anna Nowak"),
          person(4, "Jan Kowalski", { via: "collaborator" }),
          person(6, "Ewa Proponowana", { via: "assignment", proposed: true }),
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

    // Szeroka tabela: nazwiska wprost, propozycja automatu oznaczona.
    const names = screen.getByTestId("job-recruiter-names");
    expect(names).toHaveClass(WIDE_FLEX);
    expect(names).toHaveTextContent("Anna N., Jan K.");
    const proposal = names.querySelector('[data-proposed="true"]');
    expect(proposal).toHaveTextContent("Ewa P.");
    expect(proposal).toHaveTextContent("propozycja");
    // Wąska tabela: ta sama komórka ma zwartą postać — pierwsza osoba i „+1”.
    const compact = within(screen.getByTestId("job-recruiter-cell")).getByText("+1");
    expect(compact.closest(`[class*="${WIDE_HIDE}"]`)).not.toBeNull();
    expect(screen.getByTitle("Klient").closest("td")).not.toHaveClass(WIDE_CELL);
  });

  it("„Otwarta” czyta `opened_effective_at` z serwera, a bez niego — dotychczasowe pola", async () => {
    mockJobsResponse([
      jobRow({
        id: 1,
        title: "Z nowego backendu",
        opened_effective_at: "2026-10-01T07:00:00Z",
        opened_at: "2026-09-30T08:00:00Z",
        created_at: "2026-05-05T10:00:00Z",
      }),
      jobRow({ id: 2, title: "Ze starego backendu", opened_at: "2026-09-30T08:00:00Z" }),
    ]);
    renderJobs();
    await screen.findByText("Z nowego backendu");
    const cells = screen.getAllByTestId("job-opened-cell");
    expect(cells[0]).toHaveTextContent("1.10.2026");
    expect(cells[1]).toHaveTextContent("30.09.2026");
  });

  it("wąska tabela: krótka plakietka kategorii pod tytułem, pełna nazwa w podpowiedzi", async () => {
    mockJobsResponse([
      jobRow({ id: 1, title: "Z kategorią", competence_category_id: 2 }),
      jobRow({ id: 2, title: "Bez skrótu", competence_category_id: 9 }),
      jobRow({ id: 3, title: "Bez kategorii", competence_category_id: null }),
    ]);
    renderJobs();
    await screen.findByText("Z kategorią");

    const badges = await screen.findAllByTestId("job-category-short");
    expect(badges).toHaveLength(2);
    expect(badges[0]).toHaveTextContent("Dev");
    expect(badges[0]).toHaveAttribute("title", "Kategoria: Development");
    // Znika, gdy szeroka tabela ma kolumnę „Kategoria”.
    expect(badges[0]).toHaveClass(WIDE_HIDE);
    // Stoi w komórce tytułu, nie w osobnej kolumnie.
    expect(badges[0].closest("td")).toBe(screen.getByText("Z kategorią").closest("td"));
    // Kategoria spoza czterech znanych: pełna nazwa z katalogu, nigdy surowy klucz.
    expect(badges[1]).toHaveTextContent("Kategoria bez skrótu");
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
    // Bez Rekrutera nie ma ani nazwisk, ani zwartej postaci — jest „Bez rekrutera”.
    expect(screen.queryByTestId("job-recruiter-names")).not.toBeInTheDocument();
    expect(screen.getByTestId("job-no-recruiter")).toBeInTheDocument();
  });
});
