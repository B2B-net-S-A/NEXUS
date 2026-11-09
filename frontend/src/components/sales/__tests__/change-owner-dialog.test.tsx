/**
 * Zmiana opiekuna: lista to konta z prawem edycji Sprzedaży, a awaria listy
 * nie może wyglądać jak brak osób.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const update = vi.fn();
const refetch = vi.fn();
let candidates: Record<string, unknown>;

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useUpdateOpportunity: () => ({ mutate: update, isPending: false }),
  useOwnerCandidates: () => candidates,
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));
vi.mock("../SalesSelect", () => ({
  SalesSelect: ({
    value,
    onValueChange,
    options,
    ariaLabel,
  }: {
    value: string;
    onValueChange: (value: string) => void;
    options: { value: string; label: string }[];
    ariaLabel: string;
  }) => (
    <select aria-label={ariaLabel} value={value} onChange={(event) => onValueChange(event.target.value)}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

import { ChangeOwnerDialog } from "../CallLogDialogs";

const OWNER = { id: 7, name: "Obecny Opiekun" };
const ready = (data: { id: number; name: string }[]) => ({ data, isSuccess: true, isError: false, isLoading: false, refetch });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("zmiana opiekuna", () => {
  it("proponuje konta z listy kandydatów, nie osoby z filtra lejka", () => {
    candidates = ready([OWNER, { id: 9, name: "Nowa Osoba" }]);
    render(<ChangeOwnerDialog opportunityId={1} owner={OWNER} onClose={vi.fn()} />);
    const select = screen.getByLabelText("Nowy opiekun");
    expect(screen.getAllByRole("option").map((option) => option.textContent)).toEqual(["Obecny Opiekun", "Nowa Osoba"]);
    fireEvent.change(select, { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(update.mock.calls[0][0]).toEqual({ owner_user_id: 9 });
  });

  it("nieaktywny obecny opiekun zostaje widoczny, ale nie można go zapisać", () => {
    candidates = ready([{ id: 9, name: "Nowa Osoba" }]);
    render(<ChangeOwnerDialog opportunityId={1} owner={OWNER} onClose={vi.fn()} />);
    expect(screen.getAllByRole("option")[0].textContent).toBe("Obecny Opiekun");
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeDisabled();
  });

  it("awaria listy ma komunikat i ponowienie, bez listy", () => {
    candidates = {
      data: undefined,
      isSuccess: false,
      isError: true,
      isLoading: false,
      error: { response: { data: { detail: "Serwer nie odpowiada." } } },
      refetch,
    };
    render(<ChangeOwnerDialog opportunityId={1} owner={OWNER} onClose={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Serwer nie odpowiada.");
    expect(screen.queryByLabelText("Nowy opiekun")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("pusta lista mówi wprost, że nie ma komu przekazać", () => {
    candidates = ready([OWNER]);
    render(<ChangeOwnerDialog opportunityId={1} owner={OWNER} onClose={vi.fn()} />);
    expect(screen.getByText("Nie ma innej osoby z prawem edycji Sprzedaży.")).toBeInTheDocument();
  });

  it("w trakcie wczytywania nie udaje pustej listy", () => {
    candidates = { data: undefined, isSuccess: false, isError: false, isLoading: true, refetch };
    render(<ChangeOwnerDialog opportunityId={1} owner={OWNER} onClose={vi.fn()} />);
    expect(screen.getByText("Wczytywanie…")).toBeInTheDocument();
    expect(screen.queryByText("Nie ma innej osoby z prawem edycji Sprzedaży.")).toBeNull();
  });
});
