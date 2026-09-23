/**
 * Bramka „telefon po rozmowie u klienta” (pipeline v4): okno zbiera debrief,
 * a pusta lista pytań wymaga jawnego „Klient nie zadawał pytań”.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    put: (...a: unknown[]) => mocks.put(...a),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import { DebriefRequiredDialog } from "@/components/v2/recruitment/DebriefRequiredDialog";

const SAVED = {
  id: 1,
  calendar_event_id: 44,
  candidate_id: 11,
  job_id: 22,
  outcome: "good",
  candidate_comment: null,
  questions: [],
  offer_acceptance: "yes",
  acceptance_condition: null,
  no_client_questions: true,
  questions_saved: 0,
};

function renderDialog(onSaved = vi.fn(), onOpenChange = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <DebriefRequiredDialog
        open
        onOpenChange={onOpenChange}
        eventId={44}
        candidateName="Piotr Nowak"
        jobId={22}
        onSaved={onSaved}
      />
    </QueryClientProvider>,
  );
  return { onSaved, onOpenChange, invalidate };
}

async function openedDialog() {
  const dialog = await screen.findByRole("dialog", {
    name: "Telefon po rozmowie — pytania klienta",
  });
  await waitFor(() => expect(within(dialog).getByLabelText("Dobrze")).not.toBeDisabled());
  return dialog;
}

describe("DebriefRequiredDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({ data: null });
  });

  it("wyjaśnia, po co są pytania, i nie wysyła pustego debriefu", async () => {
    renderDialog();
    const dialog = await openedDialog();
    expect(within(dialog).getByTestId("debrief-required-intro")).toHaveTextContent(
      /prepu następnych kandydatów.*profilu Championa/,
    );
    fireEvent.click(within(dialog).getByLabelText("Dobrze"));
    fireEvent.click(within(dialog).getByLabelText("Tak"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz i przenieś dalej" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Wpisz pytania klienta albo zaznacz, że klient ich nie zadawał.",
    );
    expect(mocks.put).not.toHaveBeenCalled();
  });

  it("„Klient nie zadawał pytań” zapisuje debrief i ponawia ruch", async () => {
    mocks.put.mockResolvedValue({ data: SAVED });
    const { onSaved, onOpenChange, invalidate } = renderDialog();
    const dialog = await openedDialog();
    fireEvent.click(within(dialog).getByLabelText("Dobrze"));
    fireEvent.click(within(dialog).getByLabelText("Tak"));
    fireEvent.click(within(dialog).getByLabelText("Klient nie zadawał pytań"));
    // Pola pytań wyłączone — „nie pytał” nie może jechać razem z pytaniami.
    expect(within(dialog).getByLabelText("Pytanie 1")).toBeDisabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz i przenieś dalej" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(mocks.put).toHaveBeenCalledWith(
      "/api/interview-cycle/events/44/debrief",
      expect.objectContaining({
        outcome: "good",
        offer_acceptance: "yes",
        questions: [],
        no_client_questions: true,
      }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", "22"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", 22] });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("pytania klienta jadą w debriefie bez flagi „nie pytał”", async () => {
    mocks.put.mockResolvedValue({
      data: { ...SAVED, questions: ["Jak skalujesz Kafkę?"], no_client_questions: false, questions_saved: 1 },
    });
    const { onSaved } = renderDialog();
    const dialog = await openedDialog();
    fireEvent.click(within(dialog).getByLabelText("Średnio"));
    fireEvent.change(within(dialog).getByLabelText("Pytanie 1"), {
      target: { value: "Jak skalujesz Kafkę?" },
    });
    fireEvent.click(within(dialog).getByLabelText("Raczej tak"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz i przenieś dalej" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(mocks.put).toHaveBeenCalledWith(
      "/api/interview-cycle/events/44/debrief",
      expect.objectContaining({
        questions: ["Jak skalujesz Kafkę?"],
        no_client_questions: false,
      }),
    );
  });

  it("odmowa serwera zostaje w oknie i nie ponawia ruchu", async () => {
    mocks.put.mockRejectedValue({
      response: { status: 422, data: { detail: "Debrief zapisuje się pod rozmową kandydata u klienta." } },
    });
    const { onSaved } = renderDialog();
    const dialog = await openedDialog();
    fireEvent.click(within(dialog).getByLabelText("Dobrze"));
    fireEvent.click(within(dialog).getByLabelText("Tak"));
    fireEvent.click(within(dialog).getByLabelText("Klient nie zadawał pytań"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz i przenieś dalej" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/pod rozmową kandydata/);
    expect(onSaved).not.toHaveBeenCalled();
  });
});
