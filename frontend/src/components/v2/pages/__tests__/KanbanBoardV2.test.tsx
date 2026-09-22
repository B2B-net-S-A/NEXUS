/**
 * KanbanBoardV2 — testy powierzchni renderu i akcji tablicy.
 *
 * Drag-and-drop nie jest odpalalny w jsdom (repo-precedens: weryfikacja dnd
 * unit testami + realnym Chrome), więc ruchy wyzwalamy pigułkami doku:
 * - od 17.09.2026 żadna bramka nie blokuje przepływu — karta niesie odznaki
 *   („ponad budżet", „Uzupełnij screening"), a weto HM / czarna lista / NDA /
 *   konkurent to ostrzeżenie serwera z „Przenieś mimo to",
 * - ruch zbiorczy POMIJA z wyjaśnieniem karty z ostrzeżeniem (weto HM),
 * - okno stawki do klienta tylko dla `can_write_client_rate`.
 */

import * as React from "react";
import { cleanup as rtlCleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const kanban = vi.fn();
const post = vi.fn();
const get = vi.fn();
const move = vi.fn();
const toastError = vi.fn();
const toastSuccess = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
  candidatesApi: {
    removeFromRecruitment: vi.fn(),
    setRecruitmentClientRate: vi.fn(),
  },
  pipelineApi: {
    kanban: (...a: unknown[]) => kanban(...a),
    move: (...a: unknown[]) => move(...a),
  },
  pipelineTemplatesApi: {
    get: vi.fn(() =>
      Promise.resolve({ data: { stages: [], rejection_reasons: [] } }),
    ),
    list: vi.fn(() => Promise.resolve({ data: [] })),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showActionToast: vi.fn(),
    showSuccess: toastSuccess,
    showError: toastError,
  }),
}));

vi.mock("@/lib/celebrate", () => ({ celebrate: vi.fn() }));
// „Do przejrzenia": propozycje liczy własny hak (`useJobProposals`) — tu
// podstawiamy ich liczbę, żeby sprawdzić nagłówek kolumny.
const reviewTotal = { value: 0 };
vi.mock("@/components/v2/jobs/BoardReviewSection", async () => {
  const { useEffect } = await import("react");
  return {
    BoardReviewSection: ({ onTotalChange }: { onTotalChange?: (n: number | null) => void }) => {
      useEffect(() => {
        onTotalChange?.(reviewTotal.value);
      }, [onTotalChange]);
      return <div data-testid="board-review" />;
    },
  };
});

import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";
import { KANBAN_VIEW_MODE_STORAGE_KEY } from "@/lib/kanban-view-preferences";

// Domyślnie `nexus-ui` chowa puste kolumny (przegląd UX 17.09.2026). Te testy
// liczą kolumny szablonu, więc startują z pełną tablicą; testy ukrywania
// ustawiają flagę same.
beforeEach(() => {
  useUiStore.setState({ hideEmptyKanbanColumns: false } as never);
});

beforeAll(() => {
  // Radix Select uses pointer-capture APIs that jsdom does not implement.
  if (!HTMLElement.prototype.hasPointerCapture) {
    HTMLElement.prototype.hasPointerCapture = () => false;
    HTMLElement.prototype.setPointerCapture = () => {};
    HTMLElement.prototype.releasePointerCapture = () => {};
  }
});

// Domyślne odpowiedzi — `mockResolvedValue` w teście nie może przeciekać do
// kolejnych opisów (vi.clearAllMocks nie zdejmuje implementacji).
beforeEach(() => {
  get.mockImplementation(() =>
    Promise.resolve({ data: { effective_budget_hourly: null, pipeline_template_id: null } }),
  );
  move.mockImplementation(() => Promise.resolve({ data: {} }));
});

/** Kolumna „Zweryfikowany" z kartami ze stawką godzinową w PLN. */
function rateColumns(
  cards: Array<{
    id: number;
    candidate_id: number;
    name: string;
    lastname: string;
    rate: number;
    extra?: Record<string, unknown>;
  }>,
) {
  return [
    {
      stage: "verified",
      name: "Zweryfikowany",
      category: "internal",
      stage_def_id: null,
      count: cards.length,
      items: cards.map((c) => ({
        id: c.id,
        candidate_id: c.candidate_id,
        name: c.name,
        lastname: c.lastname,
        stage: "verified",
        days_in_stage: 1,
        verification_status: "active",
        expected_rate_value: c.rate,
        expected_rate_unit: "hourly",
        expected_rate_currency: "PLN",
        ...c.extra,
      })),
    },
  ] as never;
}

/** Karta sprzed 17.09.2026 z `verification_status: "pending"` — ma wyglądać jak zwykła. */
function pendingColumns() {
  return [
    {
      stage: "verified",
      name: "Zweryfikowany",
      category: "internal",
      stage_def_id: null,
      count: 1,
      items: [
        {
          id: 777,
          candidate_id: 5,
          name: "Anna",
          lastname: "Kowalska",
          stage: "verified",
          days_in_stage: 1,
          verification_status: "pending",
          expected_rate_value: 150,
          expected_rate_unit: "hourly",
          expected_rate_currency: "PLN",
          budget_max_at_move: 20000,
        },
      ],
    },
  ] as never;
}

function focusColumns() {
  const names = [
    "Nowy",
    "Screening",
    "Zweryfikowany",
    "Przedstawiony",
    "Rozmowa HR",
    "Rozmowa techniczna",
    "Rozmowa z klientem",
    "Feedback",
    "Oferta",
    "Negocjacje",
    "Akceptacja",
    "Onboarding",
    "Wycofany",
    "Odrzucony",
    "Zatrudniony",
  ];

  return names.map((name, index) => ({
    // Custom stages deliberately share the legacy enum. Stable navigation and
    // DnD identity must come from stage_def_id, not from this fallback value.
    stage: "new",
    name,
    category: index >= 12 ? "terminal" : "internal",
    stage_def_id: 201 + index,
    count: index === 1 ? 4 : 0,
    items: [],
    terminal_type:
      index === 12
        ? "withdrawn"
        : index === 13
          ? "rejected"
          : index === 14
            ? "hired"
            : null,
  })) as never;
}

function overviewColumns() {
  const columns = focusColumns() as unknown as Array<Record<string, unknown>>;
  columns[0] = {
    ...columns[0],
    count: 1,
    items: [
      {
        id: 901,
        candidate_id: 90,
        name: "Aleksandra",
        lastname: "Nowakowska",
        stage: "new",
        days_in_stage: 5,
        rating: 4.5,
        verification_status: null,
        added_to_job_by_name: "Ewa Nowak",
        added_to_job_at: "2026-08-20T08:15:00Z",
      },
    ],
  };
  return columns as never;
}

// 17 kolumn: próg pełnego układu to 16 (15 „Default B2B" + „Ogłoszenia").
function overflowColumns() {
  const columns = focusColumns() as unknown as Array<Record<string, unknown>>;
  return [
    ...columns,
    {
      stage: "new",
      name: "Do decyzji",
      category: "internal",
      stage_def_id: 216,
      count: 0,
      items: [],
      terminal_type: null,
    },
    {
      stage: "new",
      name: "Archiwum",
      category: "terminal",
      stage_def_id: 217,
      count: 0,
      items: [],
      terminal_type: "withdrawn",
    },
  ] as never;
}

