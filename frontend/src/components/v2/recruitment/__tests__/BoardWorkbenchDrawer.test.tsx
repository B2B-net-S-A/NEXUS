import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const panelProps = vi.fn();

vi.mock("@/components/v2/recruitment/PersonPanel", () => ({
  PersonPanel: (props: Record<string, unknown>) => {
    panelProps(props);
    return <div data-testid="person-panel" />;
  },
}));
vi.mock("@/hooks/usePipelineMove", () => ({
  usePipelineMove: () => ({ dialogs: <div data-testid="move-dialogs" /> }),
}));

import { BoardWorkbenchDrawer } from "@/components/v2/recruitment/BoardWorkbenchDrawer";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";

const COLUMNS = [
  {
    stage: "screening",
    stage_def_id: 3,
    label: "Screening",
    category: "internal",
    count: 1,
    items: [{ id: 501, candidate_id: 42, name: "Anna", lastname: "Nowak", stage: "screening" }],
  },
] as unknown as KanbanColumn[];

function renderDrawer(candidateId: number, onClose = vi.fn()) {
  render(
    <BoardWorkbenchDrawer
      jobId={10}
      jobTitle="Senior Java"
      columns={COLUMNS}
      candidateId={candidateId}
      section="interviews"
      onSectionChange={vi.fn()}
      onClose={onClose}
      readOnly={false}
      canWriteClientRate
      budgetHourly={150}
      rejectionReasons={[]}
      workbenchContext={{ clientId: 3, clientName: "Bank Alfa", onMoved: vi.fn(), canCloseJob: false }}
      kanbanQueryState={{ isLoading: false, isError: false, error: null, isSuccess: true, refetch: vi.fn() }}
    />,
  );
  return onClose;
}

describe("BoardWorkbenchDrawer — warsztat osoby nad Tablicą", () => {
  beforeEach(() => panelProps.mockClear());

  it("otwiera panel osoby od razu w szerokim widoku, na wskazanej sekcji", () => {
    renderDrawer(42);
    expect(screen.getByTestId("person-panel")).toBeInTheDocument();
    const props = panelProps.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    expect(props).toMatchObject({ wide: true, section: "interviews", jobId: 10, canWriteClientRate: true });
    expect((props.row as { candidateId: number }).candidateId).toBe(42);
    expect(props.workbenchContext).toMatchObject({ jobTitle: "Senior Java", budgetHourly: 150, clientName: "Bank Alfa" });
  });

  it("„Zwiń” / Esc (wyjście z szerokiego widoku) zamyka warsztat", () => {
    const onClose = renderDrawer(42);
    const props = panelProps.mock.calls.at(-1)?.[0] as { onWideChange: (wide: boolean) => void };
    props.onWideChange(false);
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("osoby, której nie ma na tablicy, nie otwiera (okna ruchu zostają)", () => {
    renderDrawer(999);
    expect(screen.queryByTestId("person-panel")).toBeNull();
    expect(screen.getByTestId("move-dialogs")).toBeInTheDocument();
  });
});
