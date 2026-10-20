/**
 * „Umów rozmowę i prepy” (20.10.2026, PR 2): termin od klienta + oba prepy
 * z podpowiedzi kalendarza jednym przyciskiem; okno klienta z godziną.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PickInterviewDialog } from "@/components/calendar/cycle/PickInterviewDialog";
import type { PrepSuggestions } from "@/lib/api/prepMeetings";
import type { PairInfo, SlotRequest } from "@/lib/interview-cycle";

const mocks = vi.hoisted(() => ({
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() },
  chooseSlot: vi.fn(),
  suggestions: vi.fn(),
  createPrep: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("@/lib/api/interviewCycle", () => ({
  interviewCycleApi: { chooseSlot: mocks.chooseSlot },
}));
vi.mock("@/lib/api/prepMeetings", async (orig) => {
  const real = await orig<typeof import("@/lib/api/prepMeetings")>();
  return {
    ...real,
    prepMeetingsApi: { ...real.prepMeetingsApi, suggestions: mocks.suggestions, create: mocks.createPrep },
  };
});
vi.mock("@/store/auth", async (orig) => {
  const real = await orig<typeof import("@/store/auth")>();
  return {
    ...real,
    useAuthStore: (sel: (s: { user: unknown }) => unknown) => sel({ user: { id: 7 } }),
  };
});

const pair: PairInfo = {
  candidate_id: 5,
  candidate_name: "Anna Test",
  candidate_email: null,
  candidate_phone: "+48 500 000 000",
  job_id: 9,
  job_title: "Java Dev",
  client_id: 3,
  client_name: "Klient",
};

const request: SlotRequest = {
  id: 11,
  status: "awaiting_recruiter",
  slots: [
    { start: "2031-06-12T12:30:00Z", end: "2031-06-12T13:15:00Z" },
    // Okno 9:00–12:00 czasu przeglądarki zapisane w UTC.
    {
      start: new Date(2031, 5, 13, 9, 0).toISOString(),
      end: new Date(2031, 5, 13, 9, 45).toISOString(),
      window_end: new Date(2031, 5, 13, 12, 0).toISOString(),
    },
  ],
  chosen_index: null,
  respond_by: null,
  recruiter_id: 7,
  created_by: 1,
  duration_minutes: 45,
  note: "Teams · Marta",
  event_id: null,
};

const suggestions: PrepSuggestions = {
  enabled: true,
  preps: [
    {
      prep_no: 1,
      organizer: { id: 2, name: "Ewa DL" },
      calendar: "ok",
      scheduled_start: null,
      minutes: 45,
      options: [
        { start: "2031-06-11T14:00:00Z", end: "2031-06-11T14:45:00Z" },
        { start: "2031-06-11T15:00:00Z", end: "2031-06-11T15:45:00Z" },
      ],
    },
    {
      prep_no: 2,
      organizer: { id: 7, name: "Kasia Rekruter" },
      calendar: "unavailable",
      scheduled_start: null,
      minutes: 45,
      options: [{ start: "2031-06-12T10:30:00Z", end: "2031-06-12T11:15:00Z" }],
    },
  ],
};

function renderDialog(onInvalidate = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PickInterviewDialog open onOpenChange={() => {}} pair={pair} request={request} onInvalidate={onInvalidate} />
    </QueryClientProvider>,
  );
  return screen.getByRole("dialog", { name: "Umów rozmowę i prepy" });
}

describe("PickInterviewDialog", () => {
  beforeEach(() => {
    mocks.chooseSlot.mockReset().mockResolvedValue({});
    mocks.suggestions.mockReset().mockResolvedValue(suggestions);
    mocks.createPrep.mockReset().mockResolvedValue({});
    mocks.toast.showError.mockReset();
    mocks.toast.showSuccess.mockReset();
  });

  it("termin + oba prepy jednym przyciskiem; planujący jest na liście zaproszonych Prepu 1", async () => {
    const dialog = renderDialog();
    expect(within(dialog).getByRole("link", { name: "+48 500 000 000" })).toHaveAttribute("href", "tel:+48 500 000 000");
    fireEvent.click(within(dialog).getAllByRole("radio", { name: /.+/ })[0]);
    expect(await within(dialog).findByText("kalendarz sprawdzony")).toBeInTheDocument();
    expect(within(dialog).getByText(/kalendarz niedostępny/)).toBeInTheDocument();
    expect(mocks.suggestions).toHaveBeenCalledWith(
      expect.objectContaining({ candidateId: 5, jobId: 9, interviewStart: "2031-06-12T12:30:00.000Z" }),
    );
    // Polecana godzina zaznaczona od razu; rekruter wybiera drugą dla Prepu 1.
    const prep1 = within(dialog).getByRole("radiogroup", { name: "Godzina Prepu 1" });
    fireEvent.click(within(prep1).getAllByRole("radio")[1]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Wybierz termin i zaproś na prepy (2)" }));

    await waitFor(() => expect(mocks.createPrep).toHaveBeenCalledTimes(2));
    expect(mocks.chooseSlot).toHaveBeenCalledWith(11, 0, null);
    expect(mocks.createPrep.mock.calls[0][0]).toMatchObject({
      prep_no: 1,
      organizer_user_id: 2,
      start: "2031-06-11T15:00:00Z",
      attendee_user_ids: [7],
    });
    expect(mocks.createPrep.mock.calls[1][0]).toMatchObject({ prep_no: 2, organizer_user_id: 7, attendee_user_ids: [] });
    expect(mocks.toast.showSuccess).toHaveBeenCalledWith(expect.stringContaining("(2)"));
  });

  it("„Zaplanuję później” i „Tylko termin” nie wysyłają zaproszeń", async () => {
    const dialog = renderDialog();
    fireEvent.click(within(dialog).getAllByRole("radio", { name: /.+/ })[0]);
    const prep2 = await within(dialog).findByRole("radiogroup", { name: "Godzina Prepu 2" });
    fireEvent.click(within(prep2).getByRole("radio", { name: "Zaplanuję później" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Tylko termin" }));
    await waitFor(() => expect(mocks.chooseSlot).toHaveBeenCalled());
    expect(mocks.createPrep).not.toHaveBeenCalled();
  });

  it("okno klienta: godzina z kandydatem idzie do wyboru, poza oknem nie da się wysłać", async () => {
    const dialog = renderDialog();
    fireEvent.click(within(dialog).getAllByRole("radio", { name: /okno/ })[0]);
    const time = within(dialog).getByLabelText("Godzina z kandydatem");
    fireEvent.change(time, { target: { value: "11:30" } });
    expect(within(dialog).getByText(/Między 09:00 a 11:15/)).toBeInTheDocument();
    fireEvent.change(time, { target: { value: "10:30" } });
    await within(dialog).findByText("kalendarz sprawdzony");
    fireEvent.click(within(dialog).getByRole("button", { name: "Tylko termin" }));
    await waitFor(() =>
      expect(mocks.chooseSlot).toHaveBeenCalledWith(11, 1, new Date(2031, 5, 13, 10, 30).toISOString()),
    );
  });

  it("nieudany prep nie cofa terminu i mówi, który nie powstał", async () => {
    mocks.createPrep.mockImplementation((body: { prep_no: number }) =>
      body.prep_no === 2 ? Promise.reject(new Error("x")) : Promise.resolve({}),
    );
    const dialog = renderDialog();
    fireEvent.click(within(dialog).getAllByRole("radio", { name: /.+/ })[0]);
    await within(dialog).findByText("kalendarz sprawdzony");
    fireEvent.click(within(dialog).getByRole("button", { name: /Wybierz termin i zaproś/ }));
    await waitFor(() => expect(mocks.toast.showError).toHaveBeenCalledWith(expect.stringContaining("Prep 2")));
    expect(mocks.chooseSlot).toHaveBeenCalledTimes(1);
  });
});