function renderBoard(
  columns = pendingColumns(),
  scoreMap?: Map<number, number>,
  readOnly = false,
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <KanbanBoardV2
          columns={columns}
          jobId={10}
          scoreMap={scoreMap}
          readOnly={readOnly}
        />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

describe("KanbanBoardV2 — karta: odznaki zamiast bramek (17.09.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  it("stawka ponad budżet godzinowy rekrutacji daje odznakę „ponad budżet”, w budżecie — nie", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    useUiStore.setState({ density: "cozy" } as never);
    get.mockResolvedValue({
      data: { effective_budget_hourly: 100, pipeline_template_id: null },
    });

    renderBoard(
      rateColumns([
        { id: 781, candidate_id: 11, name: "Adam", lastname: "Drogi", rate: 150 },
        { id: 782, candidate_id: 12, name: "Beata", lastname: "Tania", rate: 80 },
      ]),
    );

    const expensive = (
      await screen.findByRole("link", { name: "Adam Drogi" })
    ).closest("[data-kanban-card]") as HTMLElement;
    await waitFor(() =>
      expect(within(expensive).getByText("ponad budżet")).toBeInTheDocument(),
    );
    const cheap = screen
      .getByRole("link", { name: "Beata Tania" })
      .closest("[data-kanban-card]") as HTMLElement;
    expect(within(cheap).queryByText("ponad budżet")).toBeNull();
  });

  it("stara karta „pending” renderuje się jak zwykła — bez „Pending” i bez akceptacji", async () => {
    useAuthStore.setState({
      user: { role: "admin", roles: ["admin"] } as never,
    });
    useUiStore.setState({ density: "compact" } as never);

    renderBoard();

    expect(await screen.findByRole("link", { name: "Anna Kowalska" })).toBeTruthy();
    expect(screen.queryByText(/Pending/)).toBeNull();
    expect(screen.queryByText(/Oczekuje/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Akceptuj/ })).toBeNull();
    expect(screen.queryByTitle("Akceptuj weryfikację")).toBeNull();
    expect(screen.queryByTitle("Odrzuć weryfikację")).toBeNull();
  });

  it("pokazuje wynik dopasowania na karcie", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    useUiStore.setState({ density: "compact" } as never);

    renderBoard(pendingColumns(), new Map([[5, 77]]));

    expect(
      await screen.findByLabelText("Dopasowanie AI: 77 na 100"),
    ).toBeTruthy();
  });

  it("karta na „Zweryfikowany” bez zapisanego screeningu pokazuje „Uzupełnij screening”", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    useUiStore.setState({ density: "cozy" } as never);

    renderBoard(
      rateColumns([
        {
          id: 783,
          candidate_id: 13,
          name: "Celina",
          lastname: "Arkusz",
          rate: 90,
          extra: { screening_done: false },
        },
        {
          id: 784,
          candidate_id: 14,
          name: "Dawid",
          lastname: "Gotowy",
          rate: 90,
          extra: { screening_done: true },
        },
      ]),
    );

    expect(
      await screen.findByRole("button", {
        name: "Uzupełnij screening dla Celina Arkusz",
      }),
    ).toHaveTextContent("Uzupełnij screening");
    const done = screen.getByRole("button", {
      name: "Screening Championa dla Dawid Gotowy",
    });
    expect(done).toHaveTextContent("Screening");
    expect(done).not.toHaveTextContent("Uzupełnij");
  });

  it("wiersz właściciela mówi o braku danych, zamiast udawać nazwisko", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    useUiStore.setState({ density: "cozy" } as never);

    renderBoard();
    const candidate = await screen.findByRole("link", { name: "Anna Kowalska" });
    // Fala 3: wiersz właściciela to awatar + imię, a brak danych mówi o sobie
    // wprost zamiast udawać nazwisko.
    expect(screen.getByText("Brak danych")).toBeTruthy();
    const descriptionId = candidate.getAttribute("aria-describedby");
    expect(descriptionId).toBeTruthy();
    expect(document.querySelector(`#${descriptionId}`)).toHaveTextContent(
      "Brak danych o osobie dodającej.",
    );
  });

  it("w trybie tylko do odczytu ukrywa mutacje, ale zachowuje eksport CV", async () => {
    useAuthStore.setState({
      user: { role: "admin", roles: ["admin"] } as never,
    });
    useUiStore.setState({ density: "compact" } as never);

    renderBoard(pendingColumns(), undefined, true);

    expect(await screen.findByRole("link", { name: "Anna Kowalska" })).toBeTruthy();
    const checkbox = screen.getByRole("checkbox", { name: "Zaznacz Anna Kowalska" });
    expect(checkbox).toBeInTheDocument();
    await userEvent.click(checkbox);
    expect(screen.getByRole("button", { name: /CV \(ZIP\)/ })).toBeInTheDocument();
    // Pasek akcji zbiorczych: bez prawa zapisu zostaje sam eksport — ani
    // przenoszenia, ani skrótu „Odrzuć".
    expect(screen.queryByText(/Przenieś na etap/)).toBeNull();
    expect(screen.queryByRole("button", { name: /^Odrzuć$/ })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Usuń Anna Kowalska z rekrutacji" }),
    ).toBeNull();
  });
});

/**
 * Ruch z doku = `moveBlockedReason` (od 17.09.2026 blokuje wyłącznie brak
 * prawa zapisu) + ostrzeżenia serwera. Weto HM, czarna lista, NDA i konkurent
 * kończą się 409 `ELIGIBILITY_WARNING`, a tablica pyta „Przenieś mimo to"
 * i powtarza TEN SAM ruch z `acknowledge_eligibility: true`.
 */
