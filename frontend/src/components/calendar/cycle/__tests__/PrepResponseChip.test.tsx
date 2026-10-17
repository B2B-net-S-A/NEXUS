/**
 * Odpowiedź kandydata przy prepie (0453, 17.10.2026, D5): plakietka
 * i „Przyjmij termin”, które przekłada TEN prep na termin kandydata.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  patch: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    patch: (...a: unknown[]) => mocks.patch(...a),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import { PrepResponseChip } from "@/components/calendar/cycle/PrepResponseChip";

const PREP = {
  event_id: 604,
  prep_no: 2,
  candidate_id: 11,
  job_id: 22,
  organizer: { id: 7, name: "Ola Planująca" },
  status: "scheduled",
  can_edit: true,
  candidate_response: "declined",
  proposed_start: "2031-10-08T15:00:00.000Z",
  proposed_end: "2031-10-08T15:45:00.000Z",
  start: "2031-10-08T12:00:00.000Z",
  end: "2031-10-08T12:45:00.000Z",
};

function renderChip(prep: Record<string, unknown>) {
  mocks.get.mockResolvedValue({ data: prep });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PrepResponseChip eventId={604} />
    </QueryClientProvider>,
  );
}

describe("PrepResponseChip", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.patch.mockReset().mockImplementation((_url: string, body: Record<string, string>) =>
      Promise.resolve({ data: { ...PREP, ...body, candidate_response: "none", proposed_start: null } }),
    );
    mocks.toast.showSuccess.mockReset();
  });

  it("propozycja kandydata: „Przyjmij termin” przekłada prep na jego termin", async () => {
    renderChip(PREP);
    expect(await screen.findByTestId("prep-response-chip")).toHaveTextContent(/Kandydat proponuje/);
    fireEvent.click(screen.getByRole("button", { name: "Przyjmij termin" }));
    await waitFor(() => expect(mocks.patch).toHaveBeenCalledTimes(1));
    expect(mocks.patch).toHaveBeenCalledWith("/api/interview-cycle/preps/604", {
      start: PREP.proposed_start,
      end: PREP.proposed_end,
    });
    await waitFor(() =>
      expect(mocks.toast.showSuccess).toHaveBeenCalledWith(expect.stringContaining("Prep 2 przełożony")),
    );
  });

  it("bez prawa zmiany — sama plakietka, bez przycisku", async () => {
    renderChip({ ...PREP, can_edit: false });
    expect(await screen.findByTestId("prep-response-chip")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Przyjmij termin" })).toBeNull();
  });

  it("przyjęte zaproszenie — zielona plakietka", async () => {
    renderChip({ ...PREP, candidate_response: "accepted", proposed_start: null, proposed_end: null });
    expect(await screen.findByTestId("prep-response-chip")).toHaveTextContent("Kandydat przyjął");
  });
});
