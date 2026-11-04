import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AlsoFitsJob } from "@/lib/also-fits-api";

import { AlsoFitsBlock } from "../also-fits-block";
import { PickList, type PickRow } from "../pick-list";
import type { AlsoFitsRowModel, ElsewhereState } from "../useAlsoFitsJobs";

const JOBS: AlsoFitsJob[] = [
  {
    job_id: 21,
    title: "Angular Developer",
    client_name: "Ubezpieczenia Demo",
    client_reference: "ZOB-3101",
    score: 84,
    matching_must: ["Angular", "RxJS"],
    gap_must: [],
  },
  {
    job_id: 22,
    title: "Frontend Lead (Angular)",
    client_name: "Logistyka Demo",
    score: 72,
    matching_must: ["Angular"],
    gap_must: ["Prowadzenie zespołu"],
  },
];

function model(overrides: Partial<AlsoFitsRowModel> = {}, states: Record<number, ElsewhereState> = {}) {
  return {
    status: "ok" as const,
    jobs: JOBS,
    stateOf: (jobId: number) => states[jobId],
    errorOf: () => undefined,
    undoable: () => true,
    ...overrides,
  };
}

function mount(m: AlsoFitsRowModel, readOnly = false) {
  const handlers = { onAdd: vi.fn(), onUndo: vi.fn(), onRetry: vi.fn(), onRequest: vi.fn() };
  render(<AlsoFitsBlock model={m} candidateName="Oskar Wzorcowy" readOnly={readOnly} {...handlers} />);
  return handlers;
}

describe("AlsoFitsBlock — „Pasuje też do” (A1)", () => {
  it("lists jobs with score, client and must chips, and adds one or all", () => {
    const h = mount(model());
    const block = screen.getByTestId("also-fits-block");
    expect(within(block).getByText("Pasuje też do 2 innych rekrutacji")).toBeInTheDocument();
    expect(within(block).getByText("Angular Developer")).toBeInTheDocument();
    // Numer u klienta przed nazwą, jak w nagłówku rekrutacji (16.10.2026).
    expect(within(block).getByText("ZOB-3101")).toBeInTheDocument();
    expect(within(block).getByText("· Ubezpieczenia Demo")).toBeInTheDocument();
    expect(within(block).getByText("84%")).toBeInTheDocument();
    expect(within(block).getByText("✕ Prowadzenie zespołu")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Dodaj Oskar Wzorcowy też do: Frontend Lead (Angular)" }),
    );
    expect(h.onAdd).toHaveBeenCalledWith([22]);
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do wszystkich (2)" }));
    expect(h.onAdd).toHaveBeenLastCalledWith([21, 22]);
  });

  it("our consultant returning to market shows the source and the date (R2)", () => {
    mount(model({ ourConsultant: { returnsOn: "2026-10-31" } }));
    expect(screen.getByTestId("also-fits-source")).toHaveTextContent(
      "nasz konsultant · Wraca na rynek 31.10",
    );
    expect(screen.getByText("Pasuje też do 2 innych rekrutacji")).toBeInTheDocument();
  });

  it("without the returning marker there is no source line", () => {
    mount(model({ ourConsultant: null }));
    expect(screen.queryByTestId("also-fits-source")).toBeNull();
  });

  it("shows added state with undo and keeps the rest addable", () => {
    const h = mount(model({}, { 21: "added" }));
    expect(screen.getByText("Dodano")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cofnij dodanie do: Angular Developer" }));
    expect(h.onUndo).toHaveBeenCalledWith(21);
    // Zostaje jedna niedodana — bez „Dodaj do wszystkich”.
    expect(screen.queryByRole("button", { name: /Dodaj do wszystkich/ })).toBeNull();
  });

  it("hides undo after the window and shows a server refusal under the job", () => {
    mount(
      model({
        undoable: () => false,
        errorOf: (jobId) => (jobId === 22 ? "Ta osoba ma zamkniętą kartę w tej rekrutacji." : undefined),
      }, { 21: "added" }),
    );
    expect(screen.queryByRole("button", { name: /Cofnij dodanie/ })).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent("Ta osoba ma zamkniętą kartę w tej rekrutacji.");
  });

  it("says it is checking, and an outage is not an empty list", () => {
    const { unmount } = render(
      <AlsoFitsBlock
        model={model({ status: "loading", jobs: [] })}
        candidateName="Oskar"
        readOnly={false}
        onAdd={vi.fn()}
        onUndo={vi.fn()}
        onRetry={vi.fn()}
        onRequest={vi.fn()}
      />,
    );
    expect(screen.getByTestId("also-fits-loading")).toHaveTextContent("Sprawdzam inne rekrutacje…");
    unmount();
    const h = mount(model({ status: "unavailable", jobs: [] }));
    expect(screen.getByTestId("also-fits-error")).toHaveTextContent("Nie udało się sprawdzić innych rekrutacji");
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(h.onRetry).toHaveBeenCalled();
  });

  it("asks on demand when the window did not check by itself", () => {
    const h = mount(model({ status: "idle", jobs: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Sprawdź, gdzie jeszcze pasuje" }));
    expect(h.onRequest).toHaveBeenCalled();
  });

  it("renders nothing when nothing else fits", () => {
    const { container } = render(
      <AlsoFitsBlock
        model={model({ jobs: [] })}
        candidateName="Oskar"
        readOnly={false}
        onAdd={vi.fn()}
        onUndo={vi.fn()}
        onRetry={vi.fn()}
        onRequest={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("read-only viewer sees suggestions without actions", () => {
    mount(model(), true);
    for (const button of screen.getAllByRole("button", { name: /Dodaj Oskar/ })) {
      expect(button).toBeDisabled();
    }
    expect(screen.queryByRole("button", { name: /Dodaj do wszystkich/ })).toBeNull();
  });
});

describe("PickList — blok tylko pod dodaną osobą", () => {
  const base: PickRow = {
    candidateId: 1,
    fullName: "Oskar Wzorcowy",
    fitScore: 79,
    rateLabel: null,
    availabilityLabel: null,
    note: null,
    sourceLabel: null,
    warnings: [],
    alsoFits: <p>BLOK PASUJE TEŻ DO</p>,
  };

  it("renders the slot only for an added row", () => {
    render(
      <PickList
        rows={[{ ...base, addState: "added" }, { ...base, candidateId: 2, addState: null }]}
        selected={new Set()}
        onToggle={vi.fn()}
        readOnly={false}
        emptyText="Brak"
        label="Osoby"
      />,
    );
    const [added, other] = screen.getAllByRole("listitem");
    expect(within(added).getByText("BLOK PASUJE TEŻ DO")).toBeInTheDocument();
    expect(within(other).queryByText("BLOK PASUJE TEŻ DO")).toBeNull();
  });
});
