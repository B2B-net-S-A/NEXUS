/**
 * Runda 10 (R10-N15-11): odwołanie albo zakończenie wydarzenia w widoku Tydzień
 * odświeża też Tablicę „Rozmowy u klienta” (klucz `["interview-cycle"]`).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  cancelEvent: vi.fn(),
  deleteEvent: vi.fn(),
  updateEvent: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showToast: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
  calendarApi: {
    cancelEvent: (...a: unknown[]) => mocks.cancelEvent(...a),
    deleteEvent: (...a: unknown[]) => mocks.deleteEvent(...a),
    updateEvent: (...a: unknown[]) => mocks.updateEvent(...a),
  },
}));

vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

vi.mock("@/components/ConfirmDialog", () => ({
  ConfirmButton: ({
    children,
    onConfirm,
  }: {
    children?: React.ReactNode;
    onConfirm?: () => void;
  }) => (
    <button type="button" onClick={() => onConfirm?.()}>
      {children}
    </button>
  ),
}));

import { EventDetailModal } from "@/components/calendar/EventDetailModal";
import type { CalendarEvent } from "@/components/calendar/calendar-config";

const EVENT: CalendarEvent = {
  id: 41,
  title: "Rozmowa u klienta",
  event_type: "client_interview",
  start_time: "2026-09-28T09:00:00Z",
  end_time: "2026-09-28T10:00:00Z",
  all_day: false,
  candidate_id: 7,
  job_id: 5,
  reminder_minutes: 15,
  status: "scheduled",
  can_remove: true,
};

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <EventDetailModal event={EVENT} onClose={vi.fn()} onDeleted={vi.fn()} />
    </QueryClientProvider>,
  );
  return invalidate;
}

function invalidatedKeys(spy: { mock: { calls: unknown[][] } }): unknown[] {
  return spy.mock.calls.map((call) => (call[0] as { queryKey?: unknown }).queryKey);
}

beforeEach(() => {
  mocks.cancelEvent.mockReset();
  mocks.updateEvent.mockReset();
});

describe("EventDetailModal — odświeżenie Tablicy cyklu", () => {
  it("odwołanie unieważnia interview-cycle", async () => {
    mocks.cancelEvent.mockResolvedValue({
      data: { outlook: "not_applicable", event: { ...EVENT, status: "cancelled" } },
    });
    const spy = renderModal();
    fireEvent.click(screen.getByRole("button", { name: /Odwołaj/ }));
    await waitFor(() => expect(mocks.cancelEvent).toHaveBeenCalled());
    await waitFor(() => expect(invalidatedKeys(spy)).toContainEqual(["interview-cycle"]));
  });

  it("zakończenie unieważnia interview-cycle", async () => {
    mocks.updateEvent.mockResolvedValue({ data: { ...EVENT, status: "completed" } });
    const spy = renderModal();
    fireEvent.click(screen.getByRole("button", { name: /Zakończ|zakończone/i }));
    await waitFor(() => expect(mocks.updateEvent).toHaveBeenCalled());
    await waitFor(() => expect(invalidatedKeys(spy)).toContainEqual(["interview-cycle"]));
  });
});