describe("KanbanBoardV2 — ruch z doku i ostrzeżenia serwera", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
    move.mockResolvedValue({ data: {} });
    useAuthStore.setState({
      user: { role: "admin", roles: ["admin"] } as never,
    });
    useUiStore.setState({ density: "cozy" } as never);
  });

  function gateColumns(extra: Record<string, unknown>) {
    return [
      {
        stage: "screening",
        name: "Screening",
        category: "internal",
        stage_def_id: 301,
        count: 1,
        items: [
          {
            id: 801,
            candidate_id: 61,
            name: "Jan",
            lastname: "Bramka",
            stage: "screening",
            days_in_stage: 2,
            verification_status: "active",
            ...extra,
          },
        ],
      },
      {
        stage: "verified",
        name: "Zweryfikowany",
        category: "internal",
        stage_def_id: 302,
        count: 0,
        items: [],
      },
      {
        stage: "cv_sent",
        name: "CV Wysłane",
        category: "internal",
        stage_def_id: 303,
        count: 0,
        items: [],
      },
      {
        stage: "rejected",
        name: "Odrzucony",
        category: "terminal",
        stage_def_id: 304,
        count: 0,
        items: [],
        terminal_type: "rejected",
      },
    ] as never;
  }

  async function openDock() {
    const card = await waitFor(() => {
      const el = document.querySelector("[data-kanban-card]");
      expect(el).toBeTruthy();
      return el as HTMLElement;
    });
    fireEvent.click(card);
    return screen.findByRole("complementary", { name: "Karta kandydata" });
  }

  async function openDockStageMenu() {
    await openDock();
    await userEvent.click(screen.getByRole("button", { name: "Inny etap…" }));
    return screen.findByRole("menu");
  }

  const VETO = {
    hm_veto: {
      hiring_manager_contact_id: 5,
      source_job_id: 2,
      rejected_at: "2026-01-01",
      rejection_reason_name: "Brak bankowości",
    },
  };

  function moveCalls() {
    return post.mock.calls.filter((c) => c[0] === "/api/pipeline/move");
  }

  function eligibilityWarning409() {
    return {
      response: {
        status: 409,
        data: {
          detail: {
            code: "ELIGIBILITY_WARNING",
            reason_code: "hm_veto",
            reason: "Hiring manager odrzucił już tego kandydata — Brak bankowości.",
            message: "Hiring manager odrzucił już tego kandydata — Brak bankowości.",
            can_acknowledge: true,
          },
        },
      },
    };
  }

  it("weto HM NIE wyszarza w doku „CV Wysłane” ani żadnego innego etapu", async () => {
    renderBoard(gateColumns(VETO));
    const menu = await openDockStageMenu();

    for (const name of ["Zweryfikowany", "CV wysłane", "Odrzucony"]) {
      const option = within(menu).getByRole("menuitem", { name });
      expect(option).not.toHaveAttribute("aria-disabled", "true");
      expect(option.getAttribute("title")).toBeNull();
    }
    // Menu trzeba zamknąć, żeby przycisk doku pod nim był osiągalny.
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: /Odrzuć z powodem/ })).not.toBeDisabled();
  });

  /** Fragment „Default B2B": po „Wysłać do Cpro" stoją „CV Wysłane",
   *  „Preparation Meeting" i „Interview Klient". */
  function vetoRouteColumns(extra: Record<string, unknown>) {
    return [
      {
        stage: "new",
        name: "Wysłać do Cpro",
        category: "internal",
        stage_def_id: 401,
        count: 1,
        items: [
          {
            id: 811,
            candidate_id: 71,
            name: "Ewa",
            lastname: "Objazd",
            stage: "new",
            days_in_stage: 1,
            verification_status: "active",
            process_state_version: 3,
            ...extra,
          },
        ],
      },
      { stage: "cv_sent", name: "CV Wysłane", category: "internal", stage_def_id: 402, count: 0, items: [] },
      { stage: "new", name: "Preparation Meeting", category: "external", stage_def_id: 403, count: 0, items: [] },
      { stage: "client_interview", name: "Interview Klient", category: "external", stage_def_id: 404, count: 0, items: [] },
      {
        stage: "rejected",
        name: "Odrzucony",
        category: "terminal",
        stage_def_id: 405,
        count: 0,
        items: [],
        terminal_type: "rejected",
      },
    ] as never;
  }

  it("weto HM na drodze naprzód: główna akcja doku proponuje następny etap, aktywny", async () => {
    renderBoard(vetoRouteColumns(VETO));
    await openDock();

    const forward = screen.getByRole("button", { name: /Przenieś na etap: CV wysłane/ });
    expect(forward).not.toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /Przenieś na etap: Preparation Meeting/ }),
    ).toBeNull();
  });

  it("karta bez weta dostaje zwykłą akcję naprzód na „CV Wysłane”", async () => {
    renderBoard(vetoRouteColumns({}));
    await openDock();

    expect(
      screen.getByRole("button", { name: /Przenieś na etap: CV wysłane/ }),
    ).not.toBeDisabled();
  });

  it("409 ELIGIBILITY_WARNING otwiera okno z powodem, a „Przenieś mimo to” powtarza ruch z potwierdzeniem", async () => {
    post
      .mockRejectedValueOnce(eligibilityWarning409())
      .mockResolvedValueOnce({ data: { id: 812, process_state_version: 4 } });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={vetoRouteColumns(VETO)} jobId={10} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Rozmowa u klienta" }));

    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Ostrzeżenie przed przeniesieniem"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Hiring manager odrzucił już tego kandydata — Brak bankowości.",
      ),
    ).toBeInTheDocument();
    expect(moveCalls()).toHaveLength(1);
    expect(moveCalls()[0][1]).toMatchObject({
      candidate_id: 71,
      stage_def_id: 404,
      acknowledge_eligibility: undefined,
    });

    fireEvent.click(within(dialog).getByRole("button", { name: "Przenieś mimo to" }));

    await waitFor(() => expect(moveCalls()).toHaveLength(2));
    expect(moveCalls()[1][1]).toMatchObject({
      candidate_id: 71,
      job_id: 10,
      stage: "client_interview",
      stage_def_id: 404,
      acknowledge_eligibility: true,
    });
    await waitFor(() =>
      expect(screen.queryByText("Ostrzeżenie przed przeniesieniem")).toBeNull(),
    );
    // Udany ruch odświeża zapytanie strony pod oboma kluczami.
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", "10"] }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", 10] });
  });

  it("„Anuluj” w oknie ostrzeżenia nie wysyła drugiego ruchu i dociąga prawdę serwera", async () => {
    post.mockRejectedValueOnce(eligibilityWarning409());
    renderBoard(vetoRouteColumns(VETO));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Rozmowa u klienta" }));

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));

    await waitFor(() =>
      expect(screen.queryByText("Ostrzeżenie przed przeniesieniem")).toBeNull(),
    );
    await waitFor(() => expect(kanban).toHaveBeenCalledWith(10));
    await new Promise((r) => setTimeout(r, 50));
    expect(moveCalls()).toHaveLength(1);
  });

  it("ruch zbiorczy pomija kartę z wetem HM i mówi dlaczego — bez liczenia jej jako nieudanej", async () => {
    renderBoard(gateColumns(VETO));
    await userEvent.click(
      await screen.findByRole("checkbox", { name: "Zaznacz Jan Bramka" }),
    );
    const bulkTrigger = screen
      .getAllByRole("combobox")
      .find((el) => el.textContent?.includes("Przenieś na etap"));
    await userEvent.click(bulkTrigger as Element);
    await userEvent.click(await screen.findByRole("option", { name: /CV wysłane/ }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(expect.stringContaining("Pominięto 1")),
    );
    const message = toastError.mock.calls[0][0] as string;
    expect(message).toContain("Jan Bramka");
    expect(message).toContain("Brak bankowości");
    expect(message).not.toMatch(/Nie udało się przenieść/);
    expect(moveCalls()).toHaveLength(0);
  });

  it("„CV Wysłane” bez prawa zapisu stawki do klienta przenosi kartę bez pytania o stawkę", async () => {
    get.mockImplementation(() =>
      Promise.resolve({
        data: {
          effective_budget_hourly: null,
          pipeline_template_id: null,
          can_write_client_rate: false,
        },
      }),
    );
    renderBoard(gateColumns({}));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "CV wysłane" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({ candidate_id: 61, stage: "cv_sent" }),
      ),
    );
    expect(screen.queryByText(/stawk[aęi] do klienta/i)).toBeNull();
  });

  it("„CV Wysłane” z prawem zapisu stawki do klienta najpierw pyta o stawkę", async () => {
    get.mockImplementation(() =>
      Promise.resolve({
        data: {
          effective_budget_hourly: null,
          pipeline_template_id: null,
          can_write_client_rate: true,
        },
      }),
    );
    renderBoard(gateColumns({}));
    // Odpowiedź `GET /api/jobs/{id}` musi dojść, zanim klikniemy.
    await waitFor(() => expect(get).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "CV wysłane" }));

    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(moveCalls()).toHaveLength(0);
  });

  it("okno „Zweryfikowany” podpowiada stawkę z profilu, a „Pomiń stawkę” przesuwa bez stawki", async () => {
    renderBoard(gateColumns({ candidate_expected_rate_hourly: "120.00" }));
    const menu = await openDockStageMenu();
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Zweryfikowany" }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Kwota")).toHaveValue(120);
    expect(within(dialog).getByRole("button", { name: "Przesuń" })).not.toBeDisabled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Pomiń stawkę" }));

    await waitFor(() => expect(move).toHaveBeenCalledTimes(1));
    const body = move.mock.calls[0][0] as Record<string, unknown>;
    expect(body).toMatchObject({
      candidate_id: 61,
      job_id: 10,
      stage: "verified",
      stage_def_id: 302,
    });
    expect(body).not.toHaveProperty("expected_rate_value");
    expect(body).not.toHaveProperty("expected_rate_unit");
  });
});

