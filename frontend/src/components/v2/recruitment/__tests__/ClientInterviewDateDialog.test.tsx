/**
 * „Kiedy rozmowa u klienta?” przy przesunięciu karty (20.10.2026): termin albo
 * jawne „Nie znam jeszcze terminu”, nigdy cichy ruch bez decyzji.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ClientInterviewDateDialog } from "@/components/v2/recruitment/ClientInterviewDateDialog";
import { interviewCycleApi } from "@/lib/api/interviewCycle";
import { type SlotsFromMail, warningLabel } from "@/lib/interview-slot-mail";

afterEach(() => vi.restoreAllMocks());

function renderDialog() {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ClientInterviewDateDialog
        open
        candidateName="Anna Nowak"
        onCancel={onCancel}
        onConfirm={onConfirm}
      />
    </QueryClientProvider>,
  );
  const dialog = screen.getByRole("dialog", { name: "Kiedy rozmowa u klienta?" });
  return { dialog, onConfirm, onCancel };
}

describe("ClientInterviewDateDialog", () => {
  it("bez godziny prosi o termin albo „Nie znam jeszcze terminu”", () => {
    const { dialog, onConfirm } = renderDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Przesuń" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Nie znam jeszcze terminu");
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("termin i długość idą do ruchu", () => {
    const { dialog, onConfirm } = renderDialog();
    fireEvent.change(within(dialog).getByLabelText("Dzień"), { target: { value: "2026-10-22" } });
    fireEvent.change(within(dialog).getByLabelText("Godzina"), { target: { value: "14:00" } });
    fireEvent.change(within(dialog).getByLabelText("Długość"), { target: { value: "90" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Przesuń" }));
    expect(onConfirm).toHaveBeenCalledWith({
      start: new Date("2026-10-22T14:00").toISOString(),
      durationMinutes: 90,
    });
  });

  it("„Nie znam jeszcze terminu” przesuwa bez terminu", () => {
    const { dialog, onConfirm } = renderDialog();
    fireEvent.click(within(dialog).getByLabelText("Nie znam jeszcze terminu"));
    expect(within(dialog).getByLabelText("Godzina")).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Przesuń" }));
    expect(onConfirm).toHaveBeenCalledWith(null);
  });

  it("„Anuluj” nie przesuwa", () => {
    const { dialog, onConfirm, onCancel } = renderDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    expect(onCancel).toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("wklejony mail z kilkoma terminami: wybrany termin i długość z maila idą do ruchu", async () => {
    const result: SlotsFromMail = {
      status: "ok",
      message: null,
      slots: [
        { start: "2026-10-22T08:00:00Z", end: "2026-10-22T08:45:00Z", window: false, quote: "czwartek o 10:00", warning: null },
        { start: "2026-10-22T12:30:00Z", end: "2026-10-22T13:15:00Z", window: false, quote: "albo 14:30", warning: null },
      ],
      extra_slots: 0,
      dropped: 0,
      duration_minutes: 45,
      respond_by: null,
      format: "online",
      location_note: "Teams",
      people: null,
      unclear: [],
    };
    const read = vi.spyOn(interviewCycleApi, "readSlotsFromMail").mockResolvedValue(result);
    const { dialog, onConfirm } = renderDialog();
    fireEvent.change(within(dialog).getByLabelText(/Wklej maila od klienta/), {
      target: { value: "Pasuje nam czwartek o 10:00 albo 14:30, 45 min na Teams." },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Odczytaj terminy" }));
    const option = await within(dialog).findByRole("radio", { name: /albo 14:30/ });
    expect(read).toHaveBeenCalledWith(
      expect.objectContaining({ text: "Pasuje nam czwartek o 10:00 albo 14:30, 45 min na Teams." }),
    );
    fireEvent.click(option);
    fireEvent.click(within(dialog).getByRole("button", { name: "Przesuń" }));
    await waitFor(() =>
      expect(onConfirm).toHaveBeenCalledWith({
        start: new Date("2026-10-22T12:30:00Z").toISOString(),
        durationMinutes: 45,
      }),
    );
  });

  const oneSlot = (slot: SlotsFromMail["slots"][number]): SlotsFromMail => ({
    status: "ok",
    message: null,
    slots: [slot],
    extra_slots: 0,
    dropped: 0,
    duration_minutes: null,
    respond_by: null,
    format: null,
    location_note: null,
    people: null,
    unclear: [],
  });

  async function readMail(dialog: HTMLElement) {
    fireEvent.change(within(dialog).getByLabelText(/Wklej maila od klienta/), { target: { value: "mail" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Odczytaj terminy" }));
  }

  it("jeden termin z maila: cytat i ostrzeżenie są widoczne (audyt 22.10, F95)", async () => {
    vi.spyOn(interviewCycleApi, "readSlotsFromMail").mockResolvedValue(
      oneSlot({
        start: "2026-10-23T08:00:00Z",
        end: "2026-10-23T09:00:00Z",
        window: false,
        quote: "Zapraszamy w czwartek 23.10 o 10:00",
        warning: "weekday_mismatch",
      }),
    );
    const { dialog } = renderDialog();
    await readMail(dialog);
    expect(await within(dialog).findByText(warningLabel("weekday_mismatch") as string)).toBeInTheDocument();
    expect(within(dialog).getByText(/Zapraszamy w czwartek 23.10 o 10:00/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Godzina")).toHaveValue(
      new Date("2026-10-23T08:00:00Z").toTimeString().slice(0, 5),
    );
  });

  it("jedno okno klienta z maila: godzina pusta, podpowiedź zakresu (F95)", async () => {
    const start = new Date(2026, 9, 23, 9, 0).toISOString();
    const end = new Date(2026, 9, 23, 12, 0).toISOString();
    vi.spyOn(interviewCycleApi, "readSlotsFromMail").mockResolvedValue(
      oneSlot({ start, end, window: true, quote: "piątek między 9 a 12", warning: null }),
    );
    const { dialog, onConfirm } = renderDialog();
    await readMail(dialog);
    expect(await within(dialog).findByText(/Okno klienta 09:00–12:00/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Dzień")).toHaveValue("2026-10-23");
    expect(within(dialog).getByLabelText("Godzina")).toHaveValue("");
    fireEvent.click(within(dialog).getByRole("button", { name: "Przesuń" }));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("mail bez terminów zostawia ręczne wpisanie i mówi dlaczego", async () => {
    vi.spyOn(interviewCycleApi, "readSlotsFromMail").mockResolvedValue({
      status: "empty",
      message: "Nie znalazłem w tym tekście terminów z dniem i godziną.",
      slots: [],
      extra_slots: 0,
      dropped: 0,
      duration_minutes: null,
      respond_by: null,
      format: null,
      location_note: null,
      people: null,
      unclear: ["w czwartek rano"],
    });
    const { dialog, onConfirm } = renderDialog();
    fireEvent.change(within(dialog).getByLabelText(/Wklej maila od klienta/), {
      target: { value: "Może w czwartek rano?" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Odczytaj terminy" }));
    expect(await within(dialog).findByText(/Nie znalazłem w tym tekście terminów/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Godzina")).toHaveValue("");
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
