/**
 * Akcje dla wielu szans z listy (decyzja Artura 11.11.2026): krok, opiekun, zamknięcie;
 * pominięte szanse wracają z powodem i zostają zaznaczone.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const bulk = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const refetchCandidates = vi.fn();
let candidates: object = {};

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useBulkOpportunities: () => ({ mutate: bulk, isPending: false }),
  useOwnerCandidates: () => candidates,
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("../SalesSelect", () => ({
  SalesSelect: ({
    ariaLabel,
    value,
    onValueChange,
    options,
  }: {
    ariaLabel?: string;
    value: string;
    onValueChange: (value: string) => void;
    options: { value: string; label: string }[];
  }) => (
    <select aria-label={ariaLabel} value={value} onChange={(event) => onValueChange(event.target.value)}>
      <option value="">—</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

import { OpportunityBulkBar } from "../OpportunityBulkBar";

const onClear = vi.fn();
const bar = (lostStageName: string | null = "Przegrana") =>
  render(<OpportunityBulkBar ids={[11, 12, 13]} lostStageName={lostStageName} onClear={onClear} />);

beforeEach(() => {
  vi.clearAllMocks();
  // Lista osób to `owner-candidates` (aktywne konta z „Sprzedaż: edycja”), nie filtr lejka.
  candidates = {
    isSuccess: true,
    isError: false,
    data: [
      { id: 9, name: "Druga Osoba" },
      { id: 81, name: "Opiekun Fabryk" },
    ],
    refetch: refetchCandidates,
  };
});

describe("pasek zaznaczonych szans", () => {
  it("„Zaplanuj krok” wysyła jeden zapis dla wszystkich z terminem z modułu i odznacza", () => {
    bulk.mockImplementation((_input, { onSuccess }) => onSuccess({ done: [11, 12, 13], skipped: [] }));
    bar();
    expect(screen.getByText("Zaznaczone: 3 szanse")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zaplanuj krok" }));
    fireEvent.click(screen.getByRole("button", { name: "Za 2 tygodnie" }));
    expect(bulk.mock.calls[0][0]).toEqual({ ids: [11, 12, 13], action: "plan", days: 14 });
    expect(showSuccess).toHaveBeenCalled();
    expect(onClear).toHaveBeenCalled();
  });

  it("„Zmień opiekuna” proponuje osoby z owner-candidates i wysyła wybraną", () => {
    bulk.mockImplementation((_input, { onSuccess }) => onSuccess({ done: [11, 12, 13], skipped: [] }));
    bar();
    fireEvent.click(screen.getByRole("button", { name: "Zmień opiekuna" }));
    const select = screen.getByLabelText("Nowy opiekun") as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.value)).toEqual(["", "9", "81"]);
    expect((screen.getByRole("button", { name: "Przekaż 3 szanse" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(select, { target: { value: "81" } });
    fireEvent.click(screen.getByRole("button", { name: "Przekaż 3 szanse" }));
    expect(bulk.mock.calls[0][0]).toEqual({ ids: [11, 12, 13], action: "owner", owner_user_id: 81 });
  });

  it("lista osób w trakcie wczytywania nie pozwala przekazać", () => {
    candidates = { isSuccess: false, isError: false, data: undefined, refetch: refetchCandidates };
    bar();
    fireEvent.click(screen.getByRole("button", { name: "Zmień opiekuna" }));
    expect(screen.getByText("Wczytywanie osób…")).toBeTruthy();
    expect(screen.queryByLabelText("Nowy opiekun")).toBeNull();
    expect((screen.getByRole("button", { name: "Przekaż 3 szanse" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("błąd listy osób to komunikat z „Spróbuj ponownie”, nie pusta lista", () => {
    candidates = {
      isSuccess: false,
      isError: true,
      error: { response: { status: 500, data: { detail: "Błąd serwera" } } },
      data: undefined,
      refetch: refetchCandidates,
    };
    bar();
    fireEvent.click(screen.getByRole("button", { name: "Zmień opiekuna" }));
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.queryByLabelText("Nowy opiekun")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    expect(refetchCandidates).toHaveBeenCalled();
  });

  it("„Zamknij z powodem” wysyła powód bez spacji, a pusty pomija", () => {
    bulk.mockImplementation((_input, { onSuccess }) => onSuccess({ done: [11], skipped: [] }));
    bar();
    fireEvent.click(screen.getByRole("button", { name: "Zamknij z powodem" }));
    fireEvent.change(screen.getByLabelText("Powód (opcjonalnie)"), { target: { value: "  brak budżetu " } });
    fireEvent.click(screen.getByRole("button", { name: "Zamknij 3 szanse" }));
    expect(bulk.mock.calls[0][0]).toEqual({ ids: [11, 12, 13], action: "close", lost_reason: "brak budżetu" });
  });

  it("pominięte szanse wracają z powodem i zaznaczenie zostaje", () => {
    bulk.mockImplementation((_input, { onSuccess }) =>
      onSuccess({ done: [11], skipped: [{ id: 12, title: "Zespół QA", reason: "zmienia ją tylko opiekun albo admin" }] }),
    );
    bar();
    fireEvent.click(screen.getByRole("button", { name: "Zaplanuj krok" }));
    fireEvent.click(screen.getByRole("button", { name: "Jutro" }));
    expect(screen.getByText("Pominięta: Zespół QA (zmienia ją tylko opiekun albo admin)")).toBeTruthy();
    expect(onClear).not.toHaveBeenCalled();
  });

  it("błąd zapisu wraca jako komunikat", () => {
    bulk.mockImplementation((_input, { onError }) => onError(new Error("boom")));
    bar();
    fireEvent.click(screen.getByRole("button", { name: "Zaplanuj krok" }));
    fireEvent.click(screen.getByRole("button", { name: "Jutro" }));
    expect(showError).toHaveBeenCalled();
    expect(onClear).not.toHaveBeenCalled();
  });

  it("bez etapu przegranej w lejku nie ma „Zamknij z powodem”", () => {
    bar(null);
    expect(screen.queryByRole("button", { name: "Zamknij z powodem" })).toBeNull();
  });
});
