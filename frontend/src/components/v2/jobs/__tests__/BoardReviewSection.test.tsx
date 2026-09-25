import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const addToJob = vi.fn();
const dismiss = vi.fn();
const hookArgs = vi.fn();
let entries: unknown[] = [];
let status: Record<string, unknown> = {};
const retryEngine = vi.fn();

function okStatus(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    settled: true,
    inbox: { isLoading: false, isError: false, hasMore: false },
    similar: { isError: false },
    recommendations: { isError: false },
    run: { error: null },
    retryEngine,
    ...over,
  };
}

vi.mock("@/components/v2/recruitment/useJobProposals", () => ({
  useJobProposals: (...a: unknown[]) => {
    hookArgs(...a);
    return {
      entries,
      adding: false,
      dismissing: false,
      addToJob,
      dismiss,
      status,
    };
  },
}));

import { BoardReviewSection } from "@/components/v2/jobs/BoardReviewSection";

function entry(id: number, sources: string[], reason: string | null = null) {
  return {
    row: {
      kind: "proposal",
      key: `p-${id}`,
      candidateId: id,
      fullName: `Osoba ${id}`,
      rateLabel: null,
      availabilityLabel: null,
      fitScore: 88,
      warnings: [],
      sources,
      reason,
      isNew: false,
      previouslyDismissed: false,
      runId: null,
    },
    detail: { title: "Java Developer" },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  status = okStatus();
  entries = [
    entry(1, ["reassign"], "Wysłany do klienta: mBank · Kotlin Developer · 26.08.2026"),
    entry(2, ["full_base"]),
    ...Array.from({ length: 12 }, (_, i) => entry(10 + i, ["recommendation"])),
  ];
});

describe("Tablica — kolumna „Do przejrzenia”", () => {
  it("czyta tę samą scaloną listę co Tabela i przekazuje osoby z tablicy", () => {
    render(
      <BoardReviewSection jobId={5} readOnly={false} pipelineCandidateIds={[7]} budgetHourly={150} />,
    );
    expect(hookArgs).toHaveBeenCalledWith(
      5,
      expect.objectContaining({ pipelineCandidateIds: [7], budgetHourly: 150, readOnly: false }),
    );
    expect(screen.getByText("14")).toBeInTheDocument();
  });

  it("przepięcie mówi, gdzie osoba była u klienta; „Biorę” dodaje do Nowych", () => {
    render(<BoardReviewSection jobId={5} readOnly={false} />);
    expect(screen.getByText("↻ Przepięcie")).toBeInTheDocument();
    expect(
      screen.getByText("Wysłany do klienta: mBank · Kotlin Developer · 26.08.2026"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Biorę Osoba 1 — dodaj do Nowych na 12 h" }),
    );
    expect(addToJob).toHaveBeenCalledWith([1], { initialStageLegacy: "new" });
  });

  it("✕ pomija, a nadmiar prowadzi do pełnej listy", () => {
    render(<BoardReviewSection jobId={5} readOnly={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Pomiń Osoba 2" }));
    expect(dismiss).toHaveBeenCalledWith([2]);
    expect(screen.getByRole("link", { name: "Przejrzyj wszystkich 14 →" })).toHaveAttribute(
      "href",
      "/jobs/5?tab=people&seg=proposals",
    );
  });

  it("tylko do odczytu — bez przycisków akcji", () => {
    render(<BoardReviewSection jobId={5} readOnly />);
    expect(screen.getByText("↻ Przepięcie")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Biorę/ })).not.toBeInTheDocument();
  });

  it("pusto — mówi to wprost", () => {
    entries = [];
    render(<BoardReviewSection jobId={5} readOnly={false} />);
    expect(screen.getByText("Nikt nie czeka na przejrzenie.")).toBeInTheDocument();
  });

  // REC-02 (audyt 22.09 r2)
  it("awaria innego źródła przy pustej liście to komunikat z Ponów, nie pustka", () => {
    entries = [];
    status = okStatus({ similar: { isError: true }, run: { error: new Error("x") } });
    render(<BoardReviewSection jobId={5} readOnly={false} />);
    expect(screen.queryByText("Nikt nie czeka na przejrzenie.")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("przegląd bazy, podobne projekty");
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(retryEngine).toHaveBeenCalled();
  });

  it("częściowa awaria przy niepustej liście — lista i ostrzeżenie", () => {
    status = okStatus({ recommendations: { isError: true } });
    render(<BoardReviewSection jobId={5} readOnly={false} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Lista może być niepełna");
    expect(screen.getByText("Osoba 1")).toBeInTheDocument();
  });

  it("źródła jeszcze się wczytują — nie twierdzi, że nikt nie czeka", () => {
    entries = [];
    status = okStatus({ settled: false });
    render(<BoardReviewSection jobId={5} readOnly={false} />);
    expect(screen.getByText("Wczytuję…")).toBeInTheDocument();
    expect(screen.queryByText("Nikt nie czeka na przejrzenie.")).not.toBeInTheDocument();
  });

  it("skrzynka z kolejną stroną — licznik „N+”", () => {
    status = okStatus({ inbox: { isLoading: false, isError: false, hasMore: true } });
    render(<BoardReviewSection jobId={5} readOnly={false} />);
    expect(screen.getByTestId("board-review-count")).toHaveTextContent("14+");
    expect(screen.getByRole("link", { name: "Przejrzyj wszystkich 14+ →" })).toBeInTheDocument();
  });

  it("pasek przepięć w „Nowych” tylko otwiera panel i milczy przy zerze", () => {
    const onOpen = vi.fn();
    const { rerender } = render(
      <BoardReviewSection
        jobId={5}
        readOnly={false}
        compact
        onOpenPanel={vi.fn()}
        similarReassign={{ count: 5, clientName: "PKO BP", onOpen }}
      />,
    );
    const bar = screen.getByTestId("board-similar-reassign");
    expect(bar).toHaveTextContent("5 osób wysłanych do PKO BP w podobnych rekrutacjach");
    fireEvent.click(bar);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(addToJob).not.toHaveBeenCalled();

    rerender(
      <BoardReviewSection
        jobId={5}
        readOnly={false}
        compact
        onOpenPanel={vi.fn()}
        similarReassign={{ count: 0, clientName: "PKO BP", onOpen }}
      />,
    );
    expect(screen.queryByTestId("board-similar-reassign")).not.toBeInTheDocument();
  });
});
