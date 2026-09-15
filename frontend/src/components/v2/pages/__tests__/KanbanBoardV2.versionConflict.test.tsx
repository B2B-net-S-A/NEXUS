/**
 * F05 (audyt Codexa): pojedynczy ruch z tablicy odsyła wersję procesu z karty,
 * a 409 PIPELINE_VERSION_CONFLICT kończy się komunikatem, odświeżeniem tablicy
 * (oba klucze + historia doku) i BEZ automatycznego ponowienia ruchu.
 */

import * as React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const kanban = vi.fn();
const post = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: vi.fn(() =>
      Promise.resolve({ data: { salary_max: null, pipeline_template_id: null } }),
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
    acceptVerification: vi.fn(),
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
  useToast: () => ({ showActionToast: vi.fn(), showSuccess, showError }),
}));

vi.mock("@/lib/celebrate", () => ({ celebrate: vi.fn() }));

import { KanbanBoardV2 } from "@/components/v2/pages/KanbanBoardV2";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";
import { PIPELINE_VERSION_CONFLICT_MESSAGE } from "@/lib/pipeline-version-conflict";

beforeAll(() => {
  if (!HTMLElement.prototype.hasPointerCapture) {
    HTMLElement.prototype.hasPointerCapture = () => false;
    HTMLElement.prototype.setPointerCapture = () => {};
    HTMLElement.prototype.releasePointerCapture = () => {};
  }
});

function boardColumns() {
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
          lastname: "Testowy",
          stage: "screening",
          days_in_stage: 2,
          verification_status: "active",
          process_state_version: 4,
        },
      ],
    },
    {
      stage: "interview",
      name: "Interview Wewnętrzny",
      category: "internal",
      stage_def_id: 302,
      count: 0,
      items: [],
    },
  ] as never;
}

function renderBoard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>
        <KanbanBoardV2 columns={boardColumns()} jobId={10} />
      </TooltipProvider>
    </QueryClientProvider>,
  );
  return { invalidate };
}

async function clickDockPill(name: string) {
  const card = await waitFor(() => {
    const el = document.querySelector("[data-kanban-card]");
    expect(el).toBeTruthy();
    return el as HTMLElement;
  });
  fireEvent.click(card);
  const heading = await screen.findByText("Przenieś na etap");
  const pills = heading.parentElement as HTMLElement;
  fireEvent.click(within(pills).getByRole("button", { name }));
}

function moveCalls() {
  return post.mock.calls.filter((c) => c[0] === "/api/pipeline/move");
}

describe("KanbanBoardV2 — wersja procesu przy ruchu (F05)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kanban.mockResolvedValue({ data: { columns: [] } });
    useAuthStore.setState({ user: { role: "admin", roles: ["admin"] } as never });
    useUiStore.setState({ density: "cozy" } as never);
  });

  it("pojedynczy ruch z doku wysyła `expected_state_version` z karty", async () => {
    post.mockResolvedValue({ data: { id: 802, process_state_version: 5 } });
    renderBoard();

    await clickDockPill("Interview Wewnętrzny");

    await waitFor(() => expect(moveCalls()).toHaveLength(1));
    expect(moveCalls()[0][1]).toMatchObject({
      candidate_id: 61,
      job_id: 10,
      stage: "interview",
      stage_def_id: 302,
      expected_state_version: 4,
    });
    expect(showError).not.toHaveBeenCalled();
  });

  it("409 PIPELINE_VERSION_CONFLICT: komunikat, odświeżenie tablicy i doku, bez ponowienia", async () => {
    post.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            code: "PIPELINE_VERSION_CONFLICT",
            message: "Etap zmieniony przez inną osobę.",
            current_state_version: 6,
          },
        },
      },
    });
    const { invalidate } = renderBoard();

    await clickDockPill("Interview Wewnętrzny");

    await waitFor(() =>
      expect(showError).toHaveBeenCalledWith(PIPELINE_VERSION_CONFLICT_MESSAGE),
    );
    // Prawda serwera: tablica dociągnięta, oba klucze i historia doku.
    await waitFor(() => expect(kanban).toHaveBeenCalledWith(10));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", "10"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", 10] });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["candidate-stage-history", 61, 10],
    });
    // Brak automatycznego ponowienia i brak drugiego, ogólnego komunikatu.
    await new Promise((r) => setTimeout(r, 50));
    expect(moveCalls()).toHaveLength(1);
    expect(showError).toHaveBeenCalledTimes(1);
  });

  it("ruch zbiorczy (zaznaczenie + „Przenieś na etap”) NIE wysyła wersji", async () => {
    post.mockResolvedValue({ data: { id: 802, process_state_version: 5 } });
    renderBoard();
    await screen.findByTestId("pipeline-board");

    await userEvent.click(
      screen.getByRole("checkbox", { name: "Zaznacz Jan Testowy" }),
    );
    const bulkTrigger = screen
      .getAllByRole("combobox")
      .find((el) => el.textContent?.includes("Przenieś na etap"));
    await userEvent.click(bulkTrigger as Element);
    const option = (await screen.findAllByRole("option")).find((o) =>
      o.textContent?.includes("Interview Wewnętrzny"),
    );
    await userEvent.click(option as Element);

    await waitFor(() => expect(moveCalls()).toHaveLength(1));
    expect(moveCalls()[0][1]).toMatchObject({ candidate_id: 61, stage: "interview" });
    expect(moveCalls()[0][1].expected_state_version).toBeUndefined();
  });
});
