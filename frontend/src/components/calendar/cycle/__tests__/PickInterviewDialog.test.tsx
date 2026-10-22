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

function renderDialog(onInvalidate = vi.fn(), req: SlotRequest = request) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PickInterviewDialog open onOpenChange={() => {}} pair={pair} request={req} onInvalidate={onInvalidate} />
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

  it("Prep 2 nie wypada o tej samej godzinie co wybrany Prep 1", async () => {
    mocks.suggestions.mockResolvedValue({
      enabled: true,
      preps: [
        { ...suggestions.preps[0], options: [
          { start: "2031-06-12T08:00:00Z", end: "2031-06-12T08:45:00Z" },
          { start: "2031-06-12T09:00:00Z", end: "2031-06-12T09:45:00Z" },
        ] },
        { ...suggestions.preps[1], options: [
          { start: "2031-06-12T09:00:00Z", end: "2031-06-12T09:45:00Z" },
          { start: "2031-06-12T10:00:00Z", end: "2031-06-12T10:45:00Z" },
        ] },
      ],
    });
    const dialog = renderDialog();
    fireEvent.click(within(dialog).getAllByRole("radio", { name: /.+/ })[0]);
    const prep1 = await within(dialog).findByRole("radiogroup", { name: "Godzina Prepu 1" });
    fireEvent.click(within(prep1).getAllByRole("radio")[1]);
    const prep2 = within(dialog).getByRole("radiogroup", { name: "Godzina Prepu 2" });
    await waitFor(() => expect(within(prep2).getAllByRole("radio")[0]).toBeDisabled());
    expect(within(prep2).getAllByRole("radio")[1]).toHaveAttribute("aria-checked", "true");
    fireEvent.click(within(dialog).getByRole("button", { name: /Wybierz termin i zaproś/ }));
    await waitFor(() => expect(mocks.createPrep).toHaveBeenCalledTimes(2));
    expect(mocks.createPrep.mock.calls[1][0].start).toBe("2031-06-12T10:00:00Z");
  });

  it("bez prepów do zaproszenia przycisk mówi, co się stanie: rozmowa trafia do kalendarza", async () => {
    mocks.suggestions.mockResolvedValue({ enabled: false, preps: [] });
    mocks.chooseSlot.mockResolvedValue({ status: "confirmed" });
    const dialog = renderDialog();
    expect(within(dialog).queryByRole("button", { name: "Wyślij do DL" })).toBeNull();
    fireEvent.click(within(dialog).getAllByRole("radio", { name: /.+/ })[0]);
    await within(dialog).findByText(/Planowanie prepów w Teams jest wyłączone/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Wpisz do kalendarza" }));
    await waitFor(() => expect(mocks.toast.showSuccess).toHaveBeenCalledWith(expect.stringContaining("w kalendarzu")));
  });

  it("termin, który już minął, jest wyłączony z podpisem i nie jest zaznaczany sam", () => {
    const past = new Date(Date.now() - 2 * 3600_000);
    const req: SlotRequest = {
      ...request,
      slots: [{ start: past.toISOString(), end: new Date(past.getTime() + 45 * 60_000).toISOString() }],
    };
    const dialog = renderDialog(vi.fn(), req);
    const radio = within(dialog).getAllByRole("radio", { name: /.+/ })[0];
    expect(radio).toBeDisabled();
    expect(radio).not.toBeChecked();
    expect(within(dialog).getByText(/termin minął/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Wpisz do kalendarza" })).toBeDisabled();
  });

  // ── „Inna godzina…” (22.10.2026) ──
  const local = (h: number, m = 0) => new Date(2031, 5, 11, h, m).toISOString();
  const withBusy: PrepSuggestions = {
    ...suggestions,
    preps: [{ ...suggestions.preps[0], busy: [{ start: local(11, 30), end: local(13) }] }, suggestions.preps[1]],
  };

  async function openManualPrep1() {
    mocks.suggestions.mockResolvedValue(withBusy);
    const dialog = renderDialog();
    fireEvent.click(within(dialog).getAllByRole("radio", { name: /.+/ })[0]);
    const prep1 = await within(dialog).findByRole("radiogroup", { name: "Godzina Prepu 1" });
    fireEvent.click(within(prep1).getByRole("radio", { name: "Inna godzina…" }));
    const panel = within(dialog).getByTestId("prep-1-manual");
    fireEvent.change(within(panel).getByLabelText("Dzień"), { target: { value: "2031-06-11" } });
    return { dialog, panel };
  }

  it("Inna godzina na zajętym: ostrzeżenie, zapis wolno — z accept_busy", async () => {
    const { dialog, panel } = await openManualPrep1();
    fireEvent.change(within(panel).getByLabelText("Godzina"), { target: { value: "11:45" } });
    expect(within(panel).getByRole("status")).toHaveTextContent("Ewa DL ma wtedy zajęte (11:30–13:00)");
    expect(within(panel).getByRole("button", { name: "13:00" })).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Wybierz termin i zaproś na prepy (2)" }));
    await waitFor(() => expect(mocks.createPrep).toHaveBeenCalledTimes(2));
    expect(mocks.createPrep.mock.calls[0][0]).toMatchObject({
      prep_no: 1,
      start: local(11, 45),
      end: local(12, 30),
      accept_busy: true,
    });
    expect(mocks.createPrep.mock.calls[1][0]).toMatchObject({ prep_no: 2, accept_busy: false });
  });

  it("„Najbliżej wolne” przestawia godzinę na wolną — bez accept_busy", async () => {
    const { dialog, panel } = await openManualPrep1();
    fireEvent.change(within(panel).getByLabelText("Godzina"), { target: { value: "11:45" } });
    fireEvent.click(within(panel).getByRole("button", { name: "13:00" }));
    expect(within(panel).getByText(/Ewa DL ma wtedy wolne/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Wybierz termin i zaproś na prepy (2)" }));
    await waitFor(() => expect(mocks.createPrep).toHaveBeenCalledTimes(2));
    expect(mocks.createPrep.mock.calls[0][0]).toMatchObject({ start: local(13), accept_busy: false });
  });

  it("Inna godzina bez godziny albo po rozmowie blokuje zaproszenia, „Tylko termin” działa", async () => {
    const { dialog, panel } = await openManualPrep1();
    const invite = within(dialog).getByRole("button", { name: /Wybierz termin i zaproś na prepy/ });
    expect(within(panel).getByText("Wpisz godzinę prepu.")).toBeInTheDocument();
    expect(invite).toBeDisabled();
    fireEvent.change(within(panel).getByLabelText("Dzień"), { target: { value: "2031-06-12" } });
    fireEvent.change(within(panel).getByLabelText("Godzina"), { target: { value: "16:00" } });
    expect(within(panel).getByRole("alert")).toHaveTextContent(/^Prep musi skończyć się przed rozmową/);
    expect(invite).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Tylko termin" })).toBeEnabled();
  });

  it("Prep 2 przy niewidocznym kalendarzu: bez paska, z informacją", async () => {
    const dialog = renderDialog();
    fireEvent.click(within(dialog).getAllByRole("radio", { name: /.+/ })[0]);
    const prep2 = await within(dialog).findByRole("radiogroup", { name: "Godzina Prepu 2" });
    fireEvent.click(within(prep2).getByRole("radio", { name: "Inna godzina…" }));
    const panel = within(dialog).getByTestId("prep-2-manual");
    fireEvent.change(within(panel).getByLabelText("Dzień"), { target: { value: "2031-06-11" } });
    fireEvent.change(within(panel).getByLabelText("Godzina"), { target: { value: "10:00" } });
    expect(within(panel).queryByRole("img")).not.toBeInTheDocument();
    expect(within(panel).getByText(/nie sprawdzimy, czy ma wtedy wolne/)).toBeInTheDocument();
  });
});

