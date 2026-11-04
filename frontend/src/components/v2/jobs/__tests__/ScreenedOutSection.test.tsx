import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ScreenedOutList, type ScreenedOutState } from "@/components/v2/jobs/ScreenedOutSection";
import type { ScreenedOutItem } from "@/lib/api/applicationScreenings";
import { mustSummary, sourceLabel } from "@/lib/api/applicationScreenings";

const ITEM: ScreenedOutItem = {
  id: 7,
  candidate_id: 70,
  name: "Anna",
  lastname: "Przykładowa",
  applied_at: "2026-09-28T09:00:00Z",
  decided_at: "2026-09-28T09:01:00Z",
  status: "done",
  verdict: "not_fit",
  source: "justjoinit",
  must_found: 0,
  must_total: 3,
  reasons: [
    { text: "Doświadczenie z księgowości, nie z programowania.", quote: "Księgowa (2019–2025)" },
  ],
};

function list(over: Partial<{ total: number; items: ScreenedOutItem[] }> = {}): ScreenedOutState {
  return { kind: "list", total: over.total ?? 1, items: over.items ?? [ITEM] };
}

describe("ScreenedOutList", () => {
  it("is collapsed by default and shows the count", () => {
    render(<ScreenedOutList state={list({ total: 4 })} readOnly={false} onAdd={vi.fn()} />);
    expect(screen.getByTestId("screened-out-count").textContent).toBe("(4)");
    expect(screen.queryByTestId("screened-out-item")).toBeNull();
    expect(screen.getByRole("button", { name: /Odrzuceni przez AI/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("expands to reasons with the CV quote and adds despite the verdict", () => {
    const onAdd = vi.fn();
    render(<ScreenedOutList state={list({ total: 3 })} readOnly={false} onAdd={onAdd} />);
    fireEvent.click(screen.getByRole("button", { name: /Odrzuceni przez AI/ }));
    expect(screen.getByText("Doświadczenie z księgowości, nie z programowania.")).toBeTruthy();
    expect(screen.getByText("„Księgowa (2019–2025)”")).toBeTruthy();
    expect(screen.getByText(/JustJoin\.IT · 0 z 3 must-have w CV/)).toBeTruthy();
    expect(screen.getByText("Pokazano 1 z 3 — najnowsze.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj mimo to: Anna Przykładowa" }));
    expect(onAdd).toHaveBeenCalledWith(ITEM);
  });

  it("hides the add button for read-only viewers", () => {
    render(<ScreenedOutList state={list()} readOnly defaultOpen onAdd={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Dodaj mimo to/ })).toBeNull();
  });

  it("renders nothing when nobody was screened out or while loading", () => {
    const { container, rerender } = render(
      <ScreenedOutList state={list({ total: 0, items: [] })} readOnly={false} />,
    );
    expect(container.innerHTML).toBe("");
    rerender(<ScreenedOutList state={{ kind: "loading" }} readOnly={false} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows a failure with retry, never an empty list", () => {
    const onRetry = vi.fn();
    render(<ScreenedOutList state={{ kind: "error", onRetry }} readOnly={false} />);
    expect(screen.getByRole("alert").textContent).toContain("Nie wczytano listy odrzuconych");
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(onRetry).toHaveBeenCalled();
  });
});

describe("screened-out helpers", () => {
  it("summarises must-haves only when the job has them", () => {
    expect(mustSummary({ must_found: 1, must_total: 4 })).toBe("1 z 4 must-have w CV");
    expect(mustSummary({ must_found: null, must_total: 0 })).toBeNull();
    expect(mustSummary({ must_found: null, must_total: null })).toBeNull();
  });

  it("names known job boards and keeps other sources as they are", () => {
    expect(sourceLabel("rocketjobs")).toBe("RocketJobs");
    expect(sourceLabel("newsletter")).toBe("newsletter");
    expect(sourceLabel(null)).toBeNull();
  });
});
