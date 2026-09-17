/**
 * KanbanBoardV2 — testy correctness M4 PR-03 (audyt P1.3/P1.4/P2.1/P0.3-FE).
 *
 * Drag-and-drop nie jest odpalalny w jsdom (repo-precedens: weryfikacja dnd
 * unit testami + realnym Chrome), więc testujemy powierzchnie renderu i akcji:
 * - bramka „Pending" wyłączona (17.09.2026): karta ponad budżetem ma odznakę
 *   informacyjną, zero akcji akceptacji i żadnej blokady ruchu,
 * - ruch zbiorczy przechodzi przez tę samą bramkę co przeciągnięcie,
 * - modal stawki do klienta tylko dla `can_write_client_rate`.
 */

import * as React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const kanban = vi.fn();
const post = vi.fn();
const apiGet = vi.fn();
const toastError = vi.fn();
const toastSuccess = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => post(...a),
  },
  candidatesApi: {
    removeFromRecruitment: vi.fn(),
    setRecruitmentClientRate: vi.fn(),
  },
  pipelineApi: {
    kanban: (...a: unknown[]) => kanban(...a),
    move: vi.fn(() => Promise.resolve({ data: {} })),
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

import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";

beforeEach(() => {
  apiGet.mockImplementation(() =>
    Promise.resolve({ data: { salary_max: null, pipeline_template_id: null } }),
  );
});

beforeAll(() => {
  // Radix Select uses pointer-capture APIs that jsdom does not implement.
  if (!HTMLElement.prototype.hasPointerCapture) {
    HTMLElement.prototype.hasPointerCapture = () => false;
    HTMLElement.prototype.setPointerCapture = () => {};
    HTMLElement.prototype.releasePointerCapture = () => {};
  }
});

function overBudgetColumns() {
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
          verification_status: "active",
          budget_exceeded: true,
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
  columns = overBudgetColumns(),
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

describe("KanbanBoardV2 — karta ponad budżetem (bramka „Pending” wyłączona)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  it.each(["admin", "delivery_lead", "head_of_recruitment", "recruiter"])(
    "rola %s widzi odznakę „ponad budżet” i ŻADNEJ akcji akceptacji",
    async (role) => {
      useAuthStore.setState({ user: { role, roles: [role] } as never });
      useUiStore.setState({ density: "cozy" } as never);

      renderBoard();
      expect(await screen.findByText("ponad budżet")).toBeTruthy();
      expect(screen.queryByText("Pending")).toBeNull();
      expect(screen.queryByTitle("Akceptuj weryfikację")).toBeNull();
      expect(screen.queryByTitle("Odrzuć weryfikację")).toBeNull();
    },
  );

  it("pokazuje wynik dopasowania także na karcie oczekującej na akceptację", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    useUiStore.setState({ density: "compact" } as never);

    renderBoard(overBudgetColumns(), new Map([[5, 77]]));

    expect(
      await screen.findByLabelText("Dopasowanie AI: 77 na 100"),
    ).toBeTruthy();
  });

  it("karta rekrutera mówi wprost o braku danych osoby dodającej", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    useUiStore.setState({ density: "cozy" } as never);

    renderBoard();
    // Karta się renderuje…
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

    renderBoard(overBudgetColumns(), undefined, true);

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
 * Bramka ruchu doku = lustro `POST /api/pipeline/move` (wspólna funkcja
 * `moveBlockedReason`) oraz odświeżenie zapytania strony po ruchu. Do 09.2026
 * dok trzymał własną kopię reguł (weto blokowało „Zweryfikowany", „Pending"
 * nie blokował niczego), a udany ruch nie unieważniał `["kanban", id]`, więc
 * KPI i kolejki kroków 05–08 pokazywały stan sprzed ruchu.
 */
describe("KanbanBoardV2 — bramka ruchu doku i zapytanie strony", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
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

  async function openDockPills() {
    const card = await waitFor(() => {
      const el = document.querySelector("[data-kanban-card]");
      expect(el).toBeTruthy();
      return el as HTMLElement;
    });
    fireEvent.click(card);
    const heading = await screen.findByText("Przenieś na etap");
    return heading.parentElement as HTMLElement;
  }

  it("weto HM blokuje w doku „CV Wysłane”, ale NIE „Zweryfikowany” — jak serwer", async () => {
    renderBoard(
      gateColumns({
        hm_veto: {
          hiring_manager_contact_id: 5,
          source_job_id: 2,
          rejected_at: "2026-01-01",
          rejection_reason_name: "Brak bankowości",
        },
      }),
    );
    const pills = await openDockPills();

    expect(within(pills).getByRole("button", { name: "Zweryfikowany" })).not.toBeDisabled();
    const cvSent = within(pills).getByRole("button", { name: "CV Wysłane" });
    expect(cvSent).toBeDisabled();
    expect(cvSent.getAttribute("title")).toContain("Brak bankowości");
    expect(within(pills).getByRole("button", { name: "Odrzucony" })).not.toBeDisabled();
  });

  /** Fragment „Default B2B": między „Wysłać do Cpro" a „Interview Klient"
   *  stoją „CV Wysłane" (weto blokuje) i „Preparation Meeting" (nie blokuje). */
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

  it("weto HM na drodze naprzód: główna akcja doku nie robi objazdu na „Preparation Meeting”", async () => {
    renderBoard(
      vetoRouteColumns({
        hm_veto: {
          hiring_manager_contact_id: 5,
          source_job_id: 2,
          rejected_at: "2026-01-01",
          rejection_reason_name: "Brak bankowości",
        },
      }),
    );
    await openDockPills();

    expect(
      screen.queryByRole("button", { name: /Przenieś na etap: Preparation Meeting/ }),
    ).toBeNull();
    const blocked = screen.getByRole("button", { name: /Przenieś na etap: CV Wysłane/ });
    expect(blocked).toBeDisabled();
    expect(blocked.getAttribute("title")).toContain("Brak bankowości");
    // Powód widać bez najeżdżania kursorem — pod wyszarzonym krokiem.
    expect(blocked.parentElement?.textContent).toContain("Brak bankowości");
  });

  it("karta bez weta dostaje zwykłą akcję naprzód na „CV Wysłane”", async () => {
    renderBoard(vetoRouteColumns({}));
    await openDockPills();

    expect(
      screen.getByRole("button", { name: /Przenieś na etap: CV Wysłane/ }),
    ).not.toBeDisabled();
  });

  it("karta ponad budżetem (także zapisana jako `pending`) nie blokuje żadnego ruchu w doku", async () => {
    renderBoard(
      gateColumns({ verification_status: "pending", budget_exceeded: true }),
    );
    const pills = await openDockPills();

    for (const name of ["Zweryfikowany", "CV Wysłane", "Odrzucony"]) {
      expect(within(pills).getByRole("button", { name })).not.toBeDisabled();
    }
    expect(
      screen.getByRole("button", { name: /Odrzuć z powodem/ }),
    ).not.toBeDisabled();
  });

  it("ruch zbiorczy pomija kartę zablokowaną wetem i mówi dlaczego — bez cichego powrotu", async () => {
    const veto = {
      hiring_manager_contact_id: 5,
      source_job_id: 2,
      rejected_at: "2026-01-01",
      rejection_reason_name: "Brak doświadczenia w bankowości",
    };
    renderBoard(gateColumns({ hm_veto: veto }));
    await userEvent.click(
      await screen.findByRole("checkbox", { name: "Zaznacz Jan Bramka" }),
    );
    const bulkTrigger = screen
      .getAllByRole("combobox")
      .find((el) => el.textContent?.includes("Przenieś na etap"));
    await userEvent.click(bulkTrigger as Element);
    await userEvent.click(await screen.findByRole("option", { name: /CV Wysłane/ }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        expect.stringContaining("Brak doświadczenia w bankowości"),
      ),
    );
    expect(toastError.mock.calls[0][0]).toContain("Jan Bramka");
    expect(post).not.toHaveBeenCalled();
  });

  it("„CV Wysłane” bez prawa zapisu stawki do klienta przenosi kartę bez pytania o stawkę", async () => {
    apiGet.mockImplementation(() =>
      Promise.resolve({
        data: {
          salary_max: null,
          pipeline_template_id: null,
          can_write_client_rate: false,
        },
      }),
    );
    renderBoard(gateColumns({}));
    const pills = await openDockPills();
    await userEvent.click(within(pills).getByRole("button", { name: "CV Wysłane" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({ candidate_id: 61, stage: "cv_sent" }),
      ),
    );
    expect(screen.queryByText(/stawk[aęi] do klienta/i)).toBeNull();
  });

  it("„CV Wysłane” z prawem zapisu stawki do klienta najpierw pyta o stawkę", async () => {
    apiGet.mockImplementation(() =>
      Promise.resolve({
        data: {
          salary_max: null,
          pipeline_template_id: null,
          can_write_client_rate: true,
        },
      }),
    );
    renderBoard(gateColumns({}));
    // Odpowiedź `GET /api/jobs/{id}` musi dojść, zanim klikniemy.
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    const pills = await openDockPills();
    await userEvent.click(within(pills).getByRole("button", { name: "CV Wysłane" }));

    expect(await screen.findByRole("dialog")).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });
});

describe("KanbanBoardV2 — focus na etapie", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  it("pokazuje pełny pipeline w równych desktopowych kolumnach", async () => {
    const { container } = renderBoard(
      overviewColumns(),
      new Map([[90, 82]]),
    );

    const board = await screen.findByTestId("pipeline-board");
    expect(board).toHaveAttribute("data-desktop-layout", "full-pipeline");
    expect(board).toHaveClass("overflow-auto", "xl:pointer-fine:gap-1");
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(15);
    for (const column of container.querySelectorAll("[data-colid]")) {
      expect(column).toHaveClass(
        "xl:pointer-fine:w-0",
        "xl:pointer-fine:min-w-0",
        "xl:pointer-fine:basis-0",
        "xl:pointer-fine:grow",
        "xl:pointer-fine:shrink",
      );
    }

    expect(container.querySelector("[data-mobile-stage-navigation]")).toHaveClass(
      "xl:pointer-fine:hidden",
    );
    expect(screen.getByTitle("Rozmowa techniczna")).toBeTruthy();
    expect(
      screen.getByRole("group", { name: "Nowy, liczba kandydatów: 1" }),
    ).toBeTruthy();

    const candidate = await screen.findByRole("link", {
      name: "Aleksandra Nowakowska",
    });
    expect(candidate.closest("[data-kanban-card]")).toHaveClass(
      "xl:pointer-fine:p-1",
      "xl:pointer-fine:pb-6",
      "xl:pointer-fine:pt-6",
    );
    expect(candidate.closest("[data-kanban-card]")?.getAttribute("title")).toContain(
      "Aleksandra Nowakowska",
    );
    expect(candidate.closest("[data-kanban-card]")?.getAttribute("title")).toContain(
      "Dodano do rekrutacji przez: Ewa Nowak",
    );
    expect(screen.getByTestId("overview-match-score-90")).toHaveTextContent("82");
    expect(screen.getByText("R: Ewa")).toBeTruthy();
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

  // Fala 3 („parytet z makietami") przesunęła próg zwężenia karty z czterech
  // etapów na dziesięć: po zwinięciu pustych grup „Default B2B" renderuje
  // dziesięć kolumn (z „Ogłoszeniami") i to WŁAŚNIE tam karta ma pokazać
  // pełny układ z makiety.
  // Cztery kolumny to tym bardziej pełna karta — nie kafelek.
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
    // Kafelkowy badge wyniku jest tylko w trybie przeglądowym.
    expect(screen.queryByTestId("overview-match-score-90")).toBeNull();
    // Pełna karta niesie wiersz „co dalej" (5 dni na etapie wejściowym).
    expect(screen.getByText("Umów screening")).toBeTruthy();
    const descriptionId = candidate.getAttribute("aria-describedby");
    expect(descriptionId).toBeTruthy();
    expect(document.querySelector(`#${descriptionId}`)).toHaveTextContent(
      "Następny krok: Umów screening.",
    );
  });

  it("powyżej dziesięciu kolumn karta wraca do kafelka", async () => {
    renderBoard(overviewColumns());

    await screen.findByTestId("pipeline-board");
    const candidate = await screen.findByRole("link", {
      name: "Aleksandra Nowakowska",
    });
    expect(candidate.closest("[data-kanban-card]")).toHaveClass(
      "xl:pointer-fine:pt-6",
    );
    expect(screen.getByTestId("overview-match-score-90")).toBeTruthy();
  });

  it("zachowuje scroll i navigator dla pipeline dłuższego niż 16 etapów", async () => {
    const { container } = renderBoard(overflowColumns());

    const board = await screen.findByTestId("pipeline-board");
    expect(board).toHaveAttribute("data-desktop-layout", "scroll");
    expect(board).not.toHaveClass("xl:pointer-fine:gap-1");
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(17);
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
      name: "Screening, etap 2 z 15",
    });
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(15);
    expect(container.querySelector('[data-colid="def:201"]')).toBeTruthy();
    expect(container.querySelector('[data-colid="def:202"]')).toBeTruthy();
    expect(screen.getByText("W procesie: 4")).toBeTruthy();

    await userEvent.click(picker);
    expect(await screen.findAllByRole("option")).toHaveLength(15);
    await userEvent.click(
      await screen.findByRole("option", {
        name: /15\. Zatrudniony.*liczba kandydatów: 0/,
      }),
    );

    expect(
      await screen.findByRole("combobox", {
        name: "Zatrudniony, etap 15 z 15",
      }),
    ).toBeTruthy();
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(15);
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
      screen.getByRole("combobox", { name: "Screening, etap 2 z 15" }),
    ).toBeTruthy();
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(15);
    expect(post).not.toHaveBeenCalled();
  });

  it("nawiguje strzałkami i blokuje poprzedni etap na początku", async () => {
    renderBoard(focusColumns());

    await userEvent.click(
      await screen.findByRole("combobox", {
        name: "Screening, etap 2 z 15",
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
        name: "Screening, etap 2 z 15",
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
    expect(screen.getByText("W procesie: 4")).toBeTruthy();
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
    expect(options).toHaveLength(15);
    expect(
      options.some((o) => o.textContent?.includes("Poza szablonem")),
    ).toBe(false);
  });

  it("nie oferuje kubełka w nawigatorze etapów", async () => {
    renderWithBucket();

    expect(
      await screen.findByRole("combobox", { name: /etap 2 z 15/ }),
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
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(15);
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

  it("lewa kolumna pokazuje grupy etapów z licznikami zamiast piętnastu zer", async () => {
    renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    const groups = screen.getByRole("list", { name: "Grupy etapów pipeline" });
    expect(groups).toHaveTextContent("Wszystkie aktywne");
    expect(groups).toHaveTextContent("Nowi / Analiza CV");
    expect(groups).toHaveTextContent("U klienta (CV → interview)");
    expect(groups).toHaveTextContent("Odrzuceni / wycofani");
    // Etapy nie zniknęły — są schowane pod grupą, nie usunięte.
    expect(
      screen.queryByRole("list", { name: /Etapy grupy/ }),
    ).toBeNull();
  });

  it("klik w grupę rozwija jej etapy z zachowanym fokusem kolumny", async () => {
    renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    await userEvent.click(
      screen.getByRole("button", { name: /U klienta \(CV → interview\)/ }),
    );
    const stages = await screen.findByRole("list", {
      name: "Etapy grupy U klienta (CV → interview)",
    });
    expect(stages).toHaveTextContent("CV Wysłane");
    expect(stages).toHaveTextContent("Akceptacja");
  });

  it("puste grupy klienta i umowy zwijają się w jedną kolumnę-zastępnik", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    // 15 etapów − 4 (grupa klienta) − 4 (grupa umowy) = 7 prawdziwych kolumn,
    // plus dwa zastępniki = 9 pozycji na tablicy.
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(7);
    expect(container.querySelectorAll("[data-collapsed-group]")).toHaveLength(2);
    // Zastępnik nie jest KOLUMNĄ (brak `data-colid`), ale JEST celem
    // upuszczenia — patrz test niżej.
    const placeholder = container.querySelector('[data-collapsed-group="client"]');
    expect(placeholder).toBeTruthy();
    expect(placeholder?.querySelector("[data-colid]")).toBeNull();
  });

  // Bez tego zwijanie zabierałoby NAJCZĘSTSZY ruch w produkcie: pierwsze CV do
  // klienta przeciągane ze Screeningu na pusty jeszcze etap „CV Wysłane".
  it("zwinięta grupa JEST celem upuszczenia — pod id pierwszego swojego etapu", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    // „CV Wysłane" to szósta kolumna szablonu → stage_def_id 305.
    const drop = container.querySelectorAll('[data-rfd-droppable-id="def:305"]');
    expect(drop).toHaveLength(1);
    // …i leży WEWNĄTRZ zastępnika grupy klienta.
    expect(
      container
        .querySelector('[data-collapsed-group="client"]')
        ?.querySelector('[data-rfd-droppable-id="def:305"]'),
    ).toBeTruthy();
    // Prawdziwa kolumna „CV Wysłane" nie jest renderowana, więc id się NIE
    // dubluje (twardy wymóg @hello-pangea/dnd).
    expect(container.querySelector('[data-colid="def:305"]')).toBeNull();

    // Grupa umowy tak samo — pod id „Umowa wysłana" (dziesiąta kolumna).
    expect(
      container.querySelectorAll('[data-rfd-droppable-id="def:309"]'),
    ).toHaveLength(1);
  });

  it("po „Rozwiń etapy” cel wraca do prawdziwej kolumny, wciąż bez duplikatu id", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    const placeholder = container.querySelector<HTMLElement>(
      '[data-collapsed-group="client"]',
    );
    await userEvent.click(
      placeholder!.querySelector("button") as HTMLButtonElement,
    );

    expect(container.querySelector('[data-colid="def:305"]')).toBeTruthy();
    expect(
      container.querySelectorAll('[data-rfd-droppable-id="def:305"]'),
    ).toHaveLength(1);
  });

  it("bez prawa zapisu zastępnik nie przyjmuje upuszczenia", async () => {
    const { container } = renderBoard(defaultB2BColumns(), undefined, true);
    await screen.findByTestId("pipeline-board");

    // Wiążemy się z TĄ SAMĄ wartością, którą dostaje `isDropDisabled` —
    // DnD nie jest odpalalne w jsdom, więc kopia flagi nic by nie dowiodła.
    expect(
      container.querySelector('[data-collapsed-group="client"]'),
    ).toHaveAttribute("data-drop-disabled", "true");
  });

  it("z prawem zapisu zastępnik jest otwarty na upuszczenie", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    expect(
      container.querySelector('[data-collapsed-group="client"]'),
    ).toHaveAttribute("data-drop-disabled", "false");
  });

  it("„Rozwiń etapy” przywraca prawdziwe kolumny grupy", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    const placeholder = container.querySelector<HTMLElement>(
      '[data-collapsed-group="client"]',
    );
    await userEvent.click(
      placeholder!.querySelector("button") as HTMLButtonElement,
    );

    expect(container.querySelector('[data-collapsed-group="client"]')).toBeNull();
    expect(container.querySelector('[data-colid="def:305"]')).toBeTruthy();
    // 7 kolumn + 4 odzyskane etapy klienta; grupa umowy zostaje zwinięta.
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(11);
    expect(container.querySelectorAll("[data-collapsed-group]")).toHaveLength(1);
  });

  it("grupa z choćby jedną kartą renderuje się w pełni, bez zastępnika", async () => {
    const columns = (
      defaultB2BColumns() as unknown as Array<Record<string, unknown>>
    ).map((c) =>
      c.name === "Interview Klient"
        ? {
            ...c,
            count: 1,
            items: [
              {
                id: 7001,
                candidate_id: 7001,
                stage: "client_interview",
                name: "Ewa",
                lastname: "Klientowa",
                days_in_stage: 1,
              },
            ],
          }
        : c,
    ) as never;
    const { container } = renderBoard(columns);
    await screen.findByTestId("pipeline-board");

    expect(container.querySelector('[data-collapsed-group="client"]')).toBeNull();
    expect(container.querySelector('[data-collapsed-group="contract"]')).toBeTruthy();
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
    expect(
      container.querySelector('[data-column-sla="def:313"]'),
    ).toHaveTextContent("powody w doku");
  });

  it("karta mówi, co dalej, a filtr „Bez następnej akcji” liczy zaległe", async () => {
    renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    // Dwa dni na etapie wejściowym → screening; dziewięć → brak akcji.
    expect(screen.getByText("Umów screening")).toBeTruthy();
    expect(screen.getByText("Brak następnej akcji")).toBeTruthy();
    // Licznik w rail'u liczy TĄ SAMĄ funkcją co karta: jedna zaległa karta
    // wejściowa. Karta ze screeningu (2 dni) ma akcję, terminalna nie liczy się.
    expect(
      screen.getByRole("button", { name: "Bez następnej akcji · 1" }),
    ).toBeTruthy();
  });

  it("przełącznik „Ukryj puste kolumny” chowa też zastępniki zwiniętych grup", async () => {
    const { container } = renderBoard(defaultB2BColumns());
    await screen.findByTestId("pipeline-board");

    await userEvent.click(
      screen.getByRole("button", { name: "Kolumny: ukryj puste" }),
    );

    expect(container.querySelectorAll("[data-collapsed-group]")).toHaveLength(0);
    // Zostają wyłącznie kolumny z kartami: wejście, screening, odrzuceni.
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(3);
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
    expect(await screen.findByText("Utknęli > 7 d · 1")).toBeInTheDocument();
  });
});
