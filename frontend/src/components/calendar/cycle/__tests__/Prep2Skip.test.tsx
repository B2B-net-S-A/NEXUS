/**
 * Rozmowa bez Prepu 2 (0480, decyzja Artura 20.10.2026) — wyjątek, nie wybór.
 *
 * Pilnowane reguły:
 * 1. Przycisk „Rozmowa bez Prepu 2…” jest tylko przy statusie `allowed`;
 *    poza wyjątkiem jedno zdanie, dlaczego go nie ma.
 * 2. Zapis wymaga powodu (przy „Inny” — opisu) i telefonu przed rozmową.
 * 3. Zapisane pominięcie pokazuje powód, autora i telefon do odhaczenia.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: { post: (...a: unknown[]) => mocks.post(...a) },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import { Prep2SkipControls } from "@/components/calendar/cycle/Prep2Skip";
import type { PairInfo, Prep2Skip, Prep2SkipStatus } from "@/lib/interview-cycle";

const PAIR: PairInfo = {
  candidate_id: 11,
  candidate_name: "Tomasz Zieliński",
  candidate_email: null,
  job_id: 22,
  job_title: "Low Code Developer",
  client_id: 3,
  client_name: "Ubezpieczenia XYZ",
};

const INTERVIEW_AT = new Date(Date.now() + 20 * 60 * 60_000).toISOString();

const SKIP: Prep2Skip = {
  id: 5,
  interview_event_id: 9,
  reason: "no_slot",
  reason_note: null,
  call_at: new Date(Date.now() + 2 * 60 * 60_000).toISOString(),
  call_done_at: null,
  call_note: null,
  created_by: 7,
  created_by_name: "Anna Rekruterka",
  created_at: new Date().toISOString(),
};

function renderControls(status: Prep2SkipStatus, skip: Prep2Skip | null = null, readOnly = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Prep2SkipControls
        pair={PAIR}
        status={status}
        skip={skip}
        remaining={["Power Apps w bankowości"]}
        interviewAt={INTERVIEW_AT}
        readOnly={readOnly}
      />
    </QueryClientProvider>,
  );
}

describe("Prep2SkipControls", () => {
  beforeEach(() => {
    mocks.post.mockReset().mockResolvedValue({ data: SKIP });
    mocks.toast.showSuccess.mockReset();
  });

  it("przycisk tylko przy wyjątku; poza nim zdanie, dlaczego go nie ma", () => {
    renderControls("too_early");
    expect(screen.getByTestId("prep2-skip-hint")).toHaveTextContent("jest czas na Prep 2");
    expect(screen.queryByRole("button", { name: /Rozmowa bez Prepu 2/ })).toBeNull();
  });

  it("słaby Prep 1 — Prep 2 obowiązkowy, bez przycisku", () => {
    renderControls("prep1_weak");
    expect(screen.getByTestId("prep2-skip-hint")).toHaveTextContent("obowiązkowy");
    expect(screen.queryByRole("button", { name: /Rozmowa bez Prepu 2/ })).toBeNull();
  });

  it("nic do pokazania, gdy Prep 2 jest w kalendarzu albo brak Prepu 1", () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <Prep2SkipControls pair={PAIR} status="not_needed" skip={null} interviewAt={INTERVIEW_AT} />
      </QueryClientProvider>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("podgląd tylko do odczytu nie dostaje przycisku", () => {
    renderControls("allowed", null, true);
    expect(screen.queryByRole("button", { name: /Rozmowa bez Prepu 2/ })).toBeNull();
  });

  it("zapis wymaga powodu, a „Inny” — opisu", async () => {
    renderControls("allowed");
    fireEvent.click(screen.getByRole("button", { name: "Rozmowa bez Prepu 2…" }));
    expect(screen.getByText("Power Apps w bankowości")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz — rozmowa bez Prepu 2" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wybierz, dlaczego");
    fireEvent.click(screen.getByLabelText("Inny powód (opisz)"));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz — rozmowa bez Prepu 2" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Opisz powód");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("bez telefonu przed rozmową nie da się zapisać", async () => {
    renderControls("allowed");
    fireEvent.click(screen.getByRole("button", { name: "Rozmowa bez Prepu 2…" }));
    fireEvent.click(screen.getByLabelText("Kandydat nie ma wolnego terminu przed rozmową"));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz — rozmowa bez Prepu 2" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("trzeba zadzwonić");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("zapis wysyła powód i termin telefonu", async () => {
    renderControls("allowed");
    fireEvent.click(screen.getByRole("button", { name: "Rozmowa bez Prepu 2…" }));
    fireEvent.click(screen.getByLabelText("Kandydat nie ma wolnego terminu przed rozmową"));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz — rozmowa bez Prepu 2" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    const [url, body] = mocks.post.mock.calls[0] as [string, Record<string, unknown>];
    expect(url).toBe("/api/interview-cycle/prep2-skip");
    expect(body).toMatchObject({ candidate_id: 11, job_id: 22, reason: "no_slot", reason_note: null });
    expect(new Date(body.call_at as string).getTime()).toBeLessThan(new Date(INTERVIEW_AT).getTime());
    await waitFor(() => expect(mocks.toast.showSuccess).toHaveBeenCalled());
  });

  it("zapisane pominięcie: powód, autor i telefon do odhaczenia", async () => {
    renderControls("skipped", SKIP);
    const summary = screen.getByTestId("prep2-skip-summary");
    expect(summary).toHaveTextContent("Bez Prepu 2: kandydat nie miał wolnego terminu");
    expect(summary).toHaveTextContent("Anna Rekruterka");
    expect(summary).toHaveTextContent("Telefon przed rozmową");
    fireEvent.click(screen.getByRole("button", { name: "Zrobione" }));
    fireEvent.change(screen.getByLabelText("Co omówiliście (opcjonalnie)"), {
      target: { value: "Omówiliśmy Power Apps." },
    });
    const done = screen.getAllByRole("button", { name: "Zrobione" }).at(-1) as HTMLElement;
    fireEvent.click(done);
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/interview-cycle/prep2-skip/5/call-done", {
        note: "Omówiliśmy Power Apps.",
      }),
    );
  });

  it("odbyty telefon nie ma już przycisku", () => {
    renderControls("skipped", { ...SKIP, call_done_at: new Date().toISOString(), call_note: "OK" });
    expect(screen.getByTestId("prep2-skip-summary")).toHaveTextContent("Telefon przed rozmową zrobiony");
    expect(screen.queryByRole("button", { name: "Zrobione" })).toBeNull();
  });
});
