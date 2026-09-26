import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SlotDecisionDialog } from "@/components/calendar/cycle/SlotDialogs";
import type { PairInfo, SlotRequest } from "@/lib/interview-cycle";

const mocks = vi.hoisted(() => ({
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn(), showActionToast: vi.fn() },
  confirmSlot: vi.fn(),
  replaceableInterviews: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));
vi.mock("@/lib/api/interviewCycle", () => ({
  interviewCycleApi: {
    confirmSlot: mocks.confirmSlot,
    replaceableInterviews: mocks.replaceableInterviews,
    chooseSlot: vi.fn(),
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

const request: SlotRequest = {
  id: 11,
  status: "awaiting_dl",
  slots: [{ start: "2031-06-12T08:00:00Z", end: "2031-06-12T09:00:00Z" }],
  chosen_index: 0,
  respond_by: null,
  recruiter_id: 2,
  created_by: 1,
  duration_minutes: 60,
  note: null,
  event_id: null,
};

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SlotDecisionDialog open onOpenChange={() => {}} mode="confirm" pair={pair} request={request} />
    </QueryClientProvider>,
  );
}

describe("SlotDecisionDialog — przełożenie rozmowy (runda 6 audytu)", () => {
  beforeEach(() => {
    mocks.confirmSlot.mockReset().mockResolvedValue({ outlook: "skipped", cancelled_event_id: null });
    mocks.replaceableInterviews.mockReset();
  });

  it("bez zaznaczenia nie odwołuje poprzedniej rozmowy", async () => {
    mocks.replaceableInterviews.mockResolvedValue([
      { id: 99, start_time: "2031-06-10T08:00:00Z", end_time: "2031-06-10T09:00:00Z" },
    ]);
    renderDialog();
    expect(await screen.findByText("To kolejna rozmowa — zostaw obie")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź termin" }));
    await waitFor(() => expect(mocks.confirmSlot).toHaveBeenCalled());
    expect(mocks.confirmSlot.mock.calls[0][1].supersedes_event_id).toBeNull();
  });

  it("zaznaczone przełożenie wysyła rozmowę do odwołania", async () => {
    mocks.replaceableInterviews.mockResolvedValue([
      { id: 99, start_time: "2031-06-10T08:00:00Z", end_time: "2031-06-10T09:00:00Z" },
    ]);
    renderDialog();
    fireEvent.click(await screen.findByLabelText(/To przełożenie rozmowy z/));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź termin" }));
    await waitFor(() => expect(mocks.confirmSlot).toHaveBeenCalled());
    expect(mocks.confirmSlot.mock.calls[0][1].supersedes_event_id).toBe(99);
  });

  it("bez zaplanowanej rozmowy nie pokazuje pytania", async () => {
    mocks.replaceableInterviews.mockResolvedValue([]);
    renderDialog();
    await waitFor(() => expect(mocks.replaceableInterviews).toHaveBeenCalledWith(11));
    expect(screen.queryByText("To kolejna rozmowa — zostaw obie")).toBeNull();
  });
});
