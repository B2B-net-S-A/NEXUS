/**
 * „Zmień termin” rozmowy u klienta (zgłoszenie 04.11.2026): klient przełożył
 * rozmowę na przyszły tydzień, a panel osoby pozwalał przełożyć tylko prep.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import {
  InterviewRescheduleButton,
  RescheduleInterviewDialog,
} from "@/components/calendar/cycle/RescheduleInterview";
import { toLocalInput } from "@/lib/prep-timing";

const PAIR = {
  candidate_id: 11,
  candidate_name: "Jan Przykładowy",
  candidate_email: "jan@example.com",
  job_id: 22,
  job_title: "Senior Java Developer",
  client_id: 33,
  client_name: "Bank Przykładowy",
};

const START = "2031-10-06T08:00:00.000Z";

const EVENT = {
  id: 502,
  candidate_id: 11,
  job_id: 22,
  start: START,
  end: "2031-10-06T08:30:00.000Z",
  started: false,
  can_reschedule: true,
};

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function openDialog(onOpenChange = vi.fn()) {
  wrap(
    <RescheduleInterviewDialog open onOpenChange={onOpenChange} eventId={502} pair={PAIR} />,
  );
  return onOpenChange;
}

const termInput = () => screen.findByLabelText<HTMLInputElement>("Nowy termin");

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  mocks.toast.showError.mockReset();
  mocks.toast.showSuccess.mockReset();
  mocks.get.mockResolvedValue({ data: EVENT });
});

describe("InterviewRescheduleButton", () => {
  it("osoba z pary widzi przycisk, a klik przekazuje wydarzenie", async () => {
    const onEdit = vi.fn();
    wrap(<InterviewRescheduleButton eventId={502} onEdit={onEdit} />);

    fireEvent.click(await screen.findByRole("button", { name: "Zmień termin" }));

    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(mocks.get).toHaveBeenCalledWith("/api/interview-cycle/events/502");
  });

  it("bez uprawnień serwera przycisku nie ma", async () => {
    mocks.get.mockResolvedValue({ data: { ...EVENT, can_reschedule: false } });
    wrap(<InterviewRescheduleButton eventId={502} onEdit={vi.fn()} />);

    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));

    expect(screen.queryByRole("button", { name: "Zmień termin" })).toBeNull();
  });

  it("awaria odczytu nie pokazuje przycisku", async () => {
    mocks.get.mockRejectedValue(new Error("boom"));
    wrap(<InterviewRescheduleButton eventId={502} onEdit={vi.fn()} />);

    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));

    expect(screen.queryByRole("button", { name: "Zmień termin" })).toBeNull();
  });
});

describe("RescheduleInterviewDialog", () => {
  it("startuje z obecnego terminu i długości tej rozmowy", async () => {
    openDialog();

    expect((await termInput()).value).toBe(toLocalInput(new Date(START)));
    expect(screen.getByLabelText<HTMLSelectElement>("Czas").value).toBe("30");
  });

  it("zapisuje nowy termin tego samego wydarzenia z długością", async () => {
    mocks.post.mockResolvedValue({
      data: { event_id: 502, start: "2031-10-13T08:00:00.000Z", end: "2031-10-13T08:30:00.000Z" },
    });
    const onOpenChange = openDialog();
    const next = new Date("2031-10-13T08:00:00.000Z");

    fireEvent.change(await termInput(), { target: { value: toLocalInput(next) } });
    fireEvent.click(screen.getByRole("button", { name: "Przełóż rozmowę" }));

    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/interview-cycle/events/502/reschedule", {
        start: next.toISOString(),
        duration_minutes: 30,
      }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.toast.showSuccess).toHaveBeenCalledTimes(1);
  });

  it("bez zmiany zamyka okno i nikogo nie powiadamia", async () => {
    const onOpenChange = openDialog();

    await termInput();
    fireEvent.click(screen.getByRole("button", { name: "Przełóż rozmowę" }));

    expect(mocks.post).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("pusty termin nie idzie na serwer", async () => {
    openDialog();

    fireEvent.change(await termInput(), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Przełóż rozmowę" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Podaj nowy termin rozmowy.");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("odmowa serwera zostaje w oknie, które się nie zamyka", async () => {
    mocks.post.mockRejectedValue({
      response: { status: 409, data: { detail: "Rozmowa już się zaczęła." } },
    });
    const onOpenChange = openDialog();

    fireEvent.change(await termInput(), {
      target: { value: toLocalInput(new Date("2031-10-13T08:00:00.000Z")) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Przełóż rozmowę" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Rozmowa już się zaczęła.");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("awaria odczytu mówi o błędzie, a nie pokazuje pustego formularza", async () => {
    mocks.get.mockRejectedValue(new Error("boom"));
    openDialog();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać rozmowy.",
    );
    expect(screen.queryByLabelText("Nowy termin")).toBeNull();
    expect(screen.queryByRole("button", { name: "Przełóż rozmowę" })).toBeNull();
  });
});
