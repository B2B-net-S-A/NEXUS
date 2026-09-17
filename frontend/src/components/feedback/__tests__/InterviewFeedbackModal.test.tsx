/**
 * Formularz feedbacku po rozmowie (audyt 17.09.2026).
 *
 * * podpis kandydata z `name`/`lastname` (API), nie „#196867";
 * * istniejący wpis danej strony wypełnia formularz i zapisuje się PATCH-em —
 *   do 09.2026 modal kazał „użyć PATCH", którego nikt nie wołał;
 * * zapis odświeża kalendarz, kartę rekrutacji i powiadomienia.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getEvent: vi.fn(),
  getCandidate: vi.fn(),
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  calendarApi: { getEvent: (...a: unknown[]) => mocks.getEvent(...a) },
  candidatesApi: { get: (...a: unknown[]) => mocks.getCandidate(...a) },
  interviewFeedbackApi: {
    list: (...a: unknown[]) => mocks.list(...a),
    create: (...a: unknown[]) => mocks.create(...a),
    update: (...a: unknown[]) => mocks.update(...a),
  },
}));

import { InterviewFeedbackModal } from "@/components/feedback/InterviewFeedbackModal";

function renderModal(props: Partial<React.ComponentProps<typeof InterviewFeedbackModal>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const onSaved = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <InterviewFeedbackModal
        open
        onOpenChange={() => undefined}
        calendarEventId={77}
        onSaved={onSaved}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { invalidate, onSaved };
}

beforeEach(() => {
  Object.values(mocks).forEach((fn) => fn.mockReset());
  mocks.getEvent.mockResolvedValue({
    data: { id: 77, title: "Rozmowa u klienta", event_type: "interview", start_time: "2031-03-10T09:00:00Z", candidate_id: 5, job_id: 9, status: "completed" },
  });
  mocks.getCandidate.mockResolvedValue({
    data: { id: 5, name: "Anna", lastname: "Testowa", email: "anna@example.com" },
  });
  mocks.create.mockResolvedValue({ data: {} });
  mocks.update.mockResolvedValue({ data: {} });
});

describe("InterviewFeedbackModal", () => {
  it("podpisuje kandydata imieniem i nazwiskiem", async () => {
    mocks.list.mockResolvedValue({ data: [] });
    renderModal();
    expect(await screen.findByText(/Rozmowa u klienta — Anna Testowa/)).toBeInTheDocument();
  });

  it("istniejący wpis wypełnia formularz i zapisuje się PATCH-em z samymi polami", async () => {
    mocks.list.mockResolvedValue({
      data: [
        {
          id: 31,
          calendar_event_id: 77,
          feedback_source: "client_side",
          technical_fit: 4,
          soft_fit: 3,
          overall_fit: 4,
          decision: "on_hold",
          client_questions: null,
          feedback_summary: "Klient wraca w piątek.",
        },
      ],
    });
    const { invalidate, onSaved } = renderModal({ initialSource: "client_side" });

    expect(await screen.findByDisplayValue("Klient wraca w piątek.")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Zapisz zmiany" });
    fireEvent.click(save);

    await waitFor(() => expect(mocks.update).toHaveBeenCalledTimes(1));
    const [id, fields] = mocks.update.mock.calls[0];
    expect(id).toBe(31);
    expect(fields).toMatchObject({ decision: "on_hold", feedback_summary: "Klient wraca w piątek." });
    expect(fields).not.toHaveProperty("calendar_event_id");
    expect(fields).not.toHaveProperty("candidate_id");
    expect(mocks.create).not.toHaveBeenCalled();
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const keys = invalidate.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(keys).toContain(JSON.stringify(["calendar-events"]));
    expect(keys).toContain(JSON.stringify(["hiring-manager-feedback", 9]));
    expect(keys).toContain(JSON.stringify(["notifications"]));
    expect(keys).toContain(JSON.stringify(["interview-feedback"]));
  });

  it("brak wpisu = utworzenie z powiązaniem z wydarzeniem", async () => {
    mocks.list.mockResolvedValue({ data: [] });
    renderModal();
    await screen.findByText(/Anna Testowa/);
    fireEvent.click(screen.getByRole("button", { name: "4" }));
    fireEvent.change(screen.getByLabelText("Poziom zainteresowania"), { target: { value: "warm" } });
    fireEvent.change(screen.getByLabelText("Preferencja next step"), { target: { value: "need_info" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz feedback" }));
    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith(
        expect.objectContaining({ calendar_event_id: 77, candidate_id: 5, job_id: 9, overall_impression: 4 }),
      ),
    );
  });
});
