/**
 * Oś czasu: nazwa rekrutacji wpisu prowadzi na jej Tablicę z otwartą osobą
 * (17.10.2026 — rekruterzy kopiowali numer rekrutacji do wyszukiwarki).
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }));

import { TimelineTab } from "../Timeline";

const stageChange = {
  type: "stage_change",
  id: 5,
  stage: "screening",
  moved_by_name: "Marta Testowa",
  timestamp: "2026-10-15T10:00:00Z",
  job_id: 42700,
  job_title: "Data Analyst for Individual Rights Workflow Tool",
};

describe("TimelineTab — nazwa rekrutacji", () => {
  it("z numerem kandydata jest linkiem do Tablicy z otwartą osobą", () => {
    render(<TimelineTab items={[stageChange]} candidateId={121} />);
    expect(
      screen.getByRole("link", { name: "Data Analyst for Individual Rights Workflow Tool" }),
    ).toHaveAttribute("href", "/jobs/42700?candidate=121");
  });

  it("bez numeru kandydata albo rekrutacji zostaje samym tekstem", () => {
    const { unmount } = render(<TimelineTab items={[stageChange]} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("Data Analyst for Individual Rights Workflow Tool")).toBeInTheDocument();
    unmount();
    render(<TimelineTab items={[{ ...stageChange, job_id: null }]} candidateId={121} />);
    expect(screen.queryByRole("link")).toBeNull();
  });
});
