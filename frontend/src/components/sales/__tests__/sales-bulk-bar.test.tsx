/**
 * Akcje dla wielu szans z listy (decyzja Artura 11.11.2026): krok, opiekun, zamknięcie;
 * pominięte szanse wracają z powodem i zostają zaznaczone.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const bulk = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useBulkOpportunities: () => ({ mutate: bulk, isPending: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("../useOwnerFilterOptions", () => ({
  useOwnerFilterOptions: () => [
    { value: "acct:9", label: "Druga Osoba" },
    { value: "atlas:Kinga", label: "Kinga (z Atlasa)" },
  ],
}));
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

  it("„Zmień opiekuna” proponuje tylko konta NEXUSA i wysyła wybrane", () => {
    bulk.mockImplementation((_input, { onSuccess }) => onSuccess({ done: [11, 12, 13], skipped: [] }));
    bar();
    fireEvent.click(screen.getByRole("button", { name: "Zmień opiekuna" }));
    const select = screen.getByLabelText("Nowy opiekun") as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.value)).toEqual(["", "acct:9"]);
    expect((screen.getByRole("button", { name: "Przekaż 3 szanse" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(select, { target: { value: "acct:9" } });
    fireEvent.click(screen.getByRole("button", { name: "Przekaż 3 szanse" }));
    expect(bulk.mock.calls[0][0]).toEqual({ ids: [11, 12, 13], action: "owner", owner_user_id: 9 });
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
