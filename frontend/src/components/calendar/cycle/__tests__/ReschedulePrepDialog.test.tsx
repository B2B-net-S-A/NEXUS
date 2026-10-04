/**
 * „Przełóż” prep po rozmowie u klienta (04.10.2026): okno startuje z danych
 * istniejącego prepu i zapisuje WYŁĄCZNIE nowy termin tego samego spotkania.
 * Do tego dnia przycisk prowadził na widok Tydzień, gdzie klik w siatkę
 * otwierał puste „Nowe wydarzenie”.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getEvent: vi.fn(),
  updateEvent: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  calendarApi: {
    getEvent: (...a: unknown[]) => mocks.getEvent(...a),
    updateEvent: (...a: unknown[]) => mocks.updateEvent(...a),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import {
  ReschedulePrepDialog,
  eventDurationMinutes,
} from "@/components/calendar/cycle/ReschedulePrepDialog";
import { defaultPrepStart } from "@/lib/prep-timing";

const PAIR = {
  candidate_id: 11,
  candidate_name: "Jan Przykładowy",
  candidate_email: "jan@example.com",
  job_id: 22,
  job_title: "Senior Java Developer",
  client_id: 33,
  client_name: "Bank Przykładowy",
};

const INTERVIEW = { start: "2031-10-06T08:00:00.000Z", end: "2031-10-06T09:00:00.000Z" };

const PREP = {
  id: 604,
  title: "Przygotowanie do spotkania z Klientem Bank Przykładowy - Jan Przykładowy",
  event_type: "prep_call",
  start_time: "2031-10-08T12:00:00.000Z",
  end_time: "2031-10-08T13:00:00.000Z",
  all_day: false,
  reminder_minutes: 15,
  status: "scheduled",
  candidate_id: 11,
  job_id: 22,
  external_source: "microsoft365",
};

function renderDialog(onOpenChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ReschedulePrepDialog
        open
        onOpenChange={onOpenChange}
        eventId={604}
        pair={PAIR}
        prepNo={1}
        interview={INTERVIEW}
      />
    </QueryClientProvider>,
  );
  return onOpenChange;
}

describe("ReschedulePrepDialog", () => {
  beforeEach(() => {
    mocks.getEvent.mockReset().mockResolvedValue({ data: PREP });
    mocks.updateEvent.mockReset().mockImplementation((_id: number, body: Record<string, string>) =>
      Promise.resolve({ data: { ...PREP, ...body } }),
    );
    mocks.toast.showSuccess.mockReset();
  });

  it("pokazuje istniejący prep i podpowiada termin przed rozmową, z jego długością", async () => {
    renderDialog();
    expect(await screen.findByText(PREP.title)).toBeInTheDocument();
    expect(mocks.getEvent).toHaveBeenCalledWith(604);
    const start = screen.getByLabelText("Nowy termin") as HTMLInputElement;
    expect(start.value).toBe(defaultPrepStart(INTERVIEW, 1, 60));
    expect((screen.getByLabelText("Czas") as HTMLSelectElement).value).toBe("60");
    // Nie ma formularza nowego wydarzenia (tytuł, typ, kandydat do wyboru).
    expect(screen.queryByLabelText("Tytuł")).toBeNull();
  });

  it("zapis przekłada TO spotkanie — PATCH tylko z nowym początkiem i końcem", async () => {
    const onOpenChange = renderDialog();
    const start = (await screen.findByLabelText("Nowy termin")) as HTMLInputElement;
    fireEvent.change(start, { target: { value: "2031-10-03T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Przełóż" }));
    await waitFor(() => expect(mocks.updateEvent).toHaveBeenCalledTimes(1));
    const [id, body] = mocks.updateEvent.mock.calls[0];
    expect(id).toBe(604);
    expect(Object.keys(body).sort()).toEqual(["end_time", "start_time"]);
    expect(body.start_time).toBe(new Date("2031-10-03T10:00").toISOString());
    expect(new Date(body.end_time).getTime() - new Date(body.start_time).getTime()).toBe(60 * 60_000);
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.toast.showSuccess).toHaveBeenCalledWith(expect.stringContaining("Prep 1 przełożony"));
  });

  it("termin po rozmowie u klienta daje ostrzeżenie", async () => {
    renderDialog();
    const start = (await screen.findByLabelText("Nowy termin")) as HTMLInputElement;
    fireEvent.change(start, { target: { value: "2031-10-09T10:00" } });
    expect(screen.getByTestId("reschedule-prep-timing-warning")).toBeInTheDocument();
  });

  it("długość spotkania: brak końca albo śmieci = 45 min", () => {
    expect(eventDurationMinutes({ start_time: PREP.start_time, end_time: undefined })).toBe(45);
    expect(eventDurationMinutes({ start_time: PREP.start_time, end_time: "x" })).toBe(45);
    expect(eventDurationMinutes(PREP)).toBe(60);
  });
});