describe("KanbanBoardV2 — focus na etapie", () => {
  beforeEach(() => {
    // Preferencja widoku jest globalna (per użytkownik, nie per rekrutacja),
    // więc test, który kliknie „Kolumny", zapisałby ją dla następnych.
    window.localStorage.clear();
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  it("pokazuje pełny pipeline w kolumnach o podłodze 200 px", async () => {
    const { container } = renderBoard(
      overviewColumns(),
      new Map([[90, 82]]),
    );

    // 15 kolumn otwiera się domyślnie w widoku przeglądowym (decyzja Artura
    // 20.09.2026) — ten test opisuje widok KOLUMNOWY, więc przełączamy jawnie.
    await userEvent.click(await screen.findByRole("button", { name: "Widok kolumnowy" }));
    const board = await screen.findByTestId("pipeline-board");
    expect(board).toHaveAttribute("data-desktop-layout", "full-pipeline");
    expect(board).toHaveClass("overflow-auto", "xl:pointer-fine:gap-1");
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(12);
    for (const column of container.querySelectorAll("[data-colid]")) {
      expect(column).toHaveClass(
        "xl:pointer-fine:w-auto",
        "xl:pointer-fine:min-w-[12.5rem]",
        "xl:pointer-fine:basis-[12.5rem]",
        "xl:pointer-fine:grow",
      );
      // Dawny tryb kafelkowy ściskał kolumnę do zera.
      expect(column).not.toHaveClass("xl:pointer-fine:min-w-0");
    }

    expect(container.querySelector("[data-mobile-stage-navigation]")).toHaveClass(
      "xl:pointer-fine:hidden",
    );
    expect(screen.getByTitle("Rozmowa techniczna")).toBeTruthy();
    expect(
      screen.getByRole("group", { name: "Nowi, liczba kandydatów: 1" }),
    ).toBeTruthy();

    const candidate = await screen.findByRole("link", {
      name: "Aleksandra Nowakowska",
    });
    const card = candidate.closest("[data-kanban-card]");
    expect(card).not.toHaveClass("xl:pointer-fine:pt-6");
    expect(card).toHaveAttribute("data-candidate-id", "90");
    expect(card?.getAttribute("title")).toContain("Aleksandra Nowakowska");
    expect(card?.getAttribute("title")).toContain(
      "Dodano do rekrutacji przez: Ewa Nowak",
    );
    expect(screen.queryByTestId("overview-match-score-90")).toBeNull();
    const descriptionId = candidate.getAttribute("aria-describedby");
    expect(descriptionId).toBeTruthy();
    expect(container.querySelector(`#${descriptionId}`)).toHaveTextContent(
      "Dopasowanie AI: 82 na 100. Ocena: 4.5. W etapie od 5 dni. Dodano do rekrutacji przez: Ewa Nowak",
    );
    const checkbox = screen.getByRole("checkbox", {
      name: "Zaznacz Aleksandra Nowakowska",
    });
    expect(checkbox).toHaveClass("h-6", "w-6", "before:inset-1");
    expect(
      screen.getByRole("button", {
        name: "Usuń Aleksandra Nowakowska z rekrutacji",
      }),
    ).toBeTruthy();
  });

  it("przy czterech etapach zostawia pełną kartę, nie kafelek", async () => {
    const columns = (
      overviewColumns() as unknown as Array<Record<string, unknown>>
    ).slice(0, 4) as never;
    renderBoard(columns);

    const board = await screen.findByTestId("pipeline-board");
    expect(board).toHaveAttribute("data-desktop-layout", "full-pipeline");
    const candidate = await screen.findByRole("link", {
      name: "Aleksandra Nowakowska",
    });
    expect(candidate.closest("[data-kanban-card]")).not.toHaveClass(
      "xl:pointer-fine:pt-6",
    );
    expect(screen.queryByTestId("overview-match-score-90")).toBeNull();
    // Pełna karta niesie wiersz „co dalej" (5 dni na etapie wejściowym).
    expect(screen.getByText("Umów screening")).toBeTruthy();
    const descriptionId = candidate.getAttribute("aria-describedby");
    expect(descriptionId).toBeTruthy();
    expect(document.querySelector(`#${descriptionId}`)).toHaveTextContent(
      "Następny krok: Umów screening.",
    );
  });

  it("powyżej dziesięciu kolumn karta startuje jako kafelek, a „Kolumny” ją rozwijają", async () => {
    renderBoard(overviewColumns(), new Map([[90, 82]]));

    await screen.findByTestId("pipeline-board");
    const candidate = await screen.findByRole("link", {
      name: "Aleksandra Nowakowska",
    });
    // Domyślnie kafelek: karta ściśnięta, wynik jako odznaka zamiast pierścienia.
    expect(candidate.closest("[data-kanban-card]")).toHaveClass(
      "xl:pointer-fine:pt-6",
    );
    expect(screen.getByTestId("overview-match-score-90")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Widok kolumnowy" }));

    expect(candidate.closest("[data-kanban-card]")).not.toHaveClass(
      "xl:pointer-fine:pt-6",
    );
    expect(screen.queryByTestId("overview-match-score-90")).toBeNull();
    expect(screen.getByText("Umów screening")).toBeTruthy();
  });

  it("zachowuje scroll i navigator dla pipeline dłuższego niż 16 etapów", async () => {
    const { container } = renderBoard(overflowColumns());

    const board = await screen.findByTestId("pipeline-board");
    expect(board).toHaveAttribute("data-desktop-layout", "scroll");
    expect(board).not.toHaveClass("xl:pointer-fine:gap-1");
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(13);
    expect(container.querySelector("[data-colid]")).not.toHaveClass(
      "xl:pointer-fine:min-w-0",
    );
    expect(container.querySelector("[data-mobile-stage-navigation]")).not.toHaveClass(
      "xl:pointer-fine:hidden",
    );
  });

  it("pokazuje wszystkie 15 etapów i nie odmontowuje Droppable po zmianie fokusu", async () => {
    const scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView");
    const { container } = renderBoard(focusColumns());

    const picker = await screen.findByRole("combobox", {
      name: "Screening, etap 2 z 12",
    });
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(12);
    expect(container.querySelector('[data-colid="def:201"]')).toBeTruthy();
    expect(container.querySelector('[data-colid="def:202"]')).toBeTruthy();
    expect(screen.getByText("4 w procesie")).toBeTruthy();

    await userEvent.click(picker);
    expect(await screen.findAllByRole("option")).toHaveLength(12);
    await userEvent.click(
      await screen.findByRole("option", {
        name: /12\. Zatrudniony.*liczba kandydatów: 0/,
      }),
    );

    expect(
      await screen.findByRole("combobox", {
        name: "Zatrudniony, etap 12 z 12",
      }),
    ).toBeTruthy();
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(12);
    const target = container.querySelector<HTMLElement>('[data-colid="def:215"]');
    expect(target).toBeTruthy();
    expect(scrollIntoView.mock.instances.at(-1)).toBe(target);
    expect(scrollIntoView).toHaveBeenLastCalledWith({
      behavior: "smooth",
      inline: "center",
      block: "nearest",
    });
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Następny etap" })).toBeDisabled();
    scrollIntoView.mockRestore();
  });

  it("zmienia gęstość bez zmiany etapu ani odmontowania kolumn", async () => {
    useUiStore.setState({ density: "cozy" } as never);
    const { container } = renderBoard(focusColumns());

    const density = await screen.findByRole("button", {
      name: "Gęstość: cozy",
    });
    await userEvent.click(density);

    expect(
      screen.getByRole("button", { name: "Gęstość: kompaktowa" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("combobox", { name: "Screening, etap 2 z 12" }),
    ).toBeTruthy();
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(12);
    expect(post).not.toHaveBeenCalled();
  });

  it("nawiguje strzałkami i blokuje poprzedni etap na początku", async () => {
    renderBoard(focusColumns());

    await userEvent.click(
      await screen.findByRole("combobox", {
        name: "Screening, etap 2 z 12",
      }),
    );
    await userEvent.click(
      await screen.findByRole("option", {
        name: /1\. Nowy.*liczba kandydatów: 0/,
      }),
    );

    expect(screen.getByRole("button", { name: "Poprzedni etap" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Następny etap" }));
    expect(
      await screen.findByRole("combobox", {
        name: "Screening, etap 2 z 12",
      }),
    ).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });
});

// ── Kubełek „poza szablonem" ────────────────────────────────────────────────
//
// Karta, której etap nie ma kolumny w szablonie, znikała z tablicy bez śladu
// (1 633 karty na produkcji, pomiar 2026-09-02). Backend zwraca je teraz
// osobnym polem `off_template`. Te testy pilnują dwóch rzeczy naraz: że kubełek
// jest widoczny ORAZ że nie da się do niego nic przenieść.

function offTemplateFixture(count = 2) {
  return {
    name: "Poza szablonem",
    count,
    missing_stage_labels: ["Interview Wewnętrzny"],
    items: Array.from({ length: count }, (_, i) => ({
      id: 9000 + i,
      candidate_id: 500 + i,
      name: "Zofia",
      lastname: `Sierota${i}`,
      stage: "interview",
      days_in_stage: 7,
    })),
  } as never;
}

function renderWithBucket(
  columns = focusColumns(),
  offTemplate: unknown = offTemplateFixture(),
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <KanbanBoardV2
          columns={columns}
          jobId={10}
          offTemplate={offTemplate as never}
        />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("KanbanBoardV2 — karty poza szablonem", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    useAuthStore.setState({ user: { id: 1, role: "admin" } } as never);
    useUiStore.setState({ density: "cozy" } as never);
  });

  it("renderuje kubełek z kartami zamiast je gubić", async () => {
    const { container } = renderWithBucket();

    await screen.findByTestId("pipeline-board");
    const bucket = container.querySelector(
      '[data-colid="stage:__off_template__"]',
    );
    expect(bucket).toBeTruthy();
    expect(screen.getByText("Zofia Sierota0")).toBeTruthy();
  });

  it("nie zmienia układu desktopowego ani licznika „W procesie”", async () => {
    renderWithBucket();

    const board = await screen.findByTestId("pipeline-board");
    // 15 kolumn szablonu + kubełek — próg NIE może przeskoczyć na "scroll",
    // inaczej 1 009 rekrutacji dostałoby inny layout w nagrodę za bugfix.
    expect(board).toHaveAttribute("data-desktop-layout", "full-pipeline");
    // Kubełek nie dolicza się do sumy pipeline'u (to nie jest etap procesu).
    expect(screen.getByText("4 w procesie")).toBeTruthy();
  });

  it("nie oferuje kubełka jako celu przeniesienia zbiorczego", async () => {
    const { container } = renderWithBucket();
    await screen.findByTestId("pipeline-board");

    await userEvent.click(
      screen.getByRole("checkbox", { name: "Zaznacz Zofia Sierota0" }),
    );
    const bulkTrigger = screen
      .getAllByRole("combobox")
      .find((el) => el.textContent?.includes("Przenieś na etap"));
    await userEvent.click(bulkTrigger as Element);

    const options = await screen.findAllByRole("option");
    // 12 kolumn Tablicy + 2 zamknięci, bez „Zatrudniony" — hired oznacza się
    // pojedynczo.
    expect(options).toHaveLength(13);
    expect(options.some((o) => o.textContent?.includes("Zatrudniony"))).toBe(false);
    expect(
      options.some((o) => o.textContent?.includes("Poza szablonem")),
    ).toBe(false);
  });

  it("nie oferuje kubełka w nawigatorze etapów", async () => {
    renderWithBucket();

    expect(
      await screen.findByRole("combobox", { name: /etap 2 z 12/ }),
    ).toBeTruthy();
  });

  it("blokuje upuszczenie w kubełku, ale nie w kolumnie szablonu", async () => {
    const { container } = renderWithBucket();
    await screen.findByTestId("pipeline-board");

    // Wiążemy się z TĄ SAMĄ wartością, którą dostaje `isDropDisabled` —
    // DnD nie jest odpalalne w jsdom, więc kopia flagi nic by nie dowiodła.
    expect(
      container.querySelector('[data-colid="stage:__off_template__"]'),
    ).toHaveAttribute("data-drop-disabled", "true");
    expect(
      container.querySelector('[data-colid="def:201"]'),
    ).toHaveAttribute("data-drop-disabled", "false");
  });

  it("baner nazywa brakujący etap i prowadzi do szablonów", async () => {
    renderWithBucket();
    await screen.findByTestId("pipeline-board");

    expect(screen.getByText(/Interview Wewnętrzny/)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Otwórz szablony" }),
    ).toHaveAttribute("href", "/settings/pipeline-templates");
  });

  it("zdrowa tablica nie dostaje ani kubełka, ani banera", async () => {
    const { container } = renderWithBucket(focusColumns(), null);
    await screen.findByTestId("pipeline-board");

    expect(
      container.querySelector('[data-colid="stage:__off_template__"]'),
    ).toBeNull();
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(12);
    expect(screen.queryByRole("link", { name: "Otwórz szablony" })).toBeNull();
  });
});

// ── Fala 3: grupy etapów, zwinięte grupy, SLA na kolumnie, „co dalej" ───────
//
// Szablon „Default B2B" z produkcji — ZMAPOWANY na legacy enumy (w odróżnieniu
// od `focusColumns()`), bo dopiero wtedy w ogóle powstają grupy etapów.

function defaultB2BColumns() {
  const spec: Array<[string, string, string, number]> = [
    ["new", "Nowi / Analiza CV", "internal", 2],
    ["screening", "Screening", "internal", 1],
    ["verified", "Zweryfikowany", "internal", 0],
    ["new", "Przepuszczony przez DZ", "internal", 0],
    ["new", "Wysłać do Cpro", "internal", 0],
    ["cv_sent", "CV Wysłane", "internal", 0],
    ["new", "Preparation Meeting", "external", 0],
    ["client_interview", "Interview Klient", "external", 0],
    ["acceptance", "Akceptacja", "external", 0],
    ["new", "Umowa wysłana", "external", 0],
    ["new", "Umowa podpisana", "external", 0],
    ["new", "Zatrudniony", "terminal", 0],
    ["onboarding", "Onboarding", "external", 0],
    ["new", "Odrzucony", "terminal", 1],
    ["new", "Wycofany", "terminal", 0],
  ];
  return spec.map(([stage, name, category, count], index) => ({
    stage,
    name,
    category,
    stage_def_id: 300 + index,
    count,
    terminal_type:
      name === "Zatrudniony"
        ? "hired"
        : name === "Odrzucony"
          ? "rejected"
          : name === "Wycofany"
            ? "withdrawn"
            : null,
    items: Array.from({ length: count }, (_, i) => ({
      id: 1000 + index * 100 + i,
      candidate_id: 2000 + index * 100 + i,
      stage,
      name: "Kandydat",
      lastname: `${name.slice(0, 6)}${i}`,
      // Dwa dni na etapie → „Umów screening"; dziewięć → zaległość.
      days_in_stage: i === 0 ? 2 : 9,
      added_to_job_by_name: "Katarzyna Nowak",
    })),
  })) as never;
}

describe("KanbanBoardV2 — fala 3: grupy etapów i karta z następną akcją", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    useAuthStore.setState({ user: { id: 1, role: "admin" } } as never);
    useUiStore.setState({ density: "cozy", hideEmptyKanbanColumns: false } as never);
  });

  it("filtry stoją w jednym pasku nad tablicą — bez lewej kolumny etapów", async () => {
    renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    const bar = screen.getByRole("toolbar", { name: "Filtry tablicy" });
    expect(within(bar).getByRole("button", { name: /^Mój ruch/ })).toBeTruthy();
    expect(within(bar).getByRole("textbox", { name: "Filtruj po nazwisku" })).toBeTruthy();
    // Lista etapów z dawnej kolumny zniknęła — fokus kolumny daje nawigator.
    expect(screen.queryByRole("list", { name: "Grupy etapów pipeline" })).toBeNull();
  });

  it("„Mój ruch” i nazwisko przełączają się w pasku (aria-pressed)", async () => {
    renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");
    const myMove = screen.getByRole("button", { name: /^Mój ruch/ });
    expect(myMove).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(myMove);
    expect(myMove).toHaveAttribute("aria-pressed", "true");
    await userEvent.type(screen.getByRole("textbox", { name: "Filtruj po nazwisku" }), "zzz");
    expect(screen.getByRole("textbox", { name: "Filtruj po nazwisku" })).toHaveValue("zzz");
  });

  it("Tablica: jeden etap = jedna kolumna, etapy-odznaki na kartach, zamknięci na pasku", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    // Osoba na etapie „Przepuszczony przez DZ" (index 3) — w kolumnie „Zweryfikowany".
    columns[3] = {
      ...columns[3],
      count: 1,
      items: [{ id: 7301, candidate_id: 8301, stage: "new", name: "Iga", lastname: "Mazur", days_in_stage: 1 }],
    };
    const { container } = renderBoard(columns as never);
    await screen.findByTestId("pipeline-board");

    const headers = Array.from(container.querySelectorAll("[data-colid] h3")).map((h) => h.textContent);
    expect(headers).toEqual([
      "Nowi",
      "Screening",
      "Zweryfikowany",
      "CV wysłane",
      "Rozmowa u klienta",
      "Akceptacja",
      "Umowa",
      "Zatrudniony",
    ]);
    // Karta z etapu-odznaki stoi w kolumnie gospodarza i niesie odznakę.
    const verified = container.querySelector('[data-colid="def:302"]')!;
    expect(within(verified as HTMLElement).getByText("Iga Mazur")).toBeTruthy();
    expect(within(verified as HTMLElement).getByText("DZ ✓")).toBeTruthy();
    // Odrzuceni i wycofani nie zajmują kolumn — pasek z celami upuszczenia.
    const bar = screen.getByTestId("board-closed-bar");
    expect(bar).toHaveTextContent("Odrzuceni 1");
    expect(bar).toHaveTextContent("Wycofani 0");
    expect(container.querySelector('[data-colid="def:313"]')).toBeNull();
    await userEvent.click(within(bar).getByRole("button", { name: /Odrzuceni/ }));
    expect(container.querySelector('[data-colid="def:313"]')).toBeTruthy();
  });

  it("odznaki w doku: „DZ ✓” przesuwa na etap DZ, „Gotowy do Cpro” tylko z cproEnabled", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[2] = {
      ...columns[2],
      count: 1,
      items: [{ id: 7201, candidate_id: 8201, stage: "verified", name: "Olek", lastname: "Nowy", days_in_stage: 1 }],
    };
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={columns as never} jobId={10} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    await screen.findByText("Olek Nowy");
    fireEvent.click(document.querySelector('[data-candidate-id="8201"]') as HTMLElement);
    const dock = await screen.findByRole("complementary", { name: "Karta kandydata" });
    const group = within(dock).getByRole("group", { name: "Odznaki etapu" });
    expect(within(group).queryByRole("button", { name: /Gotowy do Cpro/ })).toBeNull();
    await userEvent.click(within(group).getByRole("button", { name: "+ DZ" }));
    await waitFor(() =>
      expect(post.mock.calls.find((c) => c[0] === "/api/pipeline/move")?.[1]).toMatchObject({
        candidate_id: 8201,
        stage_def_id: 303,
      }),
    );

    rerender(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={columns as never} jobId={10} cproEnabled />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    expect(
      within(screen.getByRole("group", { name: "Odznaki etapu" })).getByRole("button", {
        name: /Gotowy do Cpro/,
      }),
    ).toBeTruthy();
  });

  it("licznik „Do przejrzenia” liczy propozycje z bazy razem z kartami z ogłoszeń", async () => {
    reviewTotal.value = 14;
    try {
      // Szablon bez etapu „Ogłoszenia" — kolumna „Do przejrzenia" stoi sama.
      renderBoard(defaultB2BColumns());
      const heading = await screen.findByRole("heading", { name: "Do przejrzenia" });
      await waitFor(() => expect(heading.parentElement).toHaveTextContent("Do przejrzenia14"));

      // Z etapem „Ogłoszenia" (1 karta) nagłówek liczy 1 + 14.
      rtlCleanup();
      const withPosting = [
        {
          stage: "posting",
          name: "Ogłoszenia",
          category: "internal",
          stage_def_id: 299,
          count: 1,
          items: [{ id: 7001, candidate_id: 8001, stage: "posting", name: "Ada", lastname: "Z Ogłoszenia", days_in_stage: 0 }],
        },
        ...(defaultB2BColumns() as unknown as Array<Record<string, unknown>>),
      ];
      const { container } = renderBoard(withPosting as never);
      await waitFor(() =>
        expect(
          container.querySelector('[aria-label="Do przejrzenia, liczba kandydatów: 15"]'),
        ).toBeTruthy(),
      );
    } finally {
      reviewTotal.value = 0;
    }
  });

  it("„Gotowy do Cpro” pyta, kto wyśle, i przesuwa z wytypowaną osobą; u Nordei kolumna to „Wysłane do Cpro”", async () => {
    get.mockImplementation((url: string) =>
      url === "/api/users"
        ? Promise.resolve({ data: [{ id: 1, name: "Artur" }, { id: 44, name: "Marta Rekruter" }] })
        : Promise.resolve({ data: {} }),
    );
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[2] = {
      ...columns[2],
      count: 1,
      items: [{ id: 7202, candidate_id: 8202, stage: "verified", name: "Ola", lastname: "Gotowa", days_in_stage: 1 }],
    };
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={columns as never} jobId={10} cproEnabled />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    await screen.findByText("Ola Gotowa");
    const headers = Array.from(container.querySelectorAll("[data-colid] h3")).map((h) => h.textContent);
    expect(headers).toContain("Wysłane do Cpro");
    expect(headers).not.toContain("CV wysłane");

    fireEvent.click(document.querySelector('[data-candidate-id="8202"]') as HTMLElement);
    const dock = await screen.findByRole("complementary", { name: "Karta kandydata" });
    await userEvent.click(
      within(within(dock).getByRole("group", { name: "Odznaki etapu" })).getByRole("button", {
        name: /Gotowy do Cpro/,
      }),
    );
    // Najpierw okno — bez ruchu.
    const dialog = await screen.findByRole("dialog", { name: "Gotowy do Cpro" });
    expect(post.mock.calls.some((c) => c[0] === "/api/pipeline/move")).toBe(false);
    const select = within(dialog).getByLabelText("Wysyła");
    await waitFor(() => expect(within(select).getByRole("option", { name: "Marta Rekruter" })).toBeTruthy());
    await userEvent.selectOptions(select, "44");
    await userEvent.click(within(dialog).getByRole("button", { name: "Oznacz „Gotowy do Cpro”" }));
    await waitFor(() =>
      expect(post.mock.calls.find((c) => c[0] === "/api/pipeline/move")?.[1]).toMatchObject({
        candidate_id: 8202,
        stage_def_id: 304,
        task_assignee_id: 44,
      }),
    );
  });

  it("karta na etapie Cpro pokazuje, kto wysyła", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[4] = {
      ...columns[4],
      count: 1,
      items: [
        {
          id: 7402,
          candidate_id: 8402,
          stage: "new",
          name: "Jan",
          lastname: "Wysyłany",
          days_in_stage: 1,
          task_assignee_id: 44,
          task_assignee_name: "Marta Rekruter",
        },
      ],
    };
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={columns as never} jobId={10} cproEnabled />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    await screen.findByText("Jan Wysyłany");
    const card = document.querySelector('[data-candidate-id="8402"]') as HTMLElement;
    expect(within(card).getByText("Wysyła: Marta Rekruter")).toBeTruthy();
  });

  it("osoba na etapie Cpro ma na karcie obie odznaki, a w doku „DZ” jest włączone", async () => {
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[4] = {
      ...columns[4],
      count: 1,
      items: [{ id: 7401, candidate_id: 8401, stage: "new", name: "Ewa", lastname: "Cpro", days_in_stage: 1 }],
    };
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={columns as never} jobId={10} cproEnabled />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    await screen.findByText("Ewa Cpro");
    const card = document.querySelector('[data-candidate-id="8401"]') as HTMLElement;
    expect(within(card).getByText("DZ ✓")).toBeTruthy();
    expect(within(card).getByText("Gotowy do Cpro")).toBeTruthy();
    fireEvent.click(card);
    const group = within(
      await screen.findByRole("complementary", { name: "Karta kandydata" }),
    ).getByRole("group", { name: "Odznaki etapu" });
    expect(within(group).getByRole("button", { name: "✓ DZ" })).toHaveAttribute("aria-pressed", "true");
    expect(within(group).getByRole("button", { name: "✓ Gotowy do Cpro" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("„DZ ✓” jest wyłączone dla rekrutera — ustawia je DL albo Head of Recruitment", async () => {
    useAuthStore.setState({ user: { id: 2, role: "recruiter", roles: ["recruiter"] } } as never);
    const columns = defaultB2BColumns() as unknown as Array<Record<string, unknown>>;
    columns[2] = {
      ...columns[2],
      count: 1,
      items: [{ id: 7201, candidate_id: 8201, stage: "verified", name: "Olek", lastname: "Nowy", days_in_stage: 1 }],
    };
    renderBoard(columns as never);
    await screen.findByText("Olek Nowy");
    fireEvent.click(document.querySelector('[data-candidate-id="8201"]') as HTMLElement);
    const dock = await screen.findByRole("complementary", { name: "Karta kandydata" });
    expect(within(dock).getByRole("button", { name: "+ DZ" })).toBeDisabled();
  });

  it("nagłówek kolumny niesie drugą linię o SLA i najstarszej karcie", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    // Bez karty klienta SLA nie jest zgadywane — kolumna mówi „SLA: —".
    const intake = container.querySelector('[data-column-sla="def:300"]');
    expect(intake).toHaveTextContent("SLA: —");
    expect(intake).toHaveTextContent("najstarszy 9 d");
    // Terminal odsyła po powody do doku, weryfikacja — do następnego kroku.
    expect(
      container.querySelector('[data-column-sla="def:302"]'),
    ).toHaveTextContent("→ CV do klienta");
  });

  it("karta mówi, co dalej, a filtr „Bez następnej akcji” liczy zaległe", async () => {
    renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    // Dwa dni na etapie wejściowym → screening; dziewięć → brak akcji.
    expect(screen.getByText("Umów screening")).toBeTruthy();
    expect(screen.getByText("Brak następnej akcji")).toBeTruthy();
    // Licznik w rail'u liczy TĄ SAMĄ funkcją co karta: jedna zaległa karta
    // wejściowa. Karta ze screeningu (2 dni) ma akcję, terminalna nie liczy się.
    await userEvent.click(screen.getByRole("button", { name: /^Filtry/ }));
    expect(
      await screen.findByRole("button", { name: "Bez następnej akcji · 1" }),
    ).toBeTruthy();
  });

  it("przełącznik „Ukryj puste kolumny” zostawia tylko kolumny z kartami", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    await userEvent.click(screen.getByRole("button", { name: /^Filtry/ }));
    await userEvent.click(
      await screen.findByRole("button", { name: "Ukryj puste kolumny" }),
    );

    // Zostają wyłącznie kolumny z kartami: wejście i screening (odrzuceni
    // są na pasku nad tablicą, nie w kolumnie).
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(2);
  });
});

// B-B05: filtr „Utknęli > 7 d" liczył także karty terminalne (odrzuceni stoją
// na swoim etapie bezterminowo) i pokazywał 80 obok KPI jobbara „26".
describe("KanbanBoardV2 — „Utknęli > 7 d” bez kolumn terminalnych", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  it("liczy wyłącznie karty nieterminalne — tak jak KPI jobbara", async () => {
    const columns = overflowColumns() as unknown as Array<Record<string, unknown>>;
    const stuck = (id: number, days: number) => ({
      id,
      candidate_id: id,
      name: "Test",
      lastname: `Osoba${id}`,
      stage: "new",
      days_in_stage: days,
      verification_status: null,
    });
    columns[0] = { ...columns[0], count: 1, items: [stuck(951, 9)] };
    const last = columns.length - 1;
    columns[last] = {
      ...columns[last],
      count: 2,
      items: [stuck(952, 90), stuck(953, 40)],
    };
    renderBoard(columns as never);
    // Podsumowanie po prawej liczy to samo, co filtr w „Filtry ▾".
    expect(await screen.findByText(/utknęło > 7 d/)).toHaveTextContent("1 utknęło > 7 d");
    await userEvent.click(screen.getByRole("button", { name: /^Filtry/ }));
    expect(await screen.findByText("Utknęli > 7 d · 1")).toBeInTheDocument();
  });
});

// Przegląd UX 17.09.2026: dok nie zajmuje kolumny siatki — wysuwa się z prawej
// dopiero po kliknięciu karty, Escape go zamyka, a `?candidate=` otwiera go
// od razu z powiadomienia.
describe("KanbanBoardV2 — wysuwany dok i deep link ?candidate=", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    useAuthStore.setState({ user: { id: 1, role: "admin", roles: ["admin"] } } as never);
    useUiStore.setState({ density: "cozy" } as never);
  });

  function dockColumns() {
    return overviewColumns();
  }

  it("bez kliknięcia karty nie ma doku ani pustego panelu obok tablicy", async () => {
    renderBoard(dockColumns());
    await screen.findByTestId("pipeline-board");
    expect(
      screen.queryByRole("complementary", { name: "Karta kandydata" }),
    ).toBeNull();
    expect(screen.queryByText(/Kliknij kartę na tablicy/)).toBeNull();
  });

  it("klik karty otwiera dok, Escape go zamyka", async () => {
    renderBoard(dockColumns());
    const link = await screen.findByRole("link", { name: "Aleksandra Nowakowska" });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    expect(
      await screen.findByRole("complementary", { name: "Karta kandydata" }),
    ).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() =>
      expect(
        screen.queryByRole("complementary", { name: "Karta kandydata" }),
      ).toBeNull(),
    );
  });

  it("Escape przy otwartym dialogu nie zamyka doku", async () => {
    renderBoard(dockColumns());
    const link = await screen.findByRole("link", { name: "Aleksandra Nowakowska" });
    fireEvent.click(link.closest("[data-kanban-card]") as HTMLElement);
    await screen.findByRole("complementary", { name: "Karta kandydata" });

    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    document.body.appendChild(dialog);
    try {
      fireEvent.keyDown(window, { key: "Escape" });
      expect(
        screen.getByRole("complementary", { name: "Karta kandydata" }),
      ).toBeInTheDocument();
    } finally {
      dialog.remove();
    }
  });

  it("initialDockCandidateId otwiera dok tej osoby i prosi stronę o zdjęcie parametru", async () => {
    const onHandled = vi.fn();
    const scrollIntoView = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => {});
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={dockColumns()}
            jobId={10}
            initialDockCandidateId={90}
            onInitialDockHandled={onHandled}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );

    const dock = await screen.findByRole("complementary", { name: "Karta kandydata" });
    expect(within(dock).getByText("Aleksandra Nowakowska")).toBeInTheDocument();
    expect(onHandled).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalled();
    scrollIntoView.mockRestore();
  });

  it("zgłasza stronie, kto jest w doku — „Tabela” otwiera potem tę osobę w panelu", async () => {
    const onDockCandidateChange = vi.fn();
    const scrollIntoView = vi
      .spyOn(Element.prototype, "scrollIntoView")
      .mockImplementation(() => {});
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={dockColumns()}
            jobId={10}
            initialDockCandidateId={90}
            onDockCandidateChange={onDockCandidateChange}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );
    await screen.findByRole("complementary", { name: "Karta kandydata" });
    expect(onDockCandidateChange).toHaveBeenNthCalledWith(1, null);
    expect(onDockCandidateChange).toHaveBeenLastCalledWith(90);
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(onDockCandidateChange).toHaveBeenLastCalledWith(null));
    scrollIntoView.mockRestore();
  });

  it("initialDockCandidateId spoza tablicy nie otwiera doku, ale i tak zdejmuje parametr", async () => {
    const onHandled = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2
            columns={dockColumns()}
            jobId={10}
            initialDockCandidateId={12345}
            onInitialDockHandled={onHandled}
          />
        </TooltipProvider>
      </QueryClientProvider>,
    );

    await screen.findByTestId("pipeline-board");
    await waitFor(() => expect(onHandled).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByRole("complementary", { name: "Karta kandydata" }),
    ).toBeNull();
  });
});


