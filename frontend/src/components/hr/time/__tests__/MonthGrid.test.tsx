import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DayLeave, MonthDay, MonthView, TimesheetEntry } from "@/lib/api/hr-time";

import { LeaveLimitNotice, MonthGrid } from "../MonthGrid";

// Zgłoszenie z 03.11.2026: wpis 8 h sprzed zgłoszenia pół dnia. Akceptujący nie
// widział pół dnia, a wpis otwierał się tylko kliknięciem w sam opis.
const ENTRY: TimesheetEntry = {
  id: 1,
  work_date: "2031-03-05",
  hours: 8,
  project: null,
  description: "Praca",
  source: "template",
  is_overtime: false,
  overtime_reason: null,
};
const HALF = {
  status: "approved",
  fraction: 0.5,
  full: false,
  paid_work: false,
  paid_hours: 0,
  label: "Przerwa w świadczeniu usług",
} as DayLeave;
const DAY = {
  date: "2031-03-05",
  weekday: 3,
  is_weekend: false,
  holiday: null,
  day_off: null,
  working_day: true,
  location: "onsite",
  location_source: "default",
  attendance_status: null,
  attendance_note: null,
  leave: HALF,
  entries: [ENTRY],
  hours: 8,
  capacity: 4,
  overtime_hours: 4,
} as MonthDay;

function view(day: MonthDay): MonthView {
  return {
    employment_type: "b2b",
    no_hours_limit: false,
    days: [day],
    totals: { working_days: 1, norm_hours: 8 },
  } as MonthView;
}

function renderGrid(day: MonthDay, editable = true) {
  const onEntryClick = vi.fn();
  render(<MonthGrid view={view(day)} today="2031-03-01" editable={editable} onEntryClick={onEntryClick} />);
  return { onEntryClick, row: within(screen.getByTestId(`day-${day.date}`)) };
}

describe("MonthGrid: pół dnia i poprawa wpisu", () => {
  it("za dużo godzin: znacznik limitu zamiast mylącego „ponad 8 h”, a pół dnia widać bez przełącznika miejsca", () => {
    const { row } = renderGrid(DAY);
    expect(row.getByText("Wpisane 8 h, można 4 h")).toBeInTheDocument();
    expect(row.queryByText(/ponad 8 h/)).toBeNull();
    expect(row.getByText("pół dnia: przerwa w świadczeniu usług")).toBeInTheDocument();
  });

  it("godziny otwierają ten sam wpis co opis", () => {
    const { onEntryClick, row } = renderGrid(DAY);
    fireEvent.click(row.getByRole("button", { name: "Popraw godziny 2031-03-05" }));
    expect(onEntryClick).toHaveBeenCalledWith(DAY, ENTRY);
  });

  it("wysłany raport i auto-wpis płatnej puli: godzin nie da się kliknąć", () => {
    const first = renderGrid(DAY, false);
    expect(first.row.queryByRole("button", { name: /Popraw godziny/ })).toBeNull();
    const auto = {
      ...DAY,
      date: "2031-03-06",
      leave: null,
      capacity: 8,
      overtime_hours: 0,
      entries: [{ ...ENTRY, source: "leave_paid" }],
    } as MonthDay;
    const second = renderGrid(auto);
    expect(second.row.queryByRole("button", { name: /Popraw godziny/ })).toBeNull();
  });
});

describe("LeaveLimitNotice", () => {
  it("pusta lista nic nie rysuje", () => {
    const { container } = render(<LeaveLimitNotice days={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("bez prawa do edycji sama informacja, z prawem przycisk na ten dzień", () => {
    const { rerender } = render(<LeaveLimitNotice days={[DAY]} />);
    expect(screen.getByRole("status")).toHaveTextContent("wpisane 8 h");
    expect(screen.queryByRole("button")).toBeNull();
    const onFix = vi.fn();
    rerender(<LeaveLimitNotice days={[DAY]} onFix={onFix} />);
    fireEvent.click(screen.getByRole("button", { name: "Skróć do 4 h" }));
    expect(onFix).toHaveBeenCalledWith(DAY);
  });
});
