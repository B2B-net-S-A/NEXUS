/**
 * Lewa kolumna filtrów (krok 01 „Lista", program „flow w języku C2", PR 4/7).
 *
 * Zakres tego pliku: NOWA logika tego PR-a — filtry „Szybkie" wysyłają te
 * SAME parametry zapytania co dziś (tylko przeniesione z rzędu pigułek do
 * pionowej listy w aside), `include_stage_counts` jest zawsze włączone, a
 * „Brak opiekuna TAC" zawęża WYŁĄCZNIE bieżącą, już wczytaną stronę (bez
 * dodatkowego zapytania). `JobReadinessDock` jest zamockowany — ma własny
 * plik testów i nie jest przedmiotem tego pliku.
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

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/useCapability", () => ({
  useCapabilities: () => ({
    "job.create": false,
    "invite_link.create": false,
  }),
}));

vi.mock("@/components/v2/modals/CreateJobModal", () => ({
  CreateJobModal: () => null,
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

describe("JobsListV2 — filtry Szybkie → parametry zapytania", () => {
  beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, "hasPointerCapture", {
      configurable: true,
      value: () => false,
    });
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
      configurable: true,
      value: () => undefined,
    });
    Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", {
      configurable: true,
      value: () => undefined,
    });
  });

  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
    mockJobsResponse([jobRow()]);
  });

  it("zawsze wysyła `include_stage_counts: true` (mini-lejek bez zapytania per wiersz)", async () => {
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ include_stage_counts: true });
  });

  it("„Potrzebny search” wysyła needs_sourcing=true — ten sam parametr co dziś", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByText("Potrzebny search"));

    await waitFor(() => {
      expect(latestParams()).toMatchObject({ needs_sourcing: true });
    });
  });

  it("„Niezamknięte” wysyła open_only=true — ten sam parametr co dziś", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByText("Niezamknięte"));

    await waitFor(() => {
      expect(latestParams()).toMatchObject({ open_only: true });
    });
  });

  it("„Deadline ≤ 7 dni” wysyła okno deadline_from/deadline_to (bez ponownego wywoływania po wyłączeniu)", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByText("Deadline ≤ 7 dni"));
    await waitFor(() => {
      const params = latestParams();
      expect(params.deadline_from).toEqual(expect.any(String));
      expect(params.deadline_to).toEqual(expect.any(String));
    });

    await user.click(screen.getByText("Deadline ≤ 7 dni"));
    await waitFor(() => {
      const params = latestParams();
      expect(params.deadline_from).toBeUndefined();
      expect(params.deadline_to).toBeUndefined();
    });
  });

  it("„Wyczyść” resetuje filtr Typ i „Szybkie” razem", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    // `getByRole("button", ...)`, NIE `getByText` — fixture ma
    // `recruitment_type: "body_leasing"`, więc "Body leasing" wychodzi
    // DWA razy: jako pigułka Typ w aside i jako pill typu w wierszu listy.
    await user.click(screen.getByRole("button", { name: "Body leasing" }));
    await user.click(screen.getByText("Niezamknięte"));
    await waitFor(() => {
      expect(latestParams()).toMatchObject({
        recruitment_type: "body_leasing",
        open_only: true,
      });
    });

    // Realna poprawka w tym kroku: „Sales"/„Przetargi" wysyłają wartości
    // ENUMA (`sales_project`/`tender`), nie etykiety — stary kod wysyłał
    // `sales`/`tenders` i dostawał 422.
    await user.click(screen.getByRole("button", { name: "Sales" }));
    await waitFor(() => {
      expect(latestParams()).toMatchObject({ recruitment_type: "sales_project" });
    });
    await user.click(screen.getByRole("button", { name: "Przetargi" }));
    await waitFor(() => {
      expect(latestParams()).toMatchObject({ recruitment_type: "tender" });
    });

    await user.click(screen.getByText("Wyczyść"));
    await waitFor(() => {
      const params = latestParams();
      expect(params.recruitment_type).toBeUndefined();
      expect(params.open_only).toBeUndefined();
    });
  });

  it("typ rekrutacji ląduje w URL-u i znika z niego po „Wyczyść” (M03-B01)", async () => {
    window.history.replaceState(null, "", "/jobs");
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: "Przetargi" }));
    await waitFor(() => {
      expect(new URLSearchParams(window.location.search).get("type")).toBe(
        "tender",
      );
    });

    await user.click(screen.getByText("Wyczyść"));
    await waitFor(() => {
      expect(window.location.search).toBe("");
    });
  });
});

describe("JobsListV2 — „Brak opiekuna TAC” filtruje SERWER", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
  });

  it("wysyła owner_missing=true zamiast zawężać wczytaną stronę w przeglądarce", async () => {
    // Regresja, którą to zastępuje: filtr działał lokalnie, więc zawężał
    // wyłącznie 20 wczytanych wierszy, a paginacja dalej obiecywała strony,
    // na których nie było czego zawężać.
    mockJobsResponse([jobRow({ id: 1, title: "Bez ownera", tac_id: null })]);
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    // `getByRole("button", ...)`, NIE `getByText` — wiersz bez opiekuna TAC ma
    // WŁASNY badge „Brak opiekuna TAC" (status), więc tekst wychodzi dwukrotnie.
    await user.click(
      screen.getByRole("button", { name: /Brak opiekuna TAC/ }),
    );

    await waitFor(() => {
      expect(latestParams()).toMatchObject({ owner_missing: true });
    });
  });
});

describe("JobsListV2 — liczniki filtrów „Szybkie”", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    useUiStore.setState({ jobsView: "list" });
    mockJobsResponse([jobRow()]);
  });

  it("pokazuje liczbę z /api/jobs/quick-counts przy każdej z sześciu pozycji", async () => {
    mockQuickCounts();
    renderJobs();

    const expected: [RegExp, string][] = [
      [/Moje rekrutacje/, "12"],
      [/Niezamknięte/, "318"],
      [/Potrzebny search/, "41"],
      [/Aktywni w searchu/, "27"],
      [/Brak opiekuna TAC/, "63"],
      [/Deadline ≤ 7 dni/, "9"],
    ];
    for (const [label, count] of expected) {
      const row = await screen.findByRole("button", { name: label });
      // `waitFor`, nie samo `getByText`: przycisk filtra istnieje od
      // pierwszego renderu, a licznik dolatuje osobnym zapytaniem.
      await waitFor(() => {
        expect(within(row).getByText(count)).toBeInTheDocument();
      });
    }
  });

  it("wysyła to samo okno dat, którego używa preset „Najbliższe 7 dni”", async () => {
    // Gdyby okno liczył serwer, licznik i lista mogłyby wypaść o dzień
    // inaczej dla użytkownika w innej strefie czasowej.
    mockQuickCounts();
    renderJobs();

    await waitFor(() => expect(quickCountsMock).toHaveBeenCalled());
    const params = quickCountsMock.mock.calls.at(-1)?.[0] as
      | { deadline_from?: string; deadline_to?: string }
      | undefined;
    expect(params?.deadline_from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(params?.deadline_to).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("bez odpowiedzi z licznikami nie pokazuje zera — brak liczby to nie „zero w bazie”", async () => {
    quickCountsMock.mockRejectedValue(new Error("boom"));
    renderJobs();

    const row = await screen.findByRole("button", { name: /Moje rekrutacje/ });
    expect(within(row).queryByText("0")).not.toBeInTheDocument();
    // Sam filtr działa dalej — licznik jest dodatkiem, nie warunkiem.
    expect(row).toBeEnabled();
  });
});

describe("JobsListV2 — status jako pigułki", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
    mockJobsResponse([jobRow()]);
  });

  it("pigułka wysyła `status[]`, a „Wszystkie” czyści filtr", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    // Grupy pigułek Typ i Status obie mają pozycję „Wszystkie" — stąd
    // zapytanie w obrębie nazwanej grupy, a nie po samej nazwie przycisku.
    const statusGroup = within(
      screen.getByRole("group", { name: "Filtr: Status" }),
    );

    await user.click(statusGroup.getByRole("button", { name: "Zamknięta" }));
    await waitFor(() => {
      expect(latestParams()).toMatchObject({ status: ["closed"] });
    });

    await user.click(statusGroup.getByRole("button", { name: "Wszystkie" }));
    await waitFor(() => {
      expect(latestParams().status).toBeUndefined();
    });
  });
});

describe("JobsListV2 — liczby per grupa etapów w wierszu", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
  });

  it("pokazuje sześć liczb w kolejności lejka, bez rejected/withdrawn", async () => {
    mockJobsResponse([
      jobRow({
        stage_breakdown: { new: 3, screening: 2, hired: 1, rejected: 5 },
      }),
    ]);
    renderJobs();
    const cell = await screen.findByTestId("job-stage-counts");
    expect(cell).toHaveAccessibleName(
      "Etapy: Nowi 3, Screening 2, Zweryfikowani 0, U klienta 0, Umowa 0, Zatrudnieni 1",
    );
    // `rejected` jest poza sześcioma grupami — nigdzie nie ma „5".
    expect(within(cell).queryByText("5")).not.toBeInTheDocument();
  });

  it("tooltip grupy wymienia PEŁNE nazwy etapów szablonu z liczbami", async () => {
    mockJobsResponse([
      jobRow({
        stage_columns: [
          { stage: "new", name: "Nowy", count: 2, category: "internal", order: 0 },
          { stage: "screening", name: "Screening", count: 1, category: "internal", order: 1 },
          { stage: "new", name: "Przepuszczony przez DZ", count: 4, category: "internal", order: 2 },
          { stage: "verified", name: "Zweryfikowany", count: 1, category: "internal", order: 3 },
        ],
      }),
    ]);
    renderJobs();
    const cell = await screen.findByTestId("job-stage-counts");
    const verified = cell.querySelector('[data-group="verified"]') as HTMLElement;
    expect(verified).toHaveTextContent("5");
    expect(verified.getAttribute("title")).toBe(
      "Zweryfikowani: Przepuszczony przez DZ 4 · Zweryfikowany 1",
    );
  });

  it("bez `stage_breakdown` cofa się do paska filled/target, nie chowa kolumny", async () => {
    mockJobsResponse([jobRow({ stage_breakdown: undefined, headcount: 3 })]);
    renderJobs();
    expect(await screen.findByText("0/3")).toBeInTheDocument();
  });
});

describe("JobsListV2 — „Wymaga ruchu” i propozycje", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
  });

  it("ton pigułki zależy od liczby, a zero to wyszarzone „na bieżąco”", async () => {
    mockJobsResponse([
      jobRow({ id: 1, title: "Zero", needs_action_count: 0 }),
      jobRow({ id: 2, title: "Kilka", needs_action_count: 3 }),
      jobRow({ id: 3, title: "Zaległość", needs_action_count: 7 }),
    ]);
    renderJobs();
    await screen.findByText("Zero");
    const pills = screen.getAllByTestId("job-needs-action");
    expect(pills.map((p) => [p.textContent, p.dataset.tone])).toEqual([
      ["na bieżąco", "muted"],
      ["3 do ruchu", "warning"],
      ["7 do ruchu", "danger"],
    ]);
  });

  it("bez pola w odpowiedzi pokazuje kreskę, nie „na bieżąco” (brak wiedzy ≠ zero)", async () => {
    mockJobsResponse([jobRow({ title: "Stary backend" })]);
    renderJobs();
    await screen.findByText("Stary backend");
    expect(screen.queryByTestId("job-needs-action")).not.toBeInTheDocument();
  });

  it("„do przejrzenia” (stos wejściowy) stoi osobno od „do ruchu” i znika przy zerze", async () => {
    mockJobsResponse([
      jobRow({ id: 1, title: "Stos", needs_action_count: 2, review_count: 431 }),
      jobRow({ id: 2, title: "Pusto", needs_action_count: 1, review_count: 0 }),
    ]);
    renderJobs();
    await screen.findByText("Stos");
    const review = await screen.findAllByTestId("job-review-count");
    expect(review).toHaveLength(1);
    expect(review[0]).toHaveTextContent("431 do przejrzenia");
    expect(screen.getAllByTestId("job-needs-action")[0]).toHaveTextContent("2 do ruchu");
  });

  it("„+N propozycji” linkuje do segmentu propozycji i znika przy zerze", async () => {
    mockJobsResponse([
      jobRow({ id: 11, title: "Z propozycjami", open_proposals_count: 3 }),
      jobRow({ id: 12, title: "Bez propozycji", open_proposals_count: 0 }),
    ]);
    renderJobs();
    const link = await screen.findByRole("link", { name: "+3 propozycje" });
    expect(link).toHaveAttribute("href", "/jobs/11?tab=people&seg=proposals");
    expect(screen.queryByText(/\+0 propozycj/)).not.toBeInTheDocument();
  });
});

describe("JobsListV2 — zakres „Moje | Wszystkie” i sortowanie", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
    mockJobsResponse([jobRow()]);
    window.history.replaceState(null, "", "/jobs");
  });

  it("bez parametru w adresie startuje w „Moich”, posortowana wg „Wymaga uwagi”", async () => {
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ mine: true, sort: "attention" });
    expect(window.location.search).toBe("");
  });

  it("segment pokazuje liczniki z quick-counts", async () => {
    renderJobs();
    const scope = within(
      await screen.findByRole("group", { name: "Zakres rekrutacji" }),
    );
    await waitFor(() => {
      expect(scope.getByRole("button", { name: /Moje\s*12/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(
      scope.getByRole("button", { name: /Wszystkie\s*4\s?241/ }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("„Wszystkie” zdejmuje `mine`, wraca do „Od najnowszej” i zapisuje mine=0 w adresie", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    const scope = within(screen.getByRole("group", { name: "Zakres rekrutacji" }));

    await user.click(scope.getByRole("button", { name: /Wszystkie/ }));

    await waitFor(() => {
      expect(latestParams().mine).toBeUndefined();
      expect(latestParams()).toMatchObject({ sort: "newest" });
    });
    await waitFor(() => expect(window.location.search).toBe("?mine=0"));
  });

  it("admin / HoR / Finanse / viewer startują we „Wszystkich”, od najnowszej", async () => {
    for (const role of ["admin", "head_of_recruitment", "finance", "user"]) {
      getMock.mockClear();
      signInAs(role);
      const view = renderJobs();
      await waitFor(() => expect(jobsCalls()).toHaveLength(1));
      expect(latestParams().mine, role).toBeUndefined();
      expect(latestParams(), role).toMatchObject({ sort: "newest" });
      expect(window.location.search).toBe("");
      view.unmount();
    }
  });

  it("konto wielorolowe z rolą prowadzącą dostaje „Moje”", async () => {
    signInAs("admin", "delivery_lead");
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ mine: true, sort: "attention" });
  });

  it("jawne „Moje” u admina zapisuje mine=1, a „Wyczyść” wraca do domyślnego roli", async () => {
    signInAs("admin");
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    const scope = within(screen.getByRole("group", { name: "Zakres rekrutacji" }));

    await user.click(scope.getByRole("button", { name: /Moje/ }));
    await waitFor(() =>
      expect(latestParams()).toMatchObject({ mine: true, sort: "attention" }),
    );
    await waitFor(() => expect(window.location.search).toBe("?mine=1"));

    await user.click(screen.getByText("Wyczyść"));
    await waitFor(() => expect(latestParams().mine).toBeUndefined());
    await waitFor(() => expect(window.location.search).toBe(""));
  });

  it("„Wyczyść” u rekrutera wraca do „Moich”", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    const scope = within(screen.getByRole("group", { name: "Zakres rekrutacji" }));
    await user.click(scope.getByRole("button", { name: /Wszystkie/ }));
    await waitFor(() => expect(latestParams().mine).toBeUndefined());

    await user.click(screen.getByText("Wyczyść"));
    await waitFor(() => expect(latestParams()).toMatchObject({ mine: true }));
  });

  it("nie pyta API przed hydratacją store'u (rola jeszcze nieznana)", async () => {
    useAuthStore.setState({ user: null, hydrated: false });
    renderJobs();
    await new Promise((r) => setTimeout(r, 30));
    expect(jobsCalls()).toHaveLength(0);
  });

  it("pusty zakres „Moje” nie udaje pustej bazy — proponuje „Pokaż wszystkie”", async () => {
    mockJobsResponse([]);
    const user = userEvent.setup();
    renderJobs();
    expect(
      await screen.findByText(/Nie prowadzisz teraz żadnej rekrutacji/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pokaż wszystkie" }));
    await waitFor(() => expect(latestParams().mine).toBeUndefined());
  });
});

describe("JobsListV2 — zwijana kolumna filtrów", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list", jobsFiltersCollapsed: false });
    mockJobsResponse([jobRow()]);
    window.history.replaceState(null, "", "/jobs");
  });

  it("przycisk „Filtry (N)” liczy czynne zawężenia (bez zakresu) i zwija kolumnę", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    const toggle = screen.getByRole("button", { name: "Filtry" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await user.click(screen.getByText("Niezamknięte"));
    const counted = await screen.findByRole("button", { name: "Filtry (1)" });

    await user.click(counted);
    expect(useUiStore.getState().jobsFiltersCollapsed).toBe(true);
    expect(counted).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.getByRole("complementary", {
        name: "Filtry listy rekrutacji",
        hidden: true,
      }),
    ).toHaveClass("hidden");
  });

  it("bez zapisanego wyboru kolumna idzie za szerokością okna (CSS `2xl`)", async () => {
    useUiStore.setState({ jobsFiltersCollapsed: null });
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(
      screen.getByRole("complementary", {
        name: "Filtry listy rekrutacji",
        hidden: true,
      }),
    ).toHaveClass("hidden", "2xl:block");
  });
});

describe("JobsListV2 — widok kafelków (domyślny)", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "tiles" });
  });

  it("pasek „Kandydaci” czyta `candidate_count`/`headcount` z odpowiedzi API, nie nieistniejące pola", async () => {
    // Regresja: do 09.2026 kafelek czytał `candidates_count`/`filled_count`/
    // `target_positions` — pól, których `GET /api/jobs` nigdy nie zwracał —
    // więc na produkcji każdy kafelek pokazywał „0/N" niezależnie od pipeline'u.
    mockJobsResponse([jobRow({ candidate_count: 3, headcount: 5 })]);
    renderJobs();
    expect(await screen.findByText("3/5")).toBeInTheDocument();
    expect(screen.queryByText("0/5")).not.toBeInTheDocument();
  });
});

describe("JobsListV2 — klik w wiersz otwiera rekrutację, dok ma ikonę „Podgląd”", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    pushMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
  });

  it("klik w wiersz prowadzi do /jobs/{id}, a dok nie otwiera się sam", async () => {
    mockJobsResponse([jobRow({ id: 42, title: "Pierwsza w kolejności" })]);
    const user = userEvent.setup();
    renderJobs();
    const title = await screen.findByText("Pierwsza w kolejności");
    expect(screen.queryByTestId("mock-dock")).not.toBeInTheDocument();

    await user.click(title.closest("tr") as HTMLElement);
    expect(pushMock).toHaveBeenCalledWith("/jobs/42");
    expect(screen.queryByTestId("mock-dock")).not.toBeInTheDocument();
  });

  it("„Podgląd” otwiera dok z tą rekrutacją, nie nawiguje, i zamyka się z klawiatury", async () => {
    mockJobsResponse([
      jobRow({ id: 1, title: "Pierwsza" }),
      jobRow({ id: 2, title: "Druga" }),
      jobRow({ id: 3, title: "Trzecia" }),
    ]);
    const user = userEvent.setup();
    renderJobs();
    await screen.findByText("Pierwsza");

    const preview = screen.getByRole("button", { name: "Podgląd: Druga" });
    preview.focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByTestId("mock-dock")).toHaveTextContent("dock:2");
    expect(screen.getByTestId("mock-nav")).toHaveTextContent("nav:2/3");
    expect(preview).toHaveAttribute("aria-pressed", "true");
    expect(pushMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Zamknij podgląd" }));
    expect(screen.queryByTestId("mock-dock")).not.toBeInTheDocument();
  });

  it("nie podaje nawigacji, gdy strona ma jeden wiersz — „1 z 1” to nie nawigacja", async () => {
    mockJobsResponse([jobRow({ id: 9, title: "Jedyna" })]);
    const user = userEvent.setup();
    renderJobs();
    await screen.findByText("Jedyna");
    await user.click(screen.getByRole("button", { name: "Podgląd: Jedyna" }));

    expect(await screen.findByTestId("mock-dock")).toHaveTextContent("dock:9");
    expect(screen.queryByTestId("mock-nav")).not.toBeInTheDocument();
  });
});

describe("JobsListV2 — wiersz bez dostępu (can_open === false)", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
  });

  it("wiersz jest czytelny, ale nie udaje klikalnego — jak kafelek", async () => {
    mockJobsResponse([
      jobRow({ id: 5, title: "Otwarta" }),
      jobRow({ id: 6, title: "Cudza", can_open: false }),
    ]);
    renderJobs();

    // Tytuł bez dostępu NIE jest linkiem: `<span aria-disabled>` zamiast
    // wyłączonego `<a>` — link prowadziłby prosto w 403.
    expect(screen.queryByRole("link", { name: "Cudza" })).toBeNull();
    const title = await screen.findByText("Cudza");
    expect(title).toHaveAttribute("aria-disabled", "true");
    expect(title.getAttribute("title")).toContain("Nie masz dostępu");
    const row = title.closest("tr") as HTMLElement;
    expect(row).toHaveAttribute("aria-disabled", "true");
    expect(row.getAttribute("title")).toContain("Nie masz dostępu");

    const openLink = screen.getByRole("link", { name: "Otwarta" });
    expect(openLink).not.toHaveAttribute("aria-disabled");

    // Wiersz bez dostępu nie nawiguje po kliknięciu i nie ma „Podglądu”
    // (dok pytałby o detal → 403).
    const user = userEvent.setup();
    await user.click(row);
    expect(pushMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Podgląd: Cudza" })).toBeNull();
    expect(screen.getByRole("button", { name: "Podgląd: Otwarta" })).toBeEnabled();
  });
});
