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

// Te scenariusze opisują listę z WŁĄCZONĄ funkcją TAC (dziś wyłączona — lib/tac-ui.ts).
vi.mock("@/lib/tac-ui", () => ({ TAC_UI_ENABLED: true }));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
  },
  jobsApi: {
    quickCounts: (...args: unknown[]) => quickCountsMock(...args),
  },
}));

const pushMock = vi.fn();
// Adres przy montowaniu — czytany leniwie, więc test może go podmienić.
const navState = { search: "" };

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => new URLSearchParams(navState.search),
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

  it("dawny szybki filtr „Niezamknięte” zniknął — zastąpił go zakres „Otwarte” (open_only=true)", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(screen.queryByText("Niezamknięte")).not.toBeInTheDocument();
    expect(screen.queryByText("Moje rekrutacje")).not.toBeInTheDocument();

    const scope = within(screen.getByRole("group", { name: "Zakres rekrutacji" }));
    await user.click(scope.getByRole("button", { name: /Otwarte/ }));

    await waitFor(() => {
      expect(latestParams()).toMatchObject({ open_only: true, sort: "newest" });
      expect(latestParams().mine).toBeUndefined();
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
    await user.click(screen.getByText("Potrzebny search"));
    await waitFor(() => {
      expect(latestParams()).toMatchObject({
        recruitment_type: "body_leasing",
        needs_sourcing: true,
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
      expect(params.needs_sourcing).toBeUndefined();
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

  it("pokazuje liczbę z /api/jobs/quick-counts przy każdej pozycji", async () => {
    mockQuickCounts();
    renderJobs();

    const expected: [RegExp, string][] = [
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

    const row = await screen.findByRole("button", { name: /Potrzebny search/ });
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

  it("pokazuje osiem liczb w kolejności kolumn Tablicy, bez rejected/withdrawn", async () => {
    mockJobsResponse([
      jobRow({
        stage_breakdown: { new: 3, screening: 2, hired: 1, rejected: 5 },
      }),
    ]);
    renderJobs();
    const cell = await screen.findByTestId("job-stage-counts");
    expect(cell).toHaveAccessibleName(
      "Etapy: Nowi 3, Screening 2, Zweryfikowany 0, QC CV 0, CV wysłane 0, " +
        "Rozmowa u klienta 0, Umowa 0, Zatrudniony 1",
    );
    // `rejected` jest poza ośmioma kolumnami — nigdzie nie ma „5".
    expect(within(cell).queryByText("5")).not.toBeInTheDocument();
    // W wierszu same liczby — skróty kolumn stoją RAZ, w nagłówku.
    expect(within(cell).queryByText("Now")).not.toBeInTheDocument();
    const header = screen.getByTestId("job-stage-counts-header");
    expect(header).toHaveTextContent("NowScrZweQCWysRozUmZat");
    expect(within(header).getByText("QC")).toHaveAttribute("title", "QC CV");
  });

  it("etap QC CV (kod `interview`) ma własną kolumnę, a tooltip wymienia pełne nazwy etapów", async () => {
    mockJobsResponse([
      jobRow({
        stage_columns: [
          { stage: "new", name: "Nowy", count: 2, category: "internal", order: 0 },
          { stage: "screening", name: "Screening", count: 1, category: "internal", order: 1 },
          { stage: "verified", name: "Zweryfikowany", count: 1, category: "internal", order: 2 },
          { stage: "interview", name: "Przepuszczony przez DZ", count: 4, category: "internal", order: 3 },
          { stage: "new", name: "Wysłać do Cpro", count: 1, category: "internal", order: 4 },
        ],
      }),
    ]);
    renderJobs();
    const cell = await screen.findByTestId("job-stage-counts");
    const verified = cell.querySelector('[data-group="verified"]') as HTMLElement;
    const qc = cell.querySelector('[data-group="cv_qc"]') as HTMLElement;
    expect(verified).toHaveTextContent("1");
    expect(qc).toHaveTextContent("5");
    expect(qc.getAttribute("title")).toBe(
      "QC CV: Przepuszczony przez DZ 4 · Wysłać do Cpro 1",
    );
  });

  it("bez `stage_breakdown` cofa się do paska filled/target, nie chowa kolumny", async () => {
    mockJobsResponse([jobRow({ stage_breakdown: undefined, headcount: 3 })]);
    renderJobs();
    expect(await screen.findByText("0/3")).toBeInTheDocument();
  });
});

describe("JobsListV2 — status requestu i podobne rekrutacje (lista v4)", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
    window.history.replaceState(null, "", "/jobs");
  });

  it("kolumna „Status” nazywa status liczony przez serwer, nieznany = kreska", async () => {
    mockJobsResponse([
      jobRow({ id: 1, title: "Szuka", request_status: "searching" }),
      jobRow({ id: 2, title: "Champion", request_status: "champion" }),
      jobRow({ id: 3, title: "Stary backend" }),
    ]);
    renderJobs();
    await screen.findByText("Szuka");
    const table = screen.getByRole("table");
    expect(within(table).getByText("Szukamy")).toBeInTheDocument();
    expect(within(table).getByText("Mamy championa")).toBeInTheDocument();
    expect(screen.queryByTestId("job-needs-action")).not.toBeInTheDocument();
  });

  it("pigułka statusu wysyła `request_status` i zapisuje go w adresie", async () => {
    const user = userEvent.setup();
    mockJobsResponse([jobRow()]);
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    await user.click(
      within(screen.getByRole("group", { name: "Status requestu" })).getByRole("button", {
        name: "Mamy championa",
      }),
    );
    await waitFor(() => expect(latestParams().request_status).toEqual(["champion"]));
    expect(window.location.search).toContain("rs=champion");
  });

  it("„≈ podobne” otwiera okno przepięć, „↻” pokazuje połączoną rekrutację", async () => {
    const user = userEvent.setup();
    mockJobsResponse([
      jobRow({
        id: 21,
        title: "Z sugestią",
        similar: {
          linked_count: 0,
          linked_first: null,
          reassigned_count: 0,
          suggested: { count: 2, sent_count: 5, first: { id: 9, title: "Kotlin", reference_number: "#4588" } },
        },
      }),
      jobRow({
        id: 22,
        title: "Połączona",
        similar: {
          linked_count: 1,
          linked_first: { id: 9, title: "Kotlin", reference_number: "#4588" },
          reassigned_count: 3,
          suggested: null,
        },
      }),
    ]);
    renderJobs();
    await screen.findByText("Z sugestią");
    expect(screen.getByText("↻ #4588")).toBeInTheDocument();
    expect(screen.getByText("przepięto 3")).toBeInTheDocument();
    getMock.mockResolvedValueOnce({
      data: { job_id: 21, reassigned_count: 0, linked: [], suggestions: [] },
    });
    await user.click(screen.getByText("≈ 2 podobne"));
    expect(await screen.findByRole("dialog", { name: "Podobne rekrutacje" })).toBeInTheDocument();
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

  it("segment „Moje | Otwarte | Wszystkie” pokazuje liczniki z quick-counts", async () => {
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
    expect(scope.getByRole("button", { name: /Otwarte\s*318/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(
      scope.getByRole("button", { name: /Wszystkie\s*4\s?241/ }),
    ).toHaveAttribute("aria-pressed", "false");
  });

  it("„Otwarte” u rekrutera zapisuje open=1 w adresie", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    const scope = within(screen.getByRole("group", { name: "Zakres rekrutacji" }));
    await user.click(scope.getByRole("button", { name: /Otwarte/ }));
    await waitFor(() => expect(window.location.search).toBe("?open=1"));
    expect(latestParams()).toMatchObject({ open_only: true });
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

  it("admin / HoR / Finanse / viewer startują w „Otwartych” (bez zamkniętych), od najnowszej", async () => {
    for (const role of ["admin", "head_of_recruitment", "finance", "user"]) {
      getMock.mockClear();
      signInAs(role);
      const view = renderJobs();
      await waitFor(() => expect(jobsCalls()).toHaveLength(1));
      expect(latestParams().mine, role).toBeUndefined();
      expect(latestParams(), role).toMatchObject({ sort: "newest", open_only: true });
      expect(window.location.search).toBe("");
      view.unmount();
    }
  });

  it("stare `mine=0` z pulpitu dalej znaczy „Wszystkie” — bez open_only", async () => {
    signInAs("admin");
    window.history.replaceState(null, "", "/jobs?mine=0");
    navState.search = "mine=0";
    try {
      renderJobs();
      await waitFor(() => expect(jobsCalls()).toHaveLength(1));
      expect(latestParams().open_only).toBeUndefined();
      expect(latestParams().mine).toBeUndefined();
      const scope = within(screen.getByRole("group", { name: "Zakres rekrutacji" }));
      expect(scope.getByRole("button", { name: /Wszystkie/ })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    } finally {
      navState.search = "";
    }
  });

  it("konto wielorolowe z rolą prowadzącą dostaje „Moje”", async () => {
    signInAs("admin", "delivery_lead");
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ mine: true, sort: "attention" });
  });

  it("jawne „Moje” u admina zapisuje mine=1, a „Wyczyść” wraca do domyślnego roli („Otwarte”)", async () => {
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
    expect(latestParams()).toMatchObject({ open_only: true });
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

    await user.click(screen.getByText("Potrzebny search"));
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

  it("bez zapisanego wyboru kolumna filtrów jest zwinięta (lista v4)", async () => {
    useUiStore.setState({ jobsFiltersCollapsed: null });
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Filtry" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(
      screen.getByRole("complementary", {
        name: "Filtry listy rekrutacji",
        hidden: true,
      }),
    ).toHaveClass("hidden");
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

describe("JobsListV2 — lista v5: liczby statusów, termin, nowe filtry", () => {
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
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: () => undefined,
    });
  });

  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    useUiStore.setState({ jobsView: "list", jobsFiltersCollapsed: false });
    window.history.replaceState(null, "", "/jobs");
    navState.search = "";
  });

  const statusCounts = {
    request_status: {
      searching: 210,
      champion: 14,
      contract: 9,
      filled: 5,
      incomplete: 80,
      closed: 3968,
    },
    request_status_mine: {
      searching: 7,
      champion: 1,
      contract: 0,
      filled: 2,
      incomplete: 2,
      closed: 30,
    },
  };

  it("pigułki statusu requestu pokazują liczby zakresu: „Moje” — moje, „Otwarte” — rejestr", async () => {
    mockJobsResponse([jobRow()]);
    quickCountsMock.mockResolvedValue({
      data: {
        all: 4286,
        mine: 42,
        open: 318,
        needs_sourcing: 1,
        active_in_search: 1,
        owner_missing: 1,
        deadline_7d: 1,
        ...statusCounts,
      },
    });
    const user = userEvent.setup();
    renderJobs();
    const chips = within(await screen.findByRole("group", { name: "Status requestu" }));
    await waitFor(() =>
      expect(chips.getByRole("button", { name: /Szukamy\s*7/ })).toBeInTheDocument(),
    );
    expect(chips.getByRole("button", { name: /Umowa\s*0/ })).toBeInTheDocument();

    const scope = within(screen.getByRole("group", { name: "Zakres rekrutacji" }));
    await user.click(scope.getByRole("button", { name: /Otwarte/ }));
    await waitFor(() =>
      expect(chips.getByRole("button", { name: /Szukamy\s*210/ })).toBeInTheDocument(),
    );
    expect(chips.getByRole("button", { name: /Do uzupełnienia\s*80/ })).toBeInTheDocument();
  });

  it("bez liczników statusu (starszy backend) pigułki nie udają zera", async () => {
    mockJobsResponse([jobRow()]);
    mockQuickCounts();
    renderJobs();
    const chips = within(await screen.findByRole("group", { name: "Status requestu" }));
    await waitFor(() => expect(quickCountsMock).toHaveBeenCalled());
    expect(chips.getByRole("button", { name: "Szukamy" })).toBeInTheDocument();
  });

  it("termin: data + „za N dni” / „po terminie N dni” z tonem, brak = kreska", async () => {
    const inDays = (n: number) => {
      const d = new Date();
      d.setDate(d.getDate() + n);
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      return `${d.getFullYear()}-${m}-${day}`;
    };
    mockJobsResponse([
      jobRow({ id: 1, title: "Po terminie", deadline: inDays(-3) }),
      jobRow({ id: 2, title: "Wkrótce", deadline: inDays(5) }),
      jobRow({ id: 3, title: "Daleko", deadline: inDays(30) }),
      jobRow({ id: 4, title: "Bez terminu", deadline: null }),
    ]);
    mockQuickCounts();
    renderJobs();
    await screen.findByText("Po terminie");
    const cells = screen.getAllByTestId("job-deadline");
    expect(cells.map((c) => c.getAttribute("data-urgency"))).toEqual([
      "overdue",
      "soon",
      "normal",
    ]);
    expect(cells[0]).toHaveTextContent("po terminie 3 dni");
    expect(cells[1]).toHaveTextContent("za 5 dni");
    expect(cells[2]).toHaveTextContent("za 30 dni");
    expect(within(cells[0]).getByText("po terminie 3 dni")).toHaveClass("text-destructive");
    expect(within(cells[1]).getByText("za 5 dni")).toHaveClass("text-warning");
    const noDeadlineRow = screen.getByText("Bez terminu").closest("tr") as HTMLElement;
    expect(within(noDeadlineRow).queryByTestId("job-deadline")).not.toBeInTheDocument();
  });

  it("tytuł w dwóch liniach, „Podobne rekrutacje” to plakietka pod tytułem (bez osobnej kolumny)", async () => {
    mockJobsResponse([
      jobRow({
        id: 31,
        title: "Bardzo długi tytuł rekrutacji z klientem i technologią w nazwie",
        client_name: "Bank Demo",
        similar: {
          linked_count: 0,
          linked_first: null,
          reassigned_count: 0,
          suggested: { count: 3, sent_count: 4, first: { id: 9, title: "X", reference_number: "#1" } },
        },
      }),
    ]);
    mockQuickCounts();
    renderJobs();
    const title = await screen.findByRole("link", { name: /Bardzo długi tytuł/ });
    expect(title).toHaveClass("line-clamp-2");
    expect(screen.queryByRole("columnheader", { name: /Podobne/ })).not.toBeInTheDocument();
    const badge = screen.getByTestId("job-similar-badge");
    expect(badge).toHaveTextContent("≈ 3 podobne");
    expect(badge).toHaveTextContent("Przepnij →");
    // Plakietka stoi w komórce tytułu, obok klienta.
    expect(title.closest("td")).toContainElement(badge);
  });

  it("„Wysłanych do klienta” wysyła min_sent/max_sent i liczy się do „Filtry (N)”", async () => {
    mockJobsResponse([jobRow()]);
    mockQuickCounts();
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByRole("combobox", { name: "Filtr: Wysłanych do klienta" }));
    await user.click(await screen.findByRole("option", { name: "Co najmniej 3 osoby" }));
    await waitFor(() => expect(latestParams()).toMatchObject({ min_sent: 3 }));
    expect(latestParams().max_sent).toBeUndefined();
    expect(await screen.findByRole("button", { name: "Filtry (1)" })).toBeInTheDocument();
    await waitFor(() => expect(window.location.search).toContain("sent=3"));

    await user.click(screen.getByRole("combobox", { name: "Filtr: Wysłanych do klienta" }));
    await user.click(await screen.findByRole("option", { name: "Nikt jeszcze" }));
    await waitFor(() => expect(latestParams()).toMatchObject({ max_sent: 0 }));
    expect(latestParams().min_sent).toBeUndefined();

    await user.click(screen.getByText("Wyczyść"));
    await waitFor(() => {
      expect(latestParams().min_sent).toBeUndefined();
      expect(latestParams().max_sent).toBeUndefined();
    });
  });

  it("Delivery Lead i zakres terminu z adresu idą do API (delivery_lead_id, deadline_from/to)", async () => {
    navState.search = "lead=5&lead=8&deadline=range&dl_from=2026-10-01&dl_to=2026-10-31";
    mockJobsResponse([jobRow()]);
    mockQuickCounts();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({
      delivery_lead_id: [5, 8],
      deadline_from: "2026-10-01",
      deadline_to: "2026-10-31",
    });
    // Dwie osoby + termin = 3 zawężenia.
    expect(screen.getByRole("button", { name: "Filtry (3)" })).toBeInTheDocument();
    expect(screen.getByLabelText("Termin od")).toHaveValue("2026-10-01");
    expect(screen.getByLabelText("Termin do")).toHaveValue("2026-10-31");
  });
});
