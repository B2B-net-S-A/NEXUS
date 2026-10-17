/**
 * Okno „Przełóż / Zmień / Odwołaj prep”.
 *
 * 04.10.2026: „Przełóż” prep po rozmowie u klienta zapisuje WYŁĄCZNIE nowy
 * termin tego samego spotkania (do tego dnia przycisk prowadził na widok
 * Tydzień, gdzie klik w siatkę otwierał puste „Nowe wydarzenie”).
 * 17.10.2026 (D1–D4): to samo okno zmienia prowadzącego i zaproszonych
 * i odwołuje prep — przez trasę prepu, więc działa też dla rekrutera, który
 * założył prep w kalendarzu Delivery Leada.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
  post: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    patch: (...a: unknown[]) => mocks.patch(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import {
  ReschedulePrepDialog,
  prepChanges,
  prepDurationMinutes,
} from "@/components/calendar/cycle/ReschedulePrepDialog";
import type { Prep } from "@/lib/api/prepMeetings";
import { defaultPrepStart, toLocalInput } from "@/lib/prep-timing";

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

const PREP: Prep = {
  event_id: 604,
  prep_no: 1,
  candidate_id: 11,
  job_id: 22,
  organizer: { id: 8, name: "Anna Prowadząca" },
  scheduled_by: { id: 7, name: "Ola Planująca" },
  attendees: [
    { email: "ola@example.com", user_id: 7, name: "Ola Planująca" },
    { email: "gosc@partner.example.com", user_id: null, name: null },
  ],
  status: "scheduled",
  can_edit: true,
  start: "2031-10-08T12:00:00.000Z",
  end: "2031-10-08T13:00:00.000Z",
  online_meeting_url: "https://teams.example.com/x",
  transcription_setup: "enabled",
  transcript_status: "waiting",
  talk_share: null,
  duration_seconds: null,
  review: null,
};

const OPTIONS = {
  enabled: true,
  auto_transcribe: true,
  suggested: { "1": { id: 8, name: "Anna Prowadząca" }, "2": { id: 7, name: "Ola Planująca" } },
  team: [
    { id: 8, name: "Anna Prowadząca" },
    { id: 7, name: "Ola Planująca" },
  ],
  people: [
    { id: 8, name: "Anna Prowadząca", role: "delivery_lead", in_team: true },
    { id: 7, name: "Ola Planująca", role: "recruiter", in_team: true },
    { id: 9, name: "Marek Spoza", role: "delivery_lead", in_team: false },
  ],
  notice: "",
};

function renderDialog(
  mode: "late" | "edit" | "cancel" = "late",
  prep: Prep = PREP,
  onOpenChange = vi.fn(),
) {
  mocks.get.mockImplementation((url: string) =>
    Promise.resolve({ data: url.endsWith("/options") ? OPTIONS : prep }),
  );
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
        mode={mode}
      />
    </QueryClientProvider>,
  );
  return onOpenChange;
}

describe("ReschedulePrepDialog", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.patch.mockReset().mockImplementation((_url: string, body: Record<string, unknown>) =>
      Promise.resolve({ data: { ...PREP, ...body } }),
    );
    mocks.post.mockReset().mockResolvedValue({ data: { ...PREP, status: "cancelled" } });
    mocks.toast.showSuccess.mockReset();
  });

  it("prep po rozmowie: podpowiada termin przed nią, z długością prepu", async () => {
    renderDialog("late");
    expect(await screen.findByText(/prowadzi Anna Prowadząca/)).toBeInTheDocument();
    expect(screen.getByText(/założony przez: Ola Planująca/)).toBeInTheDocument();
    expect(mocks.get).toHaveBeenCalledWith("/api/interview-cycle/preps/604");
    const start = screen.getByLabelText("Termin") as HTMLInputElement;
    expect(start.value).toBe(defaultPrepStart(INTERVIEW, 1, 60));
    expect((screen.getByLabelText("Czas") as HTMLSelectElement).value).toBe("60");
  });

  it("„Przełóż” wysyła tylko nowy początek i koniec trasą prepu", async () => {
    const onOpenChange = renderDialog("late");
    const start = (await screen.findByLabelText("Termin")) as HTMLInputElement;
    fireEvent.change(start, { target: { value: "2031-10-03T10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Przełóż" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(1));
    const [url, body] = mocks.patch.mock.calls[0];
    expect(url).toBe("/api/interview-cycle/preps/604");
    expect(Object.keys(body).sort()).toEqual(["end", "start"]);
    expect(body.start).toBe(new Date("2031-10-03T10:00").toISOString());
    expect(new Date(body.end).getTime() - new Date(body.start).getTime()).toBe(60 * 60_000);
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.toast.showSuccess).toHaveBeenCalledWith(expect.stringContaining("Prep 1 przełożony"));
  });

  it("termin po rozmowie u klienta daje ostrzeżenie", async () => {
    renderDialog("late");
    const start = (await screen.findByLabelText("Termin")) as HTMLInputElement;
    fireEvent.change(start, { target: { value: "2031-10-09T10:00" } });
    expect(screen.getByTestId("reschedule-prep-timing-warning")).toBeInTheDocument();
  });

  it("„Zmień”: zaczyna od obecnego terminu, zmiana zaproszonych wysyła pełną listę", async () => {
    renderDialog("edit");
    const start = (await screen.findByLabelText("Termin")) as HTMLInputElement;
    expect(start.value).toBe(toLocalInput(new Date(PREP.start)));
    fireEvent.click(await screen.findByRole("button", { name: "Usuń gosc@partner.example.com" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(1));
    const [, body] = mocks.patch.mock.calls[0];
    expect(body).toEqual({ attendee_user_ids: [7], attendee_emails: [] });
  });

  it("inny prowadzący: ostrzeżenie o nowym zaproszeniu i organizer w PATCH", async () => {
    renderDialog("edit");
    const select = (await screen.findByLabelText("Prowadzi")) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "7" } });
    expect(screen.getByText(/nowe zaproszenie z kalendarza: Ola Planująca/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(1));
    const [, body] = mocks.patch.mock.calls[0];
    expect(body.organizer_user_id).toBe(7);
    // Nowy prowadzący nie jest już zaproszonym.
    expect(body.attendee_user_ids).toEqual([]);
  });

  it("bez zmian = zamyka okno bez zapisu", async () => {
    const onOpenChange = renderDialog("edit");
    fireEvent.click(await screen.findByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.patch).not.toHaveBeenCalled();
  });

  it("„Odwołaj”: wiadomość trafia do odwołania", async () => {
    const onOpenChange = renderDialog("cancel");
    const comment = (await screen.findByLabelText(/Wiadomość w odwołaniu/)) as HTMLTextAreaElement;
    fireEvent.change(comment, { target: { value: "Kandydat poprosił o inny termin." } });
    fireEvent.click(screen.getByRole("button", { name: "Odwołaj prep" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(mocks.post).toHaveBeenCalledWith("/api/interview-cycle/preps/604/cancel", {
      comment: "Kandydat poprosił o inny termin.",
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.toast.showSuccess).toHaveBeenCalledWith(expect.stringContaining("Prep 1 odwołany"));
  });

  it("osoba spoza pary widzi, kto może zmienić prep, i nie ma zapisu", async () => {
    renderDialog("edit", { ...PREP, can_edit: false });
    expect(await screen.findByText(/Ten prep mogą zmienić/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz zmiany" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Odwołaj prep" })).toBeNull();
  });

  it("czyste: długość prepu i brak zmian", () => {
    expect(prepDurationMinutes({ start: PREP.start, end: null })).toBe(45);
    expect(prepDurationMinutes({ start: PREP.start, end: "x" })).toBe(45);
    expect(prepDurationMinutes(PREP)).toBe(60);
    expect(
      prepChanges(PREP, { userIds: [7], emails: [] }, {
        start: toLocalInput(new Date(PREP.start)),
        duration: 60,
        organizerId: 8,
        invitees: { userIds: [7], emails: [] },
      }),
    ).toEqual({});
  });
});
