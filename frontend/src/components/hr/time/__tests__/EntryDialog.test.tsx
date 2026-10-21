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

// Decyzja Artura 21.10.2026: przy B2B i zleceniu „godziny ponad 8 h”, nie
// „nadgodziny” (bramka uprawnienia zostaje); przy UoP słowa bez zmian.
describe("EntryDialog — słowa godzin ponad 8 h według formy", () => {
  function openNewEntry(form: "uop" | "b2b" | "zlecenie", allowOvertime: boolean) {
    const onSave = vi.fn(async () => undefined);
    render(
      <EntryDialog
        open
        onOpenChange={() => undefined}
        day={{ ...DAY, entries: [BASE], hours: 8, overtime_hours: 0 }}
        entry={null}
        allowOvertime={allowOvertime}
        form={form}
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByLabelText(/Godziny/), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText(/Opis/), { target: { value: "Wdrożenie" } });
    return onSave;
  }

  it("UoP: „Uzasadnienie nadgodzin”", () => {
    openNewEntry("uop", true);
    expect(screen.getByLabelText("Uzasadnienie nadgodzin")).toBeInTheDocument();
    expect(screen.getByText(/napisz, czym były nadgodziny/)).toBeInTheDocument();
  });

  it.each(["b2b", "zlecenie"] as const)("%s: „Czego dotyczyły godziny ponad 8 h”", (form) => {
    openNewEntry(form, true);
    expect(screen.getByLabelText("Czego dotyczyły godziny ponad 8 h")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Zapisz/ }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Dopisz, czego dotyczyły godziny ponad 8 h (co najmniej 5 znaków).",
    );
    expect(document.body.textContent).not.toMatch(/nadgodzin/i);
  });

  it("B2B bez uprawnienia: komunikat bez „nadgodzin”", () => {
    openNewEntry("b2b", false);
    fireEvent.click(screen.getByRole("button", { name: /Zapisz/ }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Godziny ponad 8 h wpisuje osoba z uprawnieniem do godzin ponad 8 h albo Kadry.",
    );
    expect(document.body.textContent).not.toMatch(/nadgodzin/i);
  });
});
