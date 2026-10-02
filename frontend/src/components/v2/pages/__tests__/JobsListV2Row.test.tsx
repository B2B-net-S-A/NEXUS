/**
 * Wiersz listy rekrutacji (02.10.2026): jeden układ dla każdej szerokości.
 * W wierszu stoi sama nazwa stanowiska, a pod nią kategoria, klient i tryb
 * pracy. Wymagania, nazwa od klienta, numery, miasta i data otwarcia zeszły
 * do Podglądu (`JobPreviewDetails`), „Podobne rekrutacje” — do ikony.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
    listDetails,
  }: {
    jobId: number | null;
    listDetails?: React.ReactNode;
    // Prop dokłada `JobsListV2` (kontrakt `job-list-nav.ts`); dok kroku 01
    // dostaje go od tej fali programu. Atrapa czyta go, żeby test wiązał się
    // z tym, CO lista przekazuje, a nie z tym, co dok z tym robi.
    listNav?: { index: number; total: number };
  }) => (
    <div data-testid="mock-dock">
      dock:{String(jobId)}
      {listDetails}
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

const FULL_ROW = {
  title: "Programista Python (ZOB-2947)",
  working_title: "Programista Python · Python, Microservices · 6+ lat",
  working_title_auto: true,
  must_skills: ["Python", "Microservices"],
  client_name: "Bank Przykładowy",
  client_reference: "ZOB-2947",
  reference_number: "PB/004/2026",
  competence_category_id: 2,
  remote_policy: "hybrid",
  onsite_days_per_week: 2,
  location: "Warszawa, Gdańsk, Gdynia",
  opened_effective_at: "2026-09-30T08:00:00Z",
  similar: {
    linked_count: 0,
    linked_first: null,
    reassigned_count: 0,
    suggested: {
      count: 5,
      sent_count: 24,
      first: { id: 9, title: "Python", reference_number: "PB/001/2026" },
    },
  },
};

describe("JobsListV2 — prosty wiersz listy", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    searchParamsMock.mockReturnValue(new URLSearchParams());
    useUiStore.setState({ jobsView: "list" });
  });

  it("jeden układ: bez kolumn Klient, Kategoria i Otwarta, strona bez limitu szerokości", async () => {
    mockJobsResponse([jobRow({ client_name: "Bank Przykładowy" })]);
    renderJobs();
    await screen.findByText("Senior Java Developer");

    // Jak pulpit: żadnego `max-w-*` ani wyśrodkowania na stronie listy.
    expect(screen.getByTestId("jobs-list-page").className).not.toMatch(/max-w-|mx-auto/);
    const headers = screen.getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual([
      "Rekrutacja",
      "Status",
      expect.stringContaining("Etapy"),
      "Termin",
      "Rekruter",
      "",
    ]);
    // Żadna kolumna ani komórka nie zależy od szerokości tabeli.
    expect(document.querySelector('[class*="@min-[1700px]"]')).toBeNull();
  });

  it("wiersz: nazwa stanowiska, a pod nią kategoria, klient i tryb pracy", async () => {
    mockJobsResponse([jobRow(FULL_ROW)]);
    renderJobs();

    const title = await screen.findByRole("link", { name: "Programista Python" });
    const cell = within(title.closest("td") as HTMLElement);
    // Pełny tytuł roboczy stoi w dymku opakowania, nie na samym linku.
    expect(title).not.toHaveAttribute("title");
    expect(title.parentElement).toHaveAttribute(
      "title",
      "Programista Python · Python, Microservices · 6+ lat",
    );
    expect(await cell.findByTestId("job-category-short")).toHaveTextContent("Dev");
    expect(cell.getByTestId("job-row-client")).toHaveTextContent("Bank Przykładowy");
    expect(cell.getByTestId("job-row-work-mode")).toHaveTextContent(
      "Hybrydowo · Warszawa +2",
    );

    // Z wiersza zeszły: wymagania, nazwa od klienta, numery i tekst przepięcia.
    const row = within(title.closest("tr") as HTMLElement);
    for (const gone of [/Microservices/, /ZOB-2947/, /PB\/004\/2026/, /Przepnij/, /Gdynia/]) {
      expect(row.queryByText(gone)).not.toBeInTheDocument();
    }
    expect(row.queryByTestId("job-similar-badge")).not.toBeInTheDocument();
    expect(row.getByTestId("job-similar-icon")).toHaveAccessibleName(
      "Podobne rekrutacje: 5 podobnych · 24 u klienta — przepnij",
    );
  });

  it("bez trybu pracy i bez klienta wiersz nie rysuje pustych znaczników", async () => {
    mockJobsResponse([jobRow({ competence_category_id: null })]);
    renderJobs();
    const title = await screen.findByRole("link", { name: "Senior Java Developer" });
    const cell = within(title.closest("td") as HTMLElement);
    expect(cell.queryByTestId("job-row-work-mode")).not.toBeInTheDocument();
    expect(cell.queryByTestId("job-row-client")).not.toBeInTheDocument();
    expect(cell.queryByTestId("job-category-short")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-similar-icon")).not.toBeInTheDocument();
  });

  it("krótka plakietka kategorii: skrót, pełna nazwa w podpowiedzi, nigdy surowy klucz", async () => {
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
    expect(badges[0].closest("td")).toBe(screen.getByText("Z kategorią").closest("td"));
    expect(badges[1]).toHaveTextContent("Kategoria bez skrótu");
  });

  it("data otwarcia stoi w dymku terminu: pole serwera, a bez niego dotychczasowe pola", async () => {
    mockJobsResponse([
      jobRow({
        id: 1,
        title: "Z nowego backendu",
        opened_effective_at: "2026-10-01T07:00:00Z",
        opened_at: "2026-09-30T08:00:00Z",
        created_at: "2026-05-05T10:00:00Z",
      }),
      jobRow({ id: 2, title: "Ze starego backendu", created_at: "2026-05-05T10:00:00Z" }),
    ]);
    renderJobs();
    await screen.findByText("Z nowego backendu");
    expect(screen.getByTitle("Otwarta 1.10.2026")).toBeInTheDocument();
    expect(screen.getByTitle("Otwarta 5.05.2026")).toBeInTheDocument();
  });

  it("Rekruter: pierwsza osoba i „+N”, reszta w podpowiedzi — jedna postać komórki", async () => {
    mockJobsResponse([
      jobRow({
        recruiters: [
          person(3, "Anna Nowak"),
          person(4, "Jan Kowalski", { via: "collaborator" }),
          person(6, "Ewa Proponowana", { via: "assignment", proposed: true }),
        ],
      }),
    ]);
    renderJobs();
    const cell = within(await screen.findByTestId("job-recruiter-cell"));
    expect(cell.getByText("Anna N.")).toBeInTheDocument();
    expect(cell.getByText("+1")).toBeInTheDocument();
    expect(cell.getByTitle(/Ewa Proponowana/)).toBeInTheDocument();
    expect(screen.queryByTestId("job-recruiter-names")).not.toBeInTheDocument();
  });

  it("Podgląd (ikona oka) pokazuje to, co zeszło z wiersza", async () => {
    const user = userEvent.setup();
    mockJobsResponse([jobRow(FULL_ROW)]);
    renderJobs();
    await screen.findByRole("link", { name: "Programista Python" });
    await user.click(
      screen.getByRole("button", { name: "Podgląd: Programista Python (ZOB-2947)" }),
    );

    const details = within(await screen.findByTestId("job-preview-details"));
    expect(details.getByText("Python")).toBeInTheDocument();
    expect(details.getByText("Microservices")).toBeInTheDocument();
    expect(details.getByText("Programista Python (ZOB-2947)")).toBeInTheDocument();
    expect(details.getByText("ZOB-2947")).toBeInTheDocument();
    expect(details.getByText("PB/004/2026")).toBeInTheDocument();
    expect(
      details.getByText("Hybrydowo · 2 dni w tygodniu · Warszawa, Gdańsk, Gdynia"),
    ).toBeInTheDocument();
    expect(details.getByText("30.09.2026")).toBeInTheDocument();
    const badge = details.getByTestId("job-similar-badge");
    expect(badge).toHaveTextContent("≈ 5 podobnych");
    expect(badge).toHaveTextContent("Przepnij →");
  });
});
