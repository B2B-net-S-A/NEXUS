import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BulkProposalsResponse } from "@/lib/candidate-search-api";

const mocks = vi.hoisted(() => ({ add: vi.fn() }));

vi.mock("@/lib/candidate-search-api", () => ({
  proposalsBulkApi: { add: (...args: unknown[]) => mocks.add(...args) },
}));

vi.mock("@/components/v2/recruitment/JobPicker", () => ({
  JobPicker: ({ onChange, scope }: { onChange: (job: { id: number; title: string }) => void; scope: string }) => (
    <button type="button" data-scope={scope} onClick={() => onChange({ id: 42, title: "Java Developer" })}>
      Wybierz Java Developer (mock)
    </button>
  ),
}));

import {
  AddToRecruitmentDialog,
  addToRecruitmentSummary,
} from "@/components/v2/recruitment/AddToRecruitmentDialog";

function renderDialog(props: Partial<React.ComponentProps<typeof AddToRecruitmentDialog>> = {}) {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const onOpenChange = vi.fn();
  const onAdded = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <AddToRecruitmentDialog
        open
        onOpenChange={onOpenChange}
        candidateIds={[5, 6]}
        source="candidate_list"
        onAdded={onAdded}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { invalidate, onOpenChange, onAdded };
}

const RESPONSE: BulkProposalsResponse = { added: [5], skipped: [{ candidate_id: 6, reason: "already_in_job" }], total_added: 1, total_skipped: 1 };

describe("AddToRecruitmentDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.add.mockResolvedValue(RESPONSE);
  });

  it("wybiera rekrutację z moich (scope=mine); bez wyboru nie da się zapisać", () => {
    renderDialog();
    expect(screen.getByText("Wybierz rekrutację dla 2 osób.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Wybierz Java Developer/ })).toHaveAttribute("data-scope", "mine");
    expect(screen.getByRole("button", { name: "Dodaj" })).toBeDisabled();
  });

  it("zapisuje przez bulk API z właściwym źródłem, bez run_id gdy go nie ma", async () => {
    const { invalidate, onOpenChange, onAdded } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.add).toHaveBeenCalledWith(42, { candidate_ids: [5, 6], source: "candidate_list" });
    expect(onAdded).toHaveBeenCalledWith({ job: { id: 42, title: "Java Developer" }, response: RESPONSE });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", "42"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", 42] });
  });

  it("Talent Radar przekazuje run_id przeglądu", async () => {
    renderDialog({ candidateIds: [5], source: "talent_radar", runId: "run-1", subject: "Wybierz rekrutację dla: Anna." });
    expect(screen.getByText("Wybierz rekrutację dla: Anna.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
    await waitFor(() => expect(mocks.add).toHaveBeenCalled());
    expect(mocks.add).toHaveBeenCalledWith(42, { candidate_ids: [5], source: "talent_radar", run_id: "run-1" });
  });

  it("403 mówi o członkostwie w zespole i zostawia okno otwarte", async () => {
    mocks.add.mockRejectedValue(Object.assign(new Error("HTTP 403"), { response: { status: 403, data: { detail: "Forbidden" } } }));
    const { onOpenChange } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie należysz do zespołu tej rekrutacji.");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("inny błąd pokazuje treść z API", async () => {
    mocks.add.mockRejectedValue(Object.assign(new Error("HTTP 422"), { response: { status: 422, data: { detail: "Rekrutacja jest zamknięta." } } }));
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Rekrutacja jest zamknięta.");
  });

  it("podsumowanie liczy dodanych i pominiętych", () => {
    const job = { id: 42, title: "Java Developer" };
    expect(addToRecruitmentSummary({ job, response: RESPONSE })).toBe("Dodano 1 osobę do „Java Developer”. Pominięto: 1.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, added: [], total_added: 0, total_skipped: 0, skipped: [] } })).toBe("Nikogo nie dodano do „Java Developer”.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, total_added: 3, total_skipped: 0 } })).toBe("Dodano 3 osoby do „Java Developer”.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, total_added: 12, total_skipped: 0 } })).toBe("Dodano 12 osób do „Java Developer”.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, total_added: 22, total_skipped: 0 } })).toBe("Dodano 22 osoby do „Java Developer”.");
  });
});
