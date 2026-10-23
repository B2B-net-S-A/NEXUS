/**
 * „Terminy od klienta” z wklejonego maila (20.10.2026): odczyt wypełnia
 * terminy, długość, „odpowiedz do” i notatkę; wysyła się to, co DL widzi.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SlotRequestDialog } from "@/components/calendar/cycle/SlotDialogs";
import type { PairInfo } from "@/lib/interview-cycle";
import type { SlotsFromMail } from "@/lib/interview-slot-mail";

const mocks = vi.hoisted(() => ({
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() },
  createSlots: vi.fn(),
  readSlotsFromMail: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("@/lib/api/interviewCycle", () => ({
  interviewCycleApi: {
    createSlots: mocks.createSlots,
    readSlotsFromMail: mocks.readSlotsFromMail,
  },
}));

const pair: PairInfo = {
  candidate_id: 5,
  candidate_name: "Anna Test",
  candidate_email: null,
  job_id: 7,
  job_title: "Java Dev",
  client_id: 3,
  client_name: "Klient",
};

const fromMail: SlotsFromMail = {
  status: "ok",
  message: null,
  slots: [
    { start: "2031-06-12T08:00:00Z", end: "2031-06-12T08:45:00Z", window: false, quote: "czwartek 12.06 o 10:00", warning: null },
    { start: "2031-06-13T07:00:00Z", end: "2031-06-13T10:00:00Z", window: true, quote: "piątek między 9 a 12", warning: null },
    { start: "2031-06-14T08:00:00Z", end: "2031-06-14T08:45:00Z", window: false, quote: "sobota 14.06 o 10", warning: "weekend" },
  ],
  extra_slots: 0,
  dropped: 0,
  duration_minutes: 45,
  respond_by: "2031-06-10T10:00:00Z",
  format: "online",
  location_note: "Teams",
  people: "Marta i Tomek",
  unclear: [],
};

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SlotRequestDialog open onOpenChange={() => {}} pair={pair} />
    </QueryClientProvider>,
  );
  return screen.getByRole("dialog", { name: "Terminy rozmowy od klienta" });
}

describe("SlotRequestDialog — terminy z maila klienta", () => {
  beforeEach(() => {
    mocks.createSlots.mockReset().mockResolvedValue({ move_skipped_reason: null });
    mocks.readSlotsFromMail.mockReset().mockResolvedValue(fromMail);
  });

  it("odczyt wypełnia terminy z cytatem i ostrzeżeniem, a wysyłka niesie długość i „odpowiedz do”", async () => {
    const dialog = renderDialog();
    fireEvent.change(within(dialog).getByLabelText(/Wklej maila od klienta/), {
      target: { value: "Pasuje nam czwartek 12.06 o 10:00, piątek między 9 a 12, sobota 14.06 o 10." },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Odczytaj terminy" }));

    expect(await within(dialog).findByText(/„czwartek 12.06 o 10:00”/)).toBeInTheDocument();
    expect(within(dialog).getAllByLabelText(/^Termin \d$/)).toHaveLength(3);
    expect(within(dialog).getByText(/okno do .* — godzinę ustali rekruter/)).toBeInTheDocument();
    expect(within(dialog).getByText("Termin wypada w weekend — sprawdź.")).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: "45 min" })).toHaveAttribute("aria-checked", "true");
    const note = within(dialog).getByLabelText("Notatka dla rekrutera (opcjonalnie)") as HTMLTextAreaElement;
    expect(note.value).toContain("Po stronie klienta: Marta i Tomek");
    // Tekst maila nie zostaje w oknie po odczycie.
    expect(within(dialog).queryByLabelText(/Wklej maila od klienta/)).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "Wyślij rekruterowi" }));
    await waitFor(() => expect(mocks.createSlots).toHaveBeenCalledTimes(1));
    const body = mocks.createSlots.mock.calls[0][0];
    expect(body.slots.map((s: { start: string }) => s.start)).toEqual(
      fromMail.slots.map((s) => new Date(s.start).toISOString()),
    );
    expect(body.duration_minutes).toBe(45);
    expect(body.respond_by).toBe(new Date(fromMail.respond_by as string).toISOString());
  });

  it("długość z maila spoza przycisków nie ustawia się niewidocznie (audyt 22.10, F29)", async () => {
    mocks.readSlotsFromMail.mockResolvedValue({ ...fromMail, duration_minutes: 150 });
    const dialog = renderDialog();
    fireEvent.change(within(dialog).getByLabelText(/Wklej maila od klienta/), { target: { value: "mail" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Odczytaj terminy" }));
    await within(dialog).findByText(/„czwartek 12.06 o 10:00”/);
    const checked = within(dialog)
      .getAllByRole("radio")
      .filter((el) => el.getAttribute("aria-checked") === "true");
    expect(checked.map((el) => el.textContent)).toEqual(["60 min"]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Wyślij rekruterowi" }));
    await waitFor(() => expect(mocks.createSlots).toHaveBeenCalledTimes(1));
    expect(mocks.createSlots.mock.calls[0][0].duration_minutes).toBe(60);
  });

  it("poprawka ręczna zdejmuje ostrzeżenie z terminu", async () => {
    const dialog = renderDialog();
    fireEvent.change(within(dialog).getByLabelText(/Wklej maila od klienta/), { target: { value: "mail" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Odczytaj terminy" }));
    await within(dialog).findByText("Termin wypada w weekend — sprawdź.");
    fireEvent.change(within(dialog).getByLabelText("Termin 3"), { target: { value: "2031-06-16T10:00" } });
    expect(within(dialog).queryByText("Termin wypada w weekend — sprawdź.")).toBeNull();
  });

  it("niedostępny odczyt zostawia terminy wpisane ręcznie i mówi, co zrobić", async () => {
    mocks.readSlotsFromMail.mockResolvedValue({
      ...fromMail,
      status: "unavailable",
      message: "Nie udało się odczytać terminów z maila — wpisz je ręcznie.",
      slots: [],
    });
    const dialog = renderDialog();
    const before = within(dialog).getAllByLabelText(/^Termin \d$/).map((el) => (el as HTMLInputElement).value);
    fireEvent.change(within(dialog).getByLabelText(/Wklej maila od klienta/), { target: { value: "mail" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Odczytaj terminy" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("wpisz je ręcznie");
    expect(within(dialog).getAllByLabelText(/^Termin \d$/).map((el) => (el as HTMLInputElement).value)).toEqual(before);
  });
});
