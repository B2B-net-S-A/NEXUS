import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showToast: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import { RateChangeDialog } from "@/components/v2/rate-change/RateChangeDialog";

const VIEW = {
  candidate_id: 5,
  job_id: 9,
  current: { amount: "110", unit: "hourly", currency: "PLN", hourly: "110", label: "110 zł/h" },
  board_column: "cv_sent",
  notifies: true,
  cv_at_client: true,
  client_rate: null,
  changes: [],
};

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RateChangeDialog open onOpenChange={() => {}} candidateId={5} jobId={9} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.post.mockReset();
  Object.values(mocks.toast).forEach((fn) => fn.mockReset());
  mocks.get.mockResolvedValue({ data: VIEW });
});

describe("RateChangeDialog", () => {
  it("pokazuje bieżącą stawkę i zapisuje nową z powodem, notatką i otwartością na negocjację", async () => {
    mocks.post.mockResolvedValue({ data: { unchanged: false, change: { id: 1 } } });
    renderDialog();
    expect(await screen.findByText("110 zł/h")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nowa stawka B2B netto"), { target: { value: "125" } });
    fireEvent.click(screen.getByLabelText("Mail od kandydata"));
    fireEvent.click(screen.getByLabelText("Możliwe, warto porozmawiać"));
    fireEvent.change(screen.getByLabelText("Notatka (opcjonalnie)"), {
      target: { value: "druga oferta" },
    });
    expect(screen.getByTestId("rate-change-notify")).toHaveTextContent("DL dostanie zadanie");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz stawkę" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(mocks.post.mock.calls[0]).toEqual([
      "/api/rate-changes",
      {
        candidate_id: 5,
        job_id: 9,
        amount: "125",
        unit: "hourly",
        reason: "email",
        note: "druga oferta",
        negotiable: "maybe",
      },
    ]);
    expect(mocks.toast.showSuccess).toHaveBeenCalledWith(
      "Stawka zapisana. Delivery Lead i Head of Recruitment dostali powiadomienie.",
    );
  });

  it("pomyłka przy wpisie nie pyta o negocjację, a pusta kwota nie wychodzi do serwera", async () => {
    renderDialog();
    await screen.findByText("110 zł/h");
    fireEvent.click(screen.getByLabelText("Pomyłka przy wpisie"));
    expect(screen.queryByText("Czy kandydat zejdzie ze stawki?")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz stawkę" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wpisz nową stawkę");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("ta sama stawka to informacja, nie błąd", async () => {
    mocks.post.mockResolvedValue({ data: { unchanged: true, change: null } });
    renderDialog();
    await screen.findByText("110 zł/h");
    fireEvent.change(screen.getByLabelText("Nowa stawka B2B netto"), { target: { value: "110" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz stawkę" }));
    await waitFor(() =>
      expect(mocks.toast.showInfo).toHaveBeenCalledWith("Stawka bez zmian — taka sama jak dotąd."),
    );
  });
});
