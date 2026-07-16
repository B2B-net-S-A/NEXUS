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
import { beforeEach, describe, expect, it, vi } from "vitest";

const acceptVerification = vi.fn();
const kanban = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: vi.fn(() =>
      Promise.resolve({ data: { salary_max: null, pipeline_template_id: null } })
    ),
    post: vi.fn(() => Promise.resolve({ data: {} })),
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
    get: vi.fn(() => Promise.resolve({ stages: [], rejection_reasons: [] })),
    list: vi.fn(() => Promise.resolve([])),
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

function renderBoard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <KanbanBoardV2 columns={pendingColumns()} jobId={10} />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

describe("KanbanBoardV2 — pending verification card", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
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
