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

function renderBoard(columns = pendingColumns()) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <KanbanBoardV2 columns={columns} jobId={10} />
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
    expect(await screen.findByText(/Kowalska/)).toBeTruthy();
    // …ale decyzje approvera nie.
    expect(screen.queryByTitle("Akceptuj weryfikację")).toBeNull();
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
});

describe("KanbanBoardV2 — focus na etapie", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    post.mockResolvedValue({ data: {} });
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
