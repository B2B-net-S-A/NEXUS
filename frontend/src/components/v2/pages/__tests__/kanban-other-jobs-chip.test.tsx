import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OtherJobsChip, otherJobsChipLabel, showsOtherJobsChip } from "../kanban-other-jobs-chip";
import type { KanbanItem } from "../kanban-shared";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const item = {
  id: 5,
  candidate_id: 101,
  other_open_jobs: [
    { job_id: 21, title: "Angular Developer", client_name: "Ubezpieczenia Demo", column: "new" },
    { job_id: 22, title: "Frontend Lead", client_name: null, column: "screening" },
  ],
} as unknown as KanbanItem;

describe("„+N rekrutacja” na karcie Tablicy (A2)", () => {
  it("shows only in Nowi/Screening and only with other jobs", () => {
    expect(showsOtherJobsChip(item, "new")).toBe(true);
    expect(showsOtherJobsChip(item, "screening")).toBe(true);
    expect(showsOtherJobsChip(item, "verified")).toBe(false);
    expect(showsOtherJobsChip(item, null)).toBe(false);
    expect(showsOtherJobsChip({ ...item, other_open_jobs: [] } as KanbanItem, "new")).toBe(false);
  });

  it("labels the count in Polish", () => {
    expect(otherJobsChipLabel(1)).toBe("+1 rekrutacja");
    expect(otherJobsChipLabel(3)).toBe("+3 rekrutacje");
    expect(otherJobsChipLabel(5)).toBe("+5 rekrutacji");
  });

  it("opens a list with the column and a link to the card in that job", () => {
    const onCardClick = vi.fn();
    render(
      // Karta otwiera panel osoby kliknięciem — chip i okienko go nie wołają.
      <div onClick={onCardClick}>
        <OtherJobsChip item={item} fullName="Oskar Wzorcowy" />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "+2 rekrutacje — gdzie jeszcze czeka Oskar Wzorcowy" }));
    expect(screen.getByText("Oskar czeka też w 2 innych rekrutacjach")).toBeInTheDocument();
    expect(screen.getByText("Angular Developer")).toBeInTheDocument();
    expect(screen.getByText("Screening")).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "Otwórz kartę" });
    expect(links[0]).toHaveAttribute("href", "/jobs/21?candidate=101");
    fireEvent.click(screen.getByText("Angular Developer"));
    expect(onCardClick).not.toHaveBeenCalled();
  });
});
