/**
 * Lista rekrutacji: pasek filtrów nad tabelą (25.09.2026), rząd „Stan
 * requestu”, zakres, sortowanie, wiersze. Filtry wysyłają parametry do
 * serwera (`request_stage`, `worked_by`, `nobody_working`, …), a liczby
 * przychodzą z `GET /api/jobs/quick-counts`. `JobReadinessDock` jest
 * zamockowany — ma własny plik testów.
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
    ...overrides,
  };
}

function mockJobsResponse(items: ReturnType<typeof jobRow>[]) {
  getMock.mockResolvedValue({
    data: { items, total: items.length, page: 1, page_size: 20 },
  });
}

/** Liczniki zakresu, pigułek i przełączników — z `GET /api/jobs/quick-counts`. */
function mockQuickCounts(overrides: Record<string, unknown> = {}) {
  quickCountsMock.mockResolvedValue({
    data: {
      all: 4241,
      mine: 12,
      open: 318,
      attention: { overdue: 4, nobody_working: 7, nobody_sent: 11 },
      attention_mine: { overdue: 1, nobody_working: 0, nobody_sent: 2 },
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

  it("kolumny filtrów nie ma: bez „Typ”, „Szybkie”, „Status”, „Priority Work” i „Osoba odpowiedzialna”", async () => {
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(screen.queryByRole("complementary", { name: /Filtry/ })).not.toBeInTheDocument();
    for (const text of [
      "Potrzebny search",
      "Aktywni w searchu",
      "Deadline ≤ 7 dni",
      "Priority Work",
      "Osoba odpowiedzialna",
      "Wszystkie filtry",
    ]) {
      expect(screen.queryByText(text), text).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("group", { name: "Filtr: Status" })).not.toBeInTheDocument();
    const params = latestParams();
    for (const key of [
      "status",
      "recruitment_type",
      "needs_sourcing",
      "active_in_search",
      "owner_missing",
      "priority_work",
      "responsible_id",
      "request_status",
      "work_state",
    ]) {
      expect(params[key], key).toBeUndefined();
    }
  });

  it("stare klucze adresu nie zawężają listy i znikają z adresu; `rs`/`ws` przechodzą w pigułkę stanu", async () => {
    navState.search =
      "type=tender&status=closed&responsible=4&sourcing=1&active_search=1&priority=assigned&rs=champion&ws=finished";
    window.history.replaceState(null, "", `/jobs?${navState.search}`);
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({ request_stage: ["champion"] });
    expect(latestParams().status).toBeUndefined();
    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.getAll("stage")).toEqual(["champion"]);
      for (const key of ["type", "status", "responsible", "sourcing", "active_search", "priority", "rs", "ws"]) {
        expect(params.get(key), key).toBeNull();
      }
    });
    navState.search = "";
    window.history.replaceState(null, "", "/jobs");
  });

  it("„Po terminie” wysyła termin do wczoraj, a drugi klik go zdejmuje", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: /Po terminie/ }));
    await waitFor(() => {
      const params = latestParams();
      expect(params.deadline_to).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(params.deadline_from).toBeUndefined();
    });
    expect(screen.getByRole("button", { name: /Po terminie/ })).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: /Po terminie/ }));
    await waitFor(() => expect(latestParams().deadline_to).toBeUndefined());
  });

  it("„Nikt nie pracuje” wysyła nobody_working, „Nikogo nie wysłano” — max_sent=0", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: /Nikt nie pracuje/ }));
    await waitFor(() => expect(latestParams()).toMatchObject({ nobody_working: true }));
    await user.click(screen.getByRole("button", { name: /Nikogo nie wysłano/ }));
    await waitFor(() => expect(latestParams()).toMatchObject({ nobody_working: true, max_sent: 0 }));
    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.get("nobody")).toBe("1");
      expect(params.get("sent")).toBe("none");
    });

    await user.click(screen.getByRole("button", { name: /Wyczyść filtry/ }));
    await waitFor(() => {
      expect(latestParams().nobody_working).toBeUndefined();
      expect(latestParams().max_sent).toBeUndefined();
    });
    window.history.replaceState(null, "", "/jobs");
  });

  it("„Kto pracuje” → „Ja” wysyła worked_by z id zalogowanej osoby", async () => {
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: /Kto pracuje/ }));
    await user.click(await screen.findByRole("checkbox", { name: "Ja" }));
    await waitFor(() => expect(latestParams()).toMatchObject({ worked_by: [7] }));
    expect(screen.getByRole("button", { name: /Kto pracuje: ja/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Wyczyść: Kto pracuje" }));
    await waitFor(() => expect(latestParams().worked_by).toBeUndefined());
  });
});

