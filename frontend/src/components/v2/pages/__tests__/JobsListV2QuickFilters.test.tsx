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

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
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

vi.mock("@/components/v2/filters/MultiSelectFilter", () => ({
  MultiSelectFilter: () => null,
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
  JobReadinessDock: ({ jobId }: { jobId: number | null }) => (
    <div data-testid="mock-dock">dock:{String(jobId)}</div>
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

    await user.click(screen.getByText("Wyczyść"));
    await waitFor(() => {
      const params = latestParams();
      expect(params.recruitment_type).toBeUndefined();
      expect(params.open_only).toBeUndefined();
    });
  });
});

describe("JobsListV2 — „Brak ownera requestu” jako filtr (nie tylko badge)", () => {
  beforeEach(() => {
    getMock.mockReset();
    useUiStore.setState({ jobsView: "list" });
  });

  it("zawęża widoczne wiersze do tych bez tac_id, bez dodatkowego zapytania do API", async () => {
    mockJobsResponse([
      jobRow({ id: 1, title: "Ma ownera", tac_id: 7 }),
      jobRow({ id: 2, title: "Bez ownera", tac_id: null }),
    ]);
    const user = userEvent.setup();
    renderJobs();

    expect(await screen.findByText("Ma ownera")).toBeInTheDocument();
    expect(screen.getByText("Bez ownera")).toBeInTheDocument();
    const callsBefore = jobsCalls().length;

    // `getByRole("button", ...)`, NIE `getByText` — wiersz "Bez ownera" ma
    // WŁASNY badge "Brak ownera requestu" (status), więc sam tekst wychodzi
    // dwukrotnie: pigułka filtra w aside + badge w wierszu.
    await user.click(
      screen.getByRole("button", { name: /Brak ownera requestu/ }),
    );

    expect(screen.queryByText("Ma ownera")).not.toBeInTheDocument();
    expect(screen.getByText("Bez ownera")).toBeInTheDocument();
    // Filtr jest lokalny — żadne nowe żądanie do `/api/jobs` nie poszło.
    expect(jobsCalls().length).toBe(callsBefore);
  });

  it("liczy się na bieżącej stronie nawet gdy filtr jest wyłączony (licznik darmowy z już wczytanych danych)", async () => {
    mockJobsResponse([
      jobRow({ id: 1, title: "Ma ownera", tac_id: 7 }),
      jobRow({ id: 2, title: "Bez ownera A", tac_id: null }),
      jobRow({ id: 3, title: "Bez ownera B", tac_id: null }),
    ]);
    renderJobs();
    await screen.findByText("Ma ownera");

    const quickFilterButton = screen.getByRole("button", {
      name: /Brak ownera requestu/,
    });
    expect(within(quickFilterButton).getByText("2")).toBeInTheDocument();
  });

  it("gdy żaden wiersz tej strony nie pasuje, pokazuje komunikat zamiast udawać brak rekrutacji", async () => {
    mockJobsResponse([jobRow({ id: 1, title: "Ma ownera", tac_id: 7 })]);
    const user = userEvent.setup();
    renderJobs();
    await screen.findByText("Ma ownera");

    await user.click(
      screen.getByRole("button", { name: /Brak ownera requestu/ }),
    );

    expect(screen.queryByText("Ma ownera")).not.toBeInTheDocument();
    // "wyłącz filtr" jest WŁASNYM elementem (<button>) — bezpieczne dokładne
    // dopasowanie, niezależne od tego, jak JSX złamie resztę zdania na
    // granicy wiersza źródłowego.
    expect(
      await screen.findByRole("button", { name: "wyłącz filtr" }),
    ).toBeInTheDocument();
  });
});

describe("JobsListV2 — mini-lejek pipeline'u w wierszu", () => {
  beforeEach(() => {
    getMock.mockReset();
    useUiStore.setState({ jobsView: "list" });
  });

  it("z `stage_breakdown` pokazuje sumę sześciu grup (bez rejected/withdrawn)", async () => {
    mockJobsResponse([
      jobRow({
        stage_breakdown: { new: 3, screening: 2, hired: 1, rejected: 5 },
      }),
    ]);
    renderJobs();
    // 3 + 2 + 1 = 6, `rejected` poza sześcioma grupami.
    expect(await screen.findByText("6")).toBeInTheDocument();
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
    useUiStore.setState({ jobsView: "list" });
  });

  it("przekazuje id pierwszego wiersza do JobReadinessDock, gdy nic nie jest jawnie zaznaczone", async () => {
    mockJobsResponse([jobRow({ id: 42, title: "Pierwszy w kolejności" })]);
    renderJobs();
    await screen.findByText("Pierwszy w kolejności");
    expect(await screen.findByTestId("mock-dock")).toHaveTextContent("dock:42");
  });
});
