import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  setRate: vi.fn(),
  toast: { showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showToast: vi.fn() },
}));

vi.mock("@/lib/api", () => ({
  api: { get: (...a: unknown[]) => mocks.get(...a) },
  candidatesApi: {
    setRecruitmentClientRate: (...a: unknown[]) => mocks.setRate(...a),
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => mocks.toast }));

import { ClientRateChangeDialog } from "@/components/v2/rate-change/ClientRateChangeDialog";

const REASONS = [
  { value: "client_negotiated", label: "Klient wynegocjował inną stawkę" },
  { value: "send_mistake", label: "Pomyłka przy wysyłce CV" },
  { value: "other", label: "Inny powód" },
];

const HISTORY = {
  current: { value: 150, unit: "hourly", currency: "PLN" },
  current_label: "150 zł/h",
  sent: {
    at: "2026-10-17T10:00:00Z",
    by_name: "Ewa Nowak",
    rate: { value: 150, unit: "hourly", currency: "PLN" },
    label: "150 zł/h",
  },
  changes: [],
  order_lock: null,
  can_write: true,
  reasons: REASONS,
};

function renderDialog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientRateChangeDialog
        open
        onOpenChange={() => {}}
        candidateId={5}
        jobId={9}
        candidateRate={{ value: 120, unit: "hourly" }}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.setRate.mockReset();
  Object.values(mocks.toast).forEach((fn) => fn.mockReset());
  mocks.get.mockResolvedValue({ data: HISTORY });
});

describe("ClientRateChangeDialog", () => {
  it("pokazuje kwotę wysyłki i marżę, zapisuje nową stawkę z powodem i notatką", async () => {
    mocks.setRate.mockResolvedValue({ data: {} });
    renderDialog();
    expect(await screen.findByTestId("client-rate-sent")).toHaveTextContent(
      "Wysłane do klienta: 150 zł/h · 17.10 · Ewa Nowak",
    );
    fireEvent.change(screen.getByLabelText("Nowa stawka do klienta"), {
      target: { value: "145" },
    });
    expect(screen.getByTestId("client-rate-margin")).toHaveTextContent(
      "marża po zmianie 25 zł/h (było 30 zł/h)",
    );
    fireEvent.click(screen.getByLabelText("Klient wynegocjował inną stawkę"));
    fireEvent.change(screen.getByLabelText("Notatka (opcjonalnie)"), {
      target: { value: "zszedł po drugiej rozmowie" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz stawkę" }));
    await waitFor(() => expect(mocks.setRate).toHaveBeenCalled());
    expect(mocks.setRate.mock.calls[0]).toEqual([
      5,
      9,
      {
        rate_value: 145,
        rate_unit: "hourly",
        rate_currency: "PLN",
        reason: "client_negotiated",
        note: "zszedł po drugiej rozmowie",
      },
    ]);
    expect(mocks.toast.showSuccess).toHaveBeenCalledWith("Zapisano stawkę do klienta");
  });

  it("bez powodu nie zapisuje", async () => {
    renderDialog();
    await screen.findByTestId("client-rate-sent");
    fireEvent.change(screen.getByLabelText("Nowa stawka do klienta"), {
      target: { value: "145" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz stawkę" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Wybierz, dlaczego zmieniasz stawkę.",
    );
    expect(mocks.setRate).not.toHaveBeenCalled();
  });

  it("po zamówieniu odsyła do zamówienia i nie pozwala zapisać", async () => {
    mocks.get.mockResolvedValue({
      data: {
        ...HISTORY,
        can_write: false,
        order_lock: {
          order_id: 3,
          contract_id: 77,
          title: "Zamówienie X",
        },
      },
    });
    renderDialog();
    expect(await screen.findByTestId("client-rate-order-lock")).toHaveTextContent(
      "Ta osoba ma już zamówienie „Zamówienie X”",
    );
    expect(screen.queryByLabelText("Nowa stawka do klienta")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz kontrakt z zamówieniem" })).toHaveAttribute(
      "href",
      "/contracts/77",
    );
    expect(screen.getByRole("button", { name: "Zapisz stawkę" })).toBeDisabled();
  });

  it("pokazuje zmiany po wysyłce z powodem i słowami DL-a", async () => {
    mocks.get.mockResolvedValue({
      data: {
        ...HISTORY,
        current: { value: 145, unit: "hourly", currency: "PLN" },
        current_label: "145 zł/h",
        changes: [
          {
            at: "2026-10-20T09:00:00Z",
            by_name: "Ewa Nowak",
            old: null,
            new: null,
            old_label: "150 zł/h",
            new_label: "145 zł/h",
            reason: "client_negotiated",
            reason_label: "Klient wynegocjował inną stawkę",
            note: "zszedł po drugiej rozmowie",
          },
        ],
      },
    });
    renderDialog();
    const list = await screen.findByTestId("client-rate-history");
    expect(list).toHaveTextContent("20.10");
    expect(list).toHaveTextContent("150 zł/h → 145 zł/h");
    expect(list).toHaveTextContent("Ewa Nowak · Klient wynegocjował inną stawkę");
    expect(list).toHaveTextContent("„zszedł po drugiej rozmowie”");
    expect(screen.getByTestId("client-rate-sent")).toHaveTextContent("teraz 145 zł/h");
  });
});
