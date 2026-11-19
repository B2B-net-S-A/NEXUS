/**
 * Stawka z umów i aneksów kontraktu (0739): karta do zatwierdzenia, pasek po
 * wpisie automatycznym, kwoty pod bramką i awaria, która nie wygląda jak pusto.
 * Kwoty zmyślone.
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

import { ContractRateDocumentsCard } from "../ContractRateDocumentsCard";
import { RateDocumentRowNote } from "../RateDocumentRowNote";

const OPEN = {
  id: 11,
  document_id: 31,
  filename: "Aneks stawka.pdf",
  kind: "annex",
  document_date: "2026-10-01",
  category: "auto",
  reasons: [],
  decision: null,
  decided_at: null,
  undo_until: null,
  read_at: "2026-11-18T18:04:00Z",
  steps: [
    {
      from: "2026-11-01",
      to: null,
      rate: 112,
      nexus_rate: 100,
      condition: null,
    },
  ],
  quote: "wynagrodzenie 112 zł netto za roboczogodzinę",
};

function renderCard(
  props: Partial<React.ComponentProps<typeof ContractRateDocumentsCard>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ContractRateDocumentsCard contractId={5} canDismiss {...props} />
    </QueryClientProvider>,
  );
}

describe("ContractRateDocumentsCard", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.post.mockReset();
  });

  it("pokazuje różnicę z kwotami i wpisuje ją do harmonogramu", async () => {
    mocks.get.mockResolvedValue({
      data: { items: [OPEN], amounts_visible: true, can_apply: true },
    });
    mocks.post.mockResolvedValue({ data: { ...OPEN, decision: "applied" } });
    renderCard();
    expect(
      await screen.findByText(/zmienia stawkę Partnera od 11\.2026/),
    ).toBeInTheDocument();
    expect(screen.getByText("112 zł/h")).toBeInTheDocument();
    expect(screen.getByText("100 zł/h")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Wprowadź do harmonogramu" }),
    );
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/contracts/5/rate-documents/11/apply",
      ),
    );
  });

  it("bez podglądu kwot nie pokazuje stawek ani przycisku wpisu", async () => {
    mocks.get.mockResolvedValue({
      data: {
        items: [
          { ...OPEN, steps: [{ from: "2026-11-01", to: null }], quote: null },
        ],
        amounts_visible: false,
        can_apply: true,
      },
    });
    renderCard();
    expect(
      await screen.findByText(/Kwoty widzi osoba z podglądem stawek/),
    ).toBeInTheDocument();
    expect(screen.queryByText("112 zł/h")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Wprowadź do harmonogramu" }),
    ).not.toBeInTheDocument();
  });

  it("bez prawa do stawki i edycji kontraktu nie ma przycisków decyzji", async () => {
    mocks.get.mockResolvedValue({
      data: { items: [OPEN], amounts_visible: true, can_apply: false },
    });
    renderCard({ canDismiss: false });
    await screen.findByText(/zmienia stawkę Partnera/);
    expect(
      screen.queryByRole("button", { name: "Wprowadź do harmonogramu" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "To nie stawka Partnera" }),
    ).not.toBeInTheDocument();
  });

  it("różnica do sprawdzenia pokazuje powody", async () => {
    mocks.get.mockResolvedValue({
      data: {
        items: [
          { ...OPEN, category: "review", reasons: ["Różnica ponad 30%."] },
        ],
        amounts_visible: true,
        can_apply: true,
      },
    });
    renderCard();
    expect(await screen.findByText(/do sprawdzenia/)).toBeInTheDocument();
    expect(screen.getByText("Różnica ponad 30%.")).toBeInTheDocument();
  });

  it("wpis automatyczny pokazuje pasek z „Cofnij”", async () => {
    mocks.get.mockResolvedValue({
      data: {
        items: [
          {
            ...OPEN,
            decision: "auto_applied",
            decided_at: "2026-11-19T07:00:00Z",
            undo_until: "2026-11-26T07:00:00Z",
          },
        ],
        amounts_visible: true,
        can_apply: true,
      },
    });
    renderCard();
    expect(
      await screen.findByText(/NEXUS wpisał stawkę z dokumentu/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/100 zł\/h → 112 zł\/h od 01\.11\.2026/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Cofnij/ })).toBeInTheDocument();
  });

  it("awaria odczytu nie wygląda jak brak różnic", async () => {
    mocks.get.mockRejectedValue(new Error("500"));
    renderCard();
    expect(
      await screen.findByText(/Nie udało się sprawdzić stawek/),
    ).toBeInTheDocument();
  });

  it("brak różnic nie rysuje niczego", async () => {
    mocks.get.mockResolvedValue({
      data: { items: [], amounts_visible: true, can_apply: true },
    });
    const { container } = renderCard();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("RateDocumentRowNote", () => {
  it("mówi, od którego miesiąca zmienia się stawka", () => {
    render(
      <RateDocumentRowNote
        change={{
          from: "2026-11-01",
          rate: 124,
          kind: "annex",
          category: "auto",
          count: 1,
        }}
      />,
    );
    expect(screen.getByText("aneks: 124 zł/h od 11.2026")).toBeInTheDocument();
  });

  it("bez kwoty (redakcja) podaje sam miesiąc", () => {
    render(
      <RateDocumentRowNote
        change={{
          from: "2027-01-01",
          rate: null,
          kind: "contract",
          category: "auto",
          count: 2,
        }}
      />,
    );
    expect(
      screen.getByText("umowa: inna stawka od 01.2027 (+1)"),
    ).toBeInTheDocument();
  });

  it("bez różnicy nic nie rysuje", () => {
    const { container } = render(<RateDocumentRowNote change={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