// ── Przełącznik widoku: kafelki ↔ kolumny (decyzja Artura 20.09.2026) ────────
//
// Tryb kafelkowy (karty degradowane do ~25 px, żeby cały szablon zmieścił się
// bez przewijania) ZOSTAJE, ale jako wybór użytkownika. Reguła automatyczna —
// szablon szerszy niż `OVERVIEW_COLUMN_THRESHOLD` otwiera się kafelkowo — jest
// tylko WARTOŚCIĄ DOMYŚLNĄ.
//
// To jedyna warstwa, która to łapie: usterka #1604 (odznaka screeningu na
// `absolute bottom-1 right-1` przykrywająca „następną akcję") przeszła przez
// komplet zielonych testów, bo układu karty nikt nie asercjonował.
describe("KanbanBoardV2 — przełącznik widoku tablicy", () => {
  /** `n` kolumn, każda z jedną kartą (pustych nie ukrywamy w tych testach). */
  function wideColumns(n: number) {
    return Array.from({ length: n }, (_, i) => ({
      stage: "new",
      name: `Etap ${i + 1}`,
      category: "internal",
      stage_def_id: 900 + i,
      count: 1,
      items: [
        {
          id: 7000 + i,
          candidate_id: 7000 + i,
          name: "Kandydat",
          lastname: `Nr${i + 1}`,
          stage: "new",
          days_in_stage: 1,
          verification_status: "active",
        },
      ],
    })) as never;
  }

  function renderWide(n: number) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <KanbanBoardV2 columns={wideColumns(n)} jobId={10} />
        </TooltipProvider>
      </QueryClientProvider>,
    );
  }

  const toggle = () => screen.queryByRole("group", { name: "Widok tablicy" });
  const tiles = () => screen.getByRole("button", { name: "Widok przeglądowy" });
  const columns = () => screen.getByRole("button", { name: "Widok kolumnowy" });

  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [], off_template: null } });
    post.mockResolvedValue({ data: {} });
    get.mockImplementation(() =>
      Promise.resolve({
        data: { effective_budget_hourly: null, pipeline_template_id: null },
      }),
    );
  });

  it("szeroki szablon startuje w widoku przeglądowym, bez zapisanej preferencji", async () => {
    renderWide(12);
    await screen.findByTestId("pipeline-board");

    expect(toggle()).toBeInTheDocument();
    expect(tiles()).toHaveAttribute("aria-pressed", "true");
    expect(columns()).toHaveAttribute("aria-pressed", "false");
  });

  it("kliknięcie „Kolumny” przełącza widok i zapisuje wybór", async () => {
    renderWide(12);
    await screen.findByTestId("pipeline-board");

    await userEvent.click(columns());

    expect(columns()).toHaveAttribute("aria-pressed", "true");
    expect(tiles()).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem(KANBAN_VIEW_MODE_STORAGE_KEY)).toBe("columns");
  });

  it("wybór przeżywa przemontowanie — reguła automatyczna go nie nadpisuje", async () => {
    const first = renderWide(12);
    await screen.findByTestId("pipeline-board");
    await userEvent.click(columns());
    first.unmount();

    renderWide(12);
    await screen.findByTestId("pipeline-board");

    expect(columns()).toHaveAttribute("aria-pressed", "true");
  });

  it("wąski szablon nie ma przełącznika — kafelki dałyby tam tylko mniejsze karty", async () => {
    renderWide(4);
    await screen.findByTestId("pipeline-board");

    expect(toggle()).toBeNull();
  });

  it("zapamiętane kafelki NIE wracają na wąskim szablonie — byłby to stan bez wyjścia", async () => {
    window.localStorage.setItem(KANBAN_VIEW_MODE_STORAGE_KEY, "tiles");
    renderWide(4);
    await screen.findByTestId("pipeline-board");

    // Przełącznika nie ma, więc nie ma czym wyjść z kafelków — widok musi być
    // kolumnowy. Preferencja zostaje zapisana i wróci na szerokim szablonie.
    expect(toggle()).toBeNull();
    expect(window.localStorage.getItem(KANBAN_VIEW_MODE_STORAGE_KEY)).toBe("tiles");
  });
});
