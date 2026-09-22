import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const addToJob = vi.fn();
const dismiss = vi.fn();
const hookArgs = vi.fn();
let entries: unknown[] = [];

vi.mock("@/components/v2/recruitment/useJobProposals", () => ({
  useJobProposals: (...a: unknown[]) => {
    hookArgs(...a);
    return {
      entries,
      adding: false,
      dismissing: false,
      addToJob,
      dismiss,
      status: {
        inbox: { isLoading: false, isError: false },
        retryEngine: vi.fn(),
      },
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

  it("przepięcie mówi, gdzie osoba była u klienta; ✓ dodaje do Screening", () => {
    render(<BoardReviewSection jobId={5} readOnly={false} />);
    expect(screen.getByText("↻ Przepięcie")).toBeInTheDocument();
    expect(
      screen.getByText("Wysłany do klienta: mBank · Kotlin Developer · 26.08.2026"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj Osoba 1 do Screening" }));
    expect(addToJob).toHaveBeenCalledWith([1], { initialStageLegacy: "screening" });
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
    expect(screen.queryByRole("button", { name: /Screening/ })).not.toBeInTheDocument();
  });

  it("pusto — mówi to wprost", () => {
    entries = [];
    render(<BoardReviewSection jobId={5} readOnly={false} />);
    expect(screen.getByText("Nikt nie czeka na przejrzenie.")).toBeInTheDocument();
  });
});
