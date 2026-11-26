import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { JobHoldDialog } from "@/components/v2/jobs/hold/JobHoldDialog";
import type { HoldPayload, JobHold } from "@/lib/job-hold";

const TODAY = "2026-11-26";

const SEARCHING: JobHold = {
  job_id: 7,
  state: "searching",
  reason: null,
  review_on: null,
  since: null,
  by_id: null,
  by_name: null,
  can_manage: true,
  recipients: [
    { user_id: 1, name: "Anna Przykładowa", people: 3 },
    { user_id: 2, name: "Bartek Testowy", people: 1 },
  ],
  my_open_report: null,
};

function setup(hold: JobHold = SEARCHING) {
  const save = vi.fn(async (_jobId: number, payload: HoldPayload) => ({
    ...hold,
    state: "on_hold",
    reason: payload.reason,
    review_on: payload.review_on,
  }));
  const onOpenChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <JobHoldDialog jobId={7} open onOpenChange={onOpenChange} hold={hold} save={save} today={TODAY} />
    </QueryClientProvider>,
  );
  return { save, onOpenChange };
}

describe("JobHoldDialog", () => {
  it("bez powodu nie zapisuje i mówi, czego brakuje", async () => {
    const { save } = setup();
    fireEvent.click(screen.getByTestId("job-hold-submit"));
    expect(await screen.findByTestId("job-hold-reason-error")).toHaveTextContent("powód");
    expect(save).not.toHaveBeenCalled();
  });

  it("„Inny…” wymaga wpisanego powodu", async () => {
    const { save } = setup();
    fireEvent.click(screen.getByRole("radio", { name: "Inny…" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Powód wstrzymania" }), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByTestId("job-hold-submit"));
    expect(await screen.findByTestId("job-hold-reason-error")).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("termin w przeszłości blokuje zapis", async () => {
    const { save } = setup();
    fireEvent.click(screen.getByRole("radio", { name: "Zmiana zakresu" }));
    fireEvent.change(screen.getByLabelText("Sprawdzę z klientem"), { target: { value: "2026-11-20" } });
    expect(screen.getByTestId("job-hold-review-error")).toHaveTextContent("przeszłości");
    fireEvent.click(screen.getByTestId("job-hold-submit"));
    expect(save).not.toHaveBeenCalled();
  });

  it("wstrzymuje z domyślnym terminem za 14 dni i powiadomieniem rekruterów", async () => {
    const { save, onOpenChange } = setup();
    expect(screen.getByLabelText("Sprawdzę z klientem")).toHaveValue("2026-12-10");
    expect(screen.getByText(/Powiadom 2 rekruterów/)).toBeInTheDocument();
    expect(screen.getByTestId("job-hold-recipients")).toHaveTextContent("Anna P. · 3 os.");
    fireEvent.click(screen.getByRole("radio", { name: "Klient wstrzymał budżet" }));
    fireEvent.click(screen.getByTestId("job-hold-submit"));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(7, {
        reason: "Klient wstrzymał budżet",
        review_on: "2026-12-10",
        notify: true,
      }),
    );
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("wstrzymaną zmienia bez ponownej wiadomości i z własnym powodem w polu", async () => {
    const { save } = setup({
      ...SEARCHING,
      state: "on_hold",
      reason: "Klient przesuwa start na luty",
      review_on: "2026-12-08",
      since: "2026-11-20T08:00:00Z",
    });
    expect(screen.getByText("Zmień powód lub termin")).toBeInTheDocument();
    expect(screen.queryByText(/Powiadom/)).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Powód wstrzymania" })).toHaveValue(
      "Klient przesuwa start na luty",
    );
    fireEvent.click(screen.getByTestId("job-hold-submit"));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith(7, {
        reason: "Klient przesuwa start na luty",
        review_on: "2026-12-08",
        notify: false,
      }),
    );
  });

  it("błąd serwera zostaje w oknie", async () => {
    const save = vi.fn(async () => {
      throw Object.assign(new Error("x"), {
        response: { status: 409, data: { detail: { code: "job_not_open", message: "Rekrutacja nie jest otwarta." } } },
      });
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <JobHoldDialog jobId={7} open onOpenChange={vi.fn()} hold={SEARCHING} save={save} today={TODAY} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Zmiana zakresu" }));
    fireEvent.click(screen.getByTestId("job-hold-submit"));
    expect(await screen.findByTestId("job-hold-save-error")).toHaveTextContent("nie jest otwarta");
  });
});
