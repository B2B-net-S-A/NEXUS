/**
 * KanbanBoardV2 — testy correctness M4 PR-03 (audyt P1.3/P1.4/P2.1/P0.3-FE).
 *
 * Drag-and-drop nie jest odpalalny w jsdom (repo-precedens: weryfikacja dnd
 * unit testami + realnym Chrome), więc testujemy powierzchnie renderu i akcji:
 * - compact NIE ukrywa accept/reject weryfikacji (P2.1),
 * - guard approvera czyta pełny zbiór ról (primary + secondary — P0.3 FE),
 * - akcja accept celuje w id karty (fundament fixu stale-ID).
 */

import * as React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const acceptVerification = vi.fn();
const kanban = vi.fn();
const post = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: vi.fn(() =>
      Promise.resolve({ data: { salary_max: null, pipeline_template_id: null } })
    ),
    post: (...a: unknown[]) => post(...a),
  },
  candidatesApi: {
    removeFromRecruitment: vi.fn(),
    setRecruitmentClientRate: vi.fn(),
  },
  pipelineApi: {
    kanban: (...a: unknown[]) => kanban(...a),
    move: vi.fn(() => Promise.resolve({ data: {} })),
    acceptVerification: (...a: unknown[]) => acceptVerification(...a),
    rejectVerification: vi.fn(),
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
    showSuccess: vi.fn(),
    showError: vi.fn(),
  }),
}));

vi.mock("@/lib/celebrate", () => ({ celebrate: vi.fn() }));

import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";

beforeAll(() => {
  // Radix Select uses pointer-capture APIs that jsdom does not implement.
  if (!HTMLElement.prototype.hasPointerCapture) {
    HTMLElement.prototype.hasPointerCapture = () => false;
    HTMLElement.prototype.setPointerCapture = () => {};
    HTMLElement.prototype.releasePointerCapture = () => {};
  }
});

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

function overflowColumns() {
  const columns = focusColumns() as unknown as Array<Record<string, unknown>>;
  return [
    ...columns,
    {
      stage: "new",
      name: "Archiwum",
      category: "terminal",
      stage_def_id: 216,
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

describe("KanbanBoardV2 — pending verification card", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
  });

  it("compact NIE ukrywa akcji accept/reject dla approvera (P2.1)", async () => {
    useAuthStore.setState({
      user: { role: "delivery_lead", roles: ["delivery_lead"] } as never,
    });
    useUiStore.setState({ density: "compact" } as never);

    renderBoard();
    expect(await screen.findByTitle("Akceptuj weryfikację")).toBeTruthy();
    expect(screen.getByTitle("Odrzuć weryfikację")).toBeTruthy();
  });

  it("pokazuje wynik dopasowania także na karcie oczekującej na akceptację", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    useUiStore.setState({ density: "compact" } as never);

    renderBoard(pendingColumns(), new Map([[5, 77]]));

    expect(
      await screen.findByLabelText("Dopasowanie AI: 77 na 100"),
    ).toBeTruthy();
  });

  it("approver po roli DODATKOWEJ widzi akcje (multi-role, P0.3 FE)", async () => {
    useAuthStore.setState({
      // primary tac (bez uprawnień approvera), secondary delivery_lead — stary
      // kod patrzył tylko na primary i chował przyciski.
      user: { role: "tac", roles: ["tac", "delivery_lead"] } as never,
    });
    useUiStore.setState({ density: "cozy" } as never);

    renderBoard();
    expect(await screen.findByTitle("Akceptuj weryfikację")).toBeTruthy();
  });

  it("zwykły recruiter (bez ról approvera) nie widzi akcji decyzyjnych", async () => {
    useAuthStore.setState({
      user: { role: "recruiter", roles: ["recruiter"] } as never,
    });
    useUiStore.setState({ density: "cozy" } as never);

    renderBoard();
    // Karta się renderuje…
    const candidate = await screen.findByRole("link", { name: "Anna Kowalska" });
    // …ale decyzje approvera nie.
    expect(screen.queryByTitle("Akceptuj weryfikację")).toBeNull();
    expect(screen.getByText("Dodano przez: brak danych")).toBeTruthy();
    const descriptionId = candidate.getAttribute("aria-describedby");
    expect(descriptionId).toBeTruthy();
    expect(document.querySelector(`#${descriptionId}`)).toHaveTextContent(
      "Brak danych o osobie dodającej.",
    );
  });

  it("accept celuje w id karty (fundament fixu stale-ID)", async () => {
    useAuthStore.setState({
      user: { role: "admin", roles: ["admin"] } as never,
    });
    useUiStore.setState({ density: "compact" } as never);
    acceptVerification.mockResolvedValue({ data: {} });

    renderBoard();
    const btn = await screen.findByTitle("Akceptuj weryfikację");
    await userEvent.click(btn);
    await waitFor(() => expect(acceptVerification).toHaveBeenCalledWith(777));
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
    expect(screen.getByRole("button", { name: /Pobierz CV/ })).toBeInTheDocument();
    expect(screen.queryByText("Przenieś do:")).toBeNull();
    expect(screen.queryByTitle("Akceptuj weryfikację")).toBeNull();
    expect(screen.queryByTitle("Odrzuć weryfikację")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Usuń Anna Kowalska z rekrutacji" }),
    ).toBeNull();
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
    expect(candidate.parentElement).toHaveClass(
      "xl:pointer-fine:p-1",
      "xl:pointer-fine:pb-6",
      "xl:pointer-fine:pt-6",
    );
    expect(candidate.parentElement?.getAttribute("title")).toContain(
      "Aleksandra Nowakowska",
    );
    expect(candidate.parentElement?.getAttribute("title")).toContain(
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

  it("kompaktuje karty od czterech etapów, aby nie przywracać scrolla", async () => {
    const columns = (
      overviewColumns() as unknown as Array<Record<string, unknown>>
    ).slice(0, 4) as never;
    renderBoard(columns);

    const board = await screen.findByTestId("pipeline-board");
    expect(board).toHaveAttribute("data-desktop-layout", "full-pipeline");
    const candidate = await screen.findByRole("link", {
      name: "Aleksandra Nowakowska",
    });
    expect(candidate.parentElement).toHaveClass("xl:pointer-fine:pt-6");
    expect(screen.getByTestId("overview-match-score-90")).toHaveTextContent("—");
    const descriptionId = candidate.getAttribute("aria-describedby");
    expect(descriptionId).toBeTruthy();
    expect(document.querySelector(`#${descriptionId}`)).toHaveTextContent(
      "Brak wyliczonego dopasowania AI.",
    );
  });

  it("zachowuje scroll i navigator dla pipeline dłuższego niż 15 etapów", async () => {
    const { container } = renderBoard(overflowColumns());

    const board = await screen.findByTestId("pipeline-board");
    expect(board).toHaveAttribute("data-desktop-layout", "scroll");
    expect(board).not.toHaveClass("xl:pointer-fine:gap-1");
    expect(container.querySelectorAll("[data-colid]")).toHaveLength(16);
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
      .find((el) => el.textContent?.includes("Wybierz etap"));
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