describe("JobsListV2 — liczniki przełączników „wymaga uwagi”", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    useUiStore.setState({ jobsView: "list" });
    mockJobsResponse([jobRow()]);
  });

  it("w „Moich” liczby zakresu „Moje”, w „Otwartych” — rejestru, we „Wszystkich” — bez liczb", async () => {
    mockQuickCounts();
    const user = userEvent.setup();
    renderJobs();

    const overdue = await screen.findByRole("button", { name: /Po terminie/ });
    await waitFor(() => expect(within(overdue).getByText("1")).toBeInTheDocument());

    const scope = within(screen.getByRole("group", { name: "Zakres rekrutacji" }));
    await user.click(scope.getByRole("button", { name: /Otwarte/ }));
    await waitFor(() =>
      expect(within(screen.getByRole("button", { name: /Po terminie/ })).getByText("4")).toBeInTheDocument(),
    );
    expect(within(screen.getByRole("button", { name: /Nikt nie pracuje/ })).getByText("7")).toBeInTheDocument();

    await user.click(scope.getByRole("button", { name: /Wszystkie/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Po terminie/ })).toHaveTextContent(/^Po terminie$/),
    );
    window.history.replaceState(null, "", "/jobs");
  });

  it("wysyła datę „Po terminie” liczoną w przeglądarce", async () => {
    mockQuickCounts();
    renderJobs();
    await waitFor(() => expect(quickCountsMock).toHaveBeenCalled());
    const params = quickCountsMock.mock.calls.at(-1)?.[0] as { overdue_to?: string } | undefined;
    expect(params?.overdue_to).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("bez odpowiedzi z licznikami nie pokazuje zera — brak liczby to nie „zero w bazie”", async () => {
    quickCountsMock.mockRejectedValue(new Error("boom"));
    renderJobs();

    const toggle = await screen.findByRole("button", { name: /Nikt nie pracuje/ });
    expect(within(toggle).queryByText("0")).not.toBeInTheDocument();
    expect(toggle).toBeEnabled();
  });
});

