/**
 * Ramka „Następny etap” w doku osoby — ten sam główny krok co okno „Przesuń
 * dalej” (`planPrimaryStep`). Od 14.10.2026 osoba już w „QC CV” nie ma
 * przycisku: ramka mówi, od kiedy czeka u Delivery Leada, albo co poprawić.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => get(...a) },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: toastSuccess, showError: toastError, showToast: vi.fn() }),
}));

import { DockNextStage } from "@/components/v2/jobs/DockNextStage";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import type { MoveRequirementsResponse } from "@/lib/api/moveRequirements";
import { HAND_TO_DL_MESSAGE } from "@/lib/move-primary";

const target = { stage: "cv_sent", name: "CV wysłane", stage_def_id: 45, count: 0, items: [] };

function respond(data: Partial<MoveRequirementsResponse>) {
  get.mockResolvedValue({
    data: {
      from_column: "cv_qc",
      to_column: "cv_sent",
      skipped_columns: [],
      items: [],
      primary: { kind: "hand_to_dl", label: "Przekaż Delivery Leadowi", target_stage_def_id: null },
      owner_note: "CV wysyła Delivery Lead — trafi do jego „Czeka na Ciebie”.",
      ...data,
    },
  });
}

function renderFrame(item?: Partial<KanbanItem>, overrides: Partial<React.ComponentProps<typeof DockNextStage>> = {}) {
  const props = {
    candidateId: 7,
    jobId: 3,
    target: target as never,
    readOnly: false,
    onMove: vi.fn(),
    onMoveToStageDef: vi.fn(),
    onAction: vi.fn(),
    canAct: () => true,
    item: item ? ({ id: 11, candidate_id: 7, stage: "interview", ...item } as KanbanItem) : undefined,
    ...overrides,
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <DockNextStage {...props} />
    </QueryClientProvider>,
  );
  return props;
}

describe("DockNextStage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("osoba w „QC CV” z gotowym QC: „Czeka u Delivery Leada od …”, bez przycisku i bez „Czeka na Ciebie”", async () => {
    respond({});
    const now = new Date().toISOString();
    renderFrame({ moved_at: now, qc: { status: "passed", blocking_failed: 0, ok_at: now } });
    const status = await screen.findByTestId("dock-next-stage-waiting");
    expect(status).toHaveTextContent("Czeka u Delivery Leada od dziś.");
    expect(screen.queryByRole("button", { name: /Przekaż Delivery Leadowi/ })).toBeNull();
    expect(screen.queryByText(/Czeka na Ciebie/)).toBeNull();
  });

  it("QC do poprawy: ramka mówi rekruterowi, co zrobić, zanim DL zobaczy CV", async () => {
    respond({});
    renderFrame({ qc: { status: "failed", blocking_failed: 3 } });
    expect(await screen.findByTestId("dock-next-stage-waiting")).toHaveTextContent(
      "QC: 3 do poprawy — popraw CV, zanim Delivery Lead je zobaczy.",
    );
  });

  it("bez karty z Tablicy — zdanie zawsze prawdziwe, bez czasu", async () => {
    respond({});
    renderFrame();
    expect(await screen.findByTestId("dock-next-stage-waiting")).toHaveTextContent(
      "Osoba jest w „QC CV” — trafi do Delivery Leada, gdy QC przejdzie.",
    );
  });

  it("ze „Zweryfikowanego” przekazanie dalej działa: ruch na etap QC i komunikat bez „Czeka na Ciebie”", async () => {
    respond({
      from_column: "verified",
      primary: { kind: "hand_to_dl", label: "Przekaż Delivery Leadowi", target_stage_def_id: 41 },
    });
    const props = renderFrame({ stage: "verified" });
    await userEvent.click(await screen.findByRole("button", { name: /Przekaż Delivery Leadowi/ }));
    expect(props.onMoveToStageDef).toHaveBeenCalledWith(41);
    expect(toastSuccess).toHaveBeenCalledWith(HAND_TO_DL_MESSAGE);
    expect(screen.queryByTestId("dock-next-stage-waiting")).toBeNull();
  });
});
