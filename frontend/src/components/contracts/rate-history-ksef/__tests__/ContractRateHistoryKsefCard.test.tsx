/**
 * Historia stawek z faktur KSeF (0782): karta do decyzji, pasek po wpisie
 * automatycznym, kwoty pod bramką i awaria, która nie wygląda jak pusto.
 * Kwoty i numery faktur zmyślone.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/api", () => {
  const api = {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  };
  return { api, default: api };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.toastError, showSuccess: vi.fn() }),
}));

import { ContractRateHistoryKsefCard } from "../ContractRateHistoryKsefCard";
import { RateHistoryRowNote } from "../RateHistoryRowNote";

const OPEN = {
  id: 7,
  contract_id: 5,
  category: "brak_historii",
  automatic: false,
  status: "open",
  reasons: [],
  decided_at: null,
  undo_until: null,
  steps: [
    {
      leg: "client",
      from: "2025-01-01",
      months: [],
      evidence: [],
      reasons: [],
      baseline: true,
      rate: 200,
      nexus_rate: 200,
      impact: 0,
    },
    {
      leg: "client",
      from: "2026-04-01",
      months: ["2026-04", "2026-05", "2026-06"],
      evidence: ["FS/1/04", "FS/1/05"],
      reasons: [],
      baseline: false,
      rate: 250,
      nexus_rate: 200,
      impact: 24000,
    },
  ],
};

function renderCard(
  props: Partial<React.ComponentProps<typeof ContractRateHistoryKsefCard>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ContractRateHistoryKsefCard contractId={5} canDismiss {...props} />
    </QueryClientProvider>,
  );
}

describe("ContractRateHistoryKsefCard", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
  });

  it("pokazuje kroki z faktur bez kroku bazowego i wpisuje je", async () => {
    mocks.get.mockResolvedValue({
      data: { item: OPEN, amounts_visible: true, can_apply: true },
    });
    mocks.post.mockResolvedValue({ data: { ...OPEN, status: "applied" } });
    renderCard();
    expect(
      await screen.findByText(/kontrakt ma tylko bieżącą/),
    ).toBeInTheDocument();
    expect(screen.getByText("250 zł/h")).toBeInTheDocument();
    expect(screen.getByText("04.2026–06.2026")).toBeInTheDocument();
    expect(screen.getByText(/Faktury: FS\/1\/04, FS\/1\/05/)).toBeInTheDocument();
    // Krok bazowy (od startu kontraktu) nie jest wierszem tabeli.
    expect(screen.queryByText("01.01.2025")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Wprowadź do harmonogramu" }),
    );
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/contracts/5/rate-history-ksef/apply",
      ),
    );
  });

  it("bez podglądu kwot nie pokazuje stawek ani przycisku wpisu", async () => {
    mocks.get.mockResolvedValue({
      data: {
        item: {
          ...OPEN,
          steps: OPEN.steps.map(({ rate, nexus_rate, impact, ...s }) => s),
        },
        amounts_visible: false,
        can_apply: true,
      },
    });
    renderCard();
    expect(
      await screen.findByText(/inną stawkę od 04\.2026/),
    ).toBeInTheDocument();
    expect(screen.queryByText("250 zł/h")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Wprowadź do harmonogramu" }),
    ).not.toBeInTheDocument();
  });

  it("bez prawa do stawki i edycji kontraktu nie ma przycisków decyzji", async () => {
    mocks.get.mockResolvedValue({
      data: { item: OPEN, amounts_visible: true, can_apply: false },
    });
    renderCard({ canDismiss: false });
    await screen.findByText(/kontrakt ma tylko bieżącą/);
    expect(
      screen.queryByRole("button", { name: "Wprowadź do harmonogramu" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Odrzuć" })).not.toBeInTheDocument();
  });

  it("podpowiedź do sprawdzenia pokazuje powody", async () => {
    const reason = "Krok zmienia dzisiejszą stawkę — decyduje człowiek.";
    mocks.get.mockResolvedValue({
      data: {
        item: { ...OPEN, category: "rozjazd_biezacy", reasons: [reason] },
        amounts_visible: true,
        can_apply: true,
      },
    });
    renderCard();
    expect(await screen.findByText(/do sprawdzenia/)).toBeInTheDocument();
    expect(screen.getByText(reason)).toBeInTheDocument();
  });

  it("wpis automatyczny pokazuje pasek z „Cofnij”", async () => {
    mocks.get.mockResolvedValue({
      data: {
        item: {
          ...OPEN,
          status: "auto_applied",
          automatic: true,
          decided_at: "2026-11-25T07:00:00Z",
          undo_until: "2026-12-02T07:00:00Z",
        },
        amounts_visible: true,
        can_apply: true,
      },
    });
    renderCard();
    expect(
      await screen.findByText(/NEXUS uzupełnił historię stawek/),
    ).toBeInTheDocument();
    expect(screen.getByText(/klient 250 zł\/h od 01\.04\.2026/)).toBeInTheDocument();
    expect(screen.getByText(/działa do 02\.12\.2026/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cofnij/ })).toBeInTheDocument();
  });

  it("awaria odczytu nie wygląda jak brak podpowiedzi", async () => {
    mocks.get.mockRejectedValue(new Error("500"));
    renderCard();
    expect(
      await screen.findByText(/Nie udało się sprawdzić stawek z faktur/),
    ).toBeInTheDocument();
  });

  it("brak podpowiedzi nie rysuje niczego", async () => {
    mocks.get.mockResolvedValue({
      data: { item: null, amounts_visible: true, can_apply: true },
    });
    const { container } = renderCard();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("RateHistoryRowNote", () => {
  it("mówi, która stawka i od którego miesiąca", () => {
    render(
      <RateHistoryRowNote
        change={{
          from: "2026-04-01",
          leg: "cost",
          rate: 190,
          category: "brak_historii",
          count: 3,
        }}
      />,
    );
    expect(
      screen.getByText("faktury (koszt): 190 zł/h od 04.2026 (+2)"),
    ).toBeInTheDocument();
  });
});