describe("JobsListV2 — stan requestu w wierszu", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
    mockJobsResponse([jobRow()]);
  });

  it("wiersz pokazuje jeden stan requestu — ten sam co pigułka nad listą", async () => {
    mockJobsResponse([
      jobRow({ id: 201, request_status: "searching", request_stage: "to_review" }),
      jobRow({ id: 202, request_status: "searching", request_stage: "client_silent" }),
    ]);
    renderJobs();
    const table = await screen.findByRole("table");
    await waitFor(() => expect(within(table).getByText("Do przejrzenia")).toBeInTheDocument());
    expect(within(table).getByText("Klient milczy")).toBeInTheDocument();
    expect(within(table).queryByText(/^Praca:/)).toBeNull();
  });

  it("strona listy ma dolny odstęp — ostatni wiersz przewija się nad maskotkę Jarvisa", async () => {
    // CSS: jsdom nie liczy nakładania; pilnujemy samego odstępu (audyt 24.09.2026).
    renderJobs();
    expect(await screen.findByTestId("jobs-list-page")).toHaveClass("pb-24");
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

  it("pigułka stanu wysyła `request_stage` i zapisuje go w adresie", async () => {
    const user = userEvent.setup();
    mockJobsResponse([jobRow()]);
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    const chips = within(screen.getByRole("group", { name: "Stan requestu" }));
    await user.click(chips.getByRole("button", { name: "Mamy championa" }));
    await user.click(chips.getByRole("button", { name: "Klient milczy" }));
    await waitFor(() =>
      expect(latestParams().request_stage).toEqual(["champion", "client_silent"]),
    );
    expect(window.location.search).toContain("stage=champion");
    expect(window.location.search).toContain("stage=client_silent");
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
    // „Moje” = moje NIEZAMKNIĘTE (decyzja 26.09.2026) — archiwum tylko we „Wszystkich”.
    expect(latestParams()).toMatchObject({ mine: true, open_only: true, sort: "attention" });
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

    await user.click(screen.getByRole("button", { name: /Wyczyść filtry/ }));
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

    await user.click(screen.getByRole("button", { name: /Wyczyść filtry/ }));
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
    useUiStore.setState({ jobsView: "list" });
    window.history.replaceState(null, "", "/jobs");
    navState.search = "";
  });

  const stageCounts = {
    request_stage: {
      incomplete: 80,
      to_review: 40,
      searching: 210,
      champion: 14,
      contract: 9,
      client_silent: 6,
    },
    request_stage_mine: {
      incomplete: 2,
      to_review: 1,
      searching: 7,
      champion: 1,
      contract: 0,
      client_silent: 0,
    },
  };

  it("pigułki stanu pokazują liczby zakresu: „Moje” — moje, „Otwarte” — rejestr", async () => {
    mockJobsResponse([jobRow()]);
    mockQuickCounts({ mine: 42, ...stageCounts });
    const user = userEvent.setup();
    renderJobs();
    const chips = within(await screen.findByRole("group", { name: "Stan requestu" }));
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
    expect(chips.getByRole("button", { name: /Klient milczy\s*6/ })).toBeInTheDocument();
    // Jeden rząd: bez osobnego „Praca:” i bez „Obsadzona”/„Zakończony”.
    expect(chips.queryByRole("button", { name: /Obsadzona|Zakończony|W pracy/ })).toBeNull();
  });

  it("bez liczników stanu (starszy backend) pigułki nie udają zera", async () => {
    mockJobsResponse([jobRow()]);
    mockQuickCounts();
    renderJobs();
    const chips = within(await screen.findByRole("group", { name: "Stan requestu" }));
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
      jobRow({ id: 1, title: "Zaległa", deadline: inDays(-3) }),
      jobRow({ id: 2, title: "Wkrótce", deadline: inDays(5) }),
      jobRow({ id: 3, title: "Daleko", deadline: inDays(30) }),
      jobRow({ id: 4, title: "Bez terminu", deadline: null }),
    ]);
    mockQuickCounts();
    renderJobs();
    await screen.findByText("Zaległa");
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

  it("„Wysłanych do klienta” (w „Więcej filtrów”) wysyła min_sent/max_sent i liczy się do „Wyczyść filtry (N)”", async () => {
    mockJobsResponse([jobRow()]);
    mockQuickCounts();
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: /Więcej filtrów/ }));
    await user.click(screen.getByRole("combobox", { name: "Filtr: Wysłanych do klienta" }));
    await user.click(await screen.findByRole("option", { name: "Co najmniej 3 osoby" }));
    await waitFor(() => expect(latestParams()).toMatchObject({ min_sent: 3 }));
    expect(latestParams().max_sent).toBeUndefined();
    expect(await screen.findByRole("button", { name: "Wyczyść filtry (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Więcej filtrów: wysłanych: co najmniej 3 osoby/ })).toBeInTheDocument();
    await waitFor(() => expect(window.location.search).toContain("sent=3"));

    await user.click(screen.getByRole("button", { name: "Wyczyść: Więcej filtrów" }));
    await waitFor(() => {
      expect(latestParams().min_sent).toBeUndefined();
      expect(latestParams().max_sent).toBeUndefined();
    });
  });

  it("Delivery Lead i zakres terminu z adresu idą do API (delivery_lead_id, deadline_from/to)", async () => {
    navState.search = "lead=5&lead=8&deadline=range&dl_from=2026-10-01&dl_to=2026-10-31";
    mockJobsResponse([jobRow()]);
    mockQuickCounts();
    const user = userEvent.setup();
    renderJobs();
    await waitFor(() => expect(jobsCalls()).toHaveLength(1));
    expect(latestParams()).toMatchObject({
      delivery_lead_id: [5, 8],
      deadline_from: "2026-10-01",
      deadline_to: "2026-10-31",
    });
    // Delivery Lead + termin = 2 przyciski z ustawionym filtrem.
    expect(screen.getByRole("button", { name: "Wyczyść filtry (2)" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Termin: 01\.10–31\.10/ }));
    expect(await screen.findByLabelText("Termin od")).toHaveValue("2026-10-01");
    expect(screen.getByLabelText("Termin do")).toHaveValue("2026-10-31");
    navState.search = "";
  });
});
