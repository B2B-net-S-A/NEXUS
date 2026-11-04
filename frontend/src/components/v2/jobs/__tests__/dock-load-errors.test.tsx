/**
 * Runda 10 (R10-N15-3): notatki w warsztacie i historia w doku decyzji po
 * rozmowie — awaria odczytu to komunikat z „Ponów”, nie „Brak …”.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => apiGet(...a),
    post: vi.fn(),
  },
  extractErrorMsg: () => "Błąd",
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { DockNotesPanel } from "@/components/v2/jobs/workbench-chrome";
import { InterviewDecisionDock } from "@/components/v2/jobs/InterviewDecisionDock";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{node}</TooltipProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  apiGet.mockReset();
});

describe("DockNotesPanel", () => {
  it("awaria notatek to komunikat z Ponów, a po udanym odczycie — pusty stan", async () => {
    const user = userEvent.setup();
    apiGet.mockRejectedValueOnce(new Error("500"));
    wrap(<DockNotesPanel candidateId={42} jobId={10} readOnly />);

    expect(await screen.findByText(/Nie udało się wczytać: notatki/)).toBeTruthy();
    expect(screen.queryByText(/Brak notatek dla tej rekrutacji/)).toBeNull();

    apiGet.mockResolvedValueOnce({ data: { items: [] } });
    await user.click(screen.getByRole("button", { name: "Ponów" }));
    expect(await screen.findByText(/Brak notatek dla tej rekrutacji/)).toBeTruthy();
  });
});

describe("InterviewDecisionDock — Historia", () => {
  it("awaria historii to komunikat, nie „Brak zapisanych ruchów”", async () => {
    const user = userEvent.setup();
    apiGet.mockRejectedValue(new Error("500"));
    const item = {
      id: 501,
      candidate_id: 42,
      stage: "client_interview",
      name: "Anna",
      lastname: "Kowalska",
      days_in_stage: 1,
    } as KanbanItem;
    wrap(
      <InterviewDecisionDock
        item={item}
        jobId={10}
        jobTitle="Senior Java"
        currentStageLabel="Rozmowa u klienta"
        moveTargets={[]}
        readOnly
        onClose={vi.fn()}
        onMoveTo={vi.fn()}
        onTerminal={vi.fn()}
        rejectedColumn={null}
        withdrawnColumn={null}
        stageLabel={(row) => row.stage}
      />,
    );

    await user.click(screen.getByRole("tab", { name: /Historia/ }));
    expect(await screen.findByText(/Nie udało się wczytać: historia ruchów/)).toBeTruthy();
    expect(screen.queryByText(/Brak zapisanych ruchów/)).toBeNull();
  });
});
