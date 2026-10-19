import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { MonthDay, TimesheetEntry } from "@/lib/api/hr-time";

vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: vi.fn(async () => true), confirmDialog: null }),
}));

import { EntryDialog } from "../EntryDialog";

// Audyt 19.10.2026: dzień 8 h + 2 h nadgodzin. Poprawka samego opisu nie może
// żądać uzasadnienia ani prawa do nadgodzin — suma dnia się nie zmienia.
const BASE: TimesheetEntry = {
  id: 1,
  work_date: "2031-03-05",
  hours: 8,
  project: null,
  description: "Praca",
  source: "manual",
  is_overtime: false,
  overtime_reason: null,
};
const EXTRA: TimesheetEntry = {
  ...BASE,
  id: 2,
  hours: 2,
  description: "Dyżur",
  is_overtime: true,
  overtime_reason: "Dyżur wieczorny",
};
const DAY = {
  date: "2031-03-05",
  weekday: 3,
  is_weekend: false,
  holiday: null,
  day_off: null,
  working_day: true,
  location: null,
  location_source: null,
  attendance_status: null,
  attendance_note: null,
  leave: null,
  entries: [BASE, EXTRA],
  hours: 10,
  capacity: 8,
  overtime_hours: 2,
} as MonthDay;

function renderDialog(entry: TimesheetEntry, allowOvertime: boolean) {
  const onSave = vi.fn(async () => undefined);
  render(
    <EntryDialog
      open
      onOpenChange={() => undefined}
      day={DAY}
      entry={entry}
      allowOvertime={allowOvertime}
      onSave={onSave}
    />,
  );
  fireEvent.change(screen.getByLabelText(/Opis/), { target: { value: "Poprawiony opis" } });
  fireEvent.click(screen.getByRole("button", { name: /Zapisz/ }));
  return onSave;
}

describe("EntryDialog — poprawka opisu w dniu z nadgodzinami", () => {
  it("zwykły wpis zostaje bez uzasadnienia", async () => {
    const onSave = renderDialog(BASE, true);
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ description: "Poprawiony opis", hours: 8, overtime_reason: null }),
    );
  });

  it("przełożony bez prawa do nadgodzin poprawia opis wpisu nadgodzin", async () => {
    const onSave = renderDialog(EXTRA, false);
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ hours: 2, overtime_reason: "Dyżur wieczorny" }),
    );
  });
});
