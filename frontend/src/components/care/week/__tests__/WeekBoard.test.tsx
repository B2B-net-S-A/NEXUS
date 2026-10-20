/** „Opieka · Ten tydzień”: kolumna z setkami zaległych pokazuje 8 najstarszych (prod 20.10.2026). */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WeekBoard } from "@/components/care/week/WeekBoard";
import { shiftIso } from "@/components/care/week/week-format";
import type { CareWeek, WeekContact } from "@/lib/api/care";

function contact(id: number, dueOn: string): WeekContact {
  return {
    contract_id: id,
    candidate_id: id,
    candidate_name: `Konsultant ${id}`,
    client_id: 3,
    client_name: "Firma Testowa",
    job_title: null,
    start_date: null,
    end_date: null,
    owner: { id: 7, name: "Opiekunka Testowa" },
    reasons: [
      { kind: "day_30", label: "Dzień 30", due_on: dueOn, overdue: true, plan_item_id: id, from_conversation_on: null },
    ],
    due_on: dueOn,
    overdue: true,
    overdue_days: 1,
    plan_item_id: id,
    manager: null,
    last_conversation: null,
    signals: [],
    front_office: { reasons: [], handed_off_on: null },
  } as WeekContact;
}

const contacts = Array.from({ length: 482 }, (_, i) => contact(1000 + i, shiftIso("2026-10-19", -1 - i)));
const data = {
  week: { from: "2026-10-19", to: "2026-10-23", today: "2026-10-20", is_current: true },
  scope: "all",
  contacts,
  feedback: [],
  feedback_visible: true,
  counts: { contacts: 482, overdue: 482, feedback: 0, front_office: 0 },
  can_edit: true,
  can_write_feedback: true,
} as unknown as CareWeek;

function renderBoard(selectedId: number | null = null) {
  render(
    <WeekBoard data={data} showOwner selectedId={selectedId} onOpen={vi.fn()} onTalk={vi.fn()} />,
  );
  return screen.getByRole("region", { name: "Zaległe" });
}

describe("WeekBoard — limit kolumny", () => {
  it("482 zaległe: licznik w nagłówku, 8 najstarszych kart i „Pokaż wszystkie (482)”", () => {
    const column = renderBoard();
    expect(within(column).getByText("482")).toBeInTheDocument();
    const cards = within(column).getAllByRole("button", { name: /^Oś konsultanta:/ });
    expect(cards).toHaveLength(8);
    // Najstarszy termin (najwięcej dni po) na górze.
    expect(cards[0]).toHaveAccessibleName("Oś konsultanta: Konsultant 1481");
    fireEvent.click(within(column).getByRole("button", { name: "Pokaż wszystkie (482)" }));
    expect(within(column).getAllByRole("button", { name: /^Oś konsultanta:/ })).toHaveLength(482);
    fireEvent.click(within(column).getByRole("button", { name: "Pokaż mniej" }));
    expect(within(column).getAllByRole("button", { name: /^Oś konsultanta:/ })).toHaveLength(8);
  });

  it("otwarta oś osoby spoza pierwszych 8 — jej karta jest widoczna", () => {
    const column = renderBoard(1000);
    expect(within(column).getByRole("button", { name: "Oś konsultanta: Konsultant 1000" })).toBeInTheDocument();
  });
});
