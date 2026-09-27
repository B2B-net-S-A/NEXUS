/**
 * Runda 10 (F08): okno „Zaplanuj Prep” podpowiada termin PRZED rozmową
 * u klienta i ostrzega, gdy prep na nią nachodzi.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/prepMeetings", () => ({
  prepMeetingsApi: { create: vi.fn() },
  usePrepOptions: () => ({
    isPending: false,
    isError: false,
    data: {
      enabled: true,
      auto_transcribe: true,
      notice: "Spotkanie jest nagrywane.",
      team: [{ id: 5, name: "Delivery Lead" }],
      suggested: { "1": { id: 5 } },
    },
  }),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));

import { PlanPrepDialog } from "@/components/calendar/cycle/PlanPrepDialog";
import { defaultPrepStart, toLocalInput } from "@/lib/prep-timing";

const PAIR = {
  candidate_id: 11,
  candidate_name: "Piotr Nowak",
  candidate_email: "piotr@example.com",
  job_id: 22,
  job_title: "Senior Java",
  client_id: 33,
  client_name: "Alior",
};

function renderDialog(interview: { start: string; end: string }) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <PlanPrepDialog open onOpenChange={() => {}} pair={PAIR} prepNo={1} interview={interview} />
    </QueryClientProvider>,
  );
}

describe("PlanPrepDialog — termin względem rozmowy u klienta", () => {
  it("podpowiada termin przed rozmową, a prep na rozmowie ostrzega", () => {
    const start = new Date();
    start.setDate(start.getDate() + 4);
    start.setHours(10, 0, 0, 0);
    const end = new Date(start.getTime() + 60 * 60_000);
    const interview = { start: start.toISOString(), end: end.toISOString() };

    renderDialog(interview);

    const input = screen.getByLabelText("Termin") as HTMLInputElement;
    expect(input.value).toBe(defaultPrepStart(interview, 1, 45));
    expect(new Date(input.value).getTime()).toBeLessThan(start.getTime());
    expect(screen.queryByTestId("prep-timing-warning")).toBeNull();

    fireEvent.change(input, { target: { value: toLocalInput(start) } });
    expect(screen.getByTestId("prep-timing-warning")).toHaveTextContent(
      /nakłada się na rozmowę u klienta/,
    );
  });
});
