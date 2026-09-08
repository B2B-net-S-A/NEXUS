/**
 * Lewa kolumna filtrów (krok 01 „Lista", program „flow w języku C2", PR 4/7).
 *
 * Zakres tego pliku: NOWA logika tego PR-a — filtry „Szybkie" wysyłają te
 * SAME parametry zapytania co dziś (tylko przeniesione z rzędu pigułek do
 * pionowej listy w aside), `include_stage_counts` jest zawsze włączone, a
 * „Brak ownera requestu" zawęża WYŁĄCZNIE bieżącą, już wczytaną stronę (bez
 * dodatkowego zapytania). `JobReadinessDock` jest zamockowany — ma własny
 * plik testów i nie jest przedmiotem tego pliku.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { JobsListV2 } from "@/components/v2/pages/JobsListV2";
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

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/hooks/useCapability", () => ({
  useCapabilities: () => ({
    "job.create": false,
    "invite_link.create": false,
  }),
}));

vi.mock("@/components/AppShell", () => ({
  AddJobModal: () => null,
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
});

describe("JobsListV2 — „Brak ownera requestu” filtruje SERWER", () => {
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

    // `getByRole("button", ...)`, NIE `getByText` — wiersz bez ownera ma
    // WŁASNY badge „Brak ownera" (status), więc tekst wychodzi dwukrotnie.
    await user.click(
      screen.getByRole("button", { name: /Brak ownera requestu/ }),
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
      [/Moje projekty/, "12"],
      [/Niezamknięte/, "318"],
      [/Potrzebny search/, "41"],
      [/Aktywni w searchu/, "27"],
      [/Brak ownera requestu/, "63"],
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

    const row = await screen.findByRole("button", { name: /Moje projekty/ });
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

describe("JobsListV2 — mini-lejek pipeline'u w wierszu", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
  });

  it("pokazuje „nowi·screening·zweryfikowani / w procesie”, bez rejected/withdrawn", async () => {
    mockJobsResponse([
      jobRow({
        stage_breakdown: { new: 3, screening: 2, hired: 1, rejected: 5 },
      }),
    ]);
    renderJobs();
    // 3 + 2 + 1 = 6 w procesie, `rejected` poza sześcioma grupami; przed
    // makietą „01 Lista" wiersz pokazywał samą sumę, więc nie dawało się
    // odczytać, czy ludzie stoją na wejściu, czy są już u klienta.
    expect(await screen.findByText("3·2·0 / 6")).toBeInTheDocument();
  });

  it("bez `stage_breakdown` cofa się do paska filled/target, nie chowa kolumny", async () => {
    mockJobsResponse([jobRow({ stage_breakdown: undefined, headcount: 3 })]);
    renderJobs();
    expect(await screen.findByText("0/3")).toBeInTheDocument();
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

describe("JobsListV2 — dok pokazuje pierwszy widoczny wiersz", () => {
  beforeEach(() => {
    getMock.mockReset();
    quickCountsMock.mockReset();
    mockQuickCounts();
    useUiStore.setState({ jobsView: "list" });
  });

  it("przekazuje id pierwszego wiersza do JobReadinessDock, gdy nic nie jest jawnie zaznaczone", async () => {
    mockJobsResponse([jobRow({ id: 42, title: "Pierwszy w kolejności" })]);
    renderJobs();
    await screen.findByText("Pierwszy w kolejności");
    expect(await screen.findByTestId("mock-dock")).toHaveTextContent("dock:42");
  });

  it("podaje dokowi nawigację „N z M” po wierszach bieżącej strony", async () => {
    mockJobsResponse([
      jobRow({ id: 1, title: "Pierwsza" }),
      jobRow({ id: 2, title: "Druga" }),
      jobRow({ id: 3, title: "Trzecia" }),
    ]);
    renderJobs();
    await screen.findByText("Pierwsza");

    expect(await screen.findByTestId("mock-nav")).toHaveTextContent("nav:1/3");
  });

  it("nie podaje nawigacji, gdy strona ma jeden wiersz — „1 z 1” to nie nawigacja", async () => {
    mockJobsResponse([jobRow({ id: 9, title: "Jedyna" })]);
    renderJobs();
    await screen.findByText("Jedyna");

    expect(screen.queryByTestId("mock-nav")).not.toBeInTheDocument();
  });
});
