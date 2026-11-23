/**
 * `?nowa=<NIP>` na liście Firm: okno otwiera się samo, po zapisie adres prowadzi
 * na kartę, a anulowanie wraca na czystą listę. Dane fikcyjne.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { push, replace, params, editor } = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  params: { value: new URLSearchParams("nowa=1111111111") },
  editor: { value: true },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => params.value,
}));
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => ({ replaceUrl: vi.fn() }) }));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => editor.value,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number } }) => unknown) => selector({ user: { id: 3 } }),
  hasRole: () => false,
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useSalesCompanies: () => ({ data: { items: [], total: 0 }, isSuccess: true, isLoading: false }),
}));
vi.mock("../useOwnerFilterOptions", () => ({ useOwnerFilterOptions: () => [] }));
vi.mock("../OwnerLabelsDialog", () => ({ OwnerLabelsDialog: () => null }));
vi.mock("../SalesSelect", () => ({ SalesSelect: () => null }));
// Okno zastępujemy przyciskami, które robią dokładnie to, co prawdziwe okno po zapisie
// (najpierw onSaved, potem zamknięcie) i po „Anuluj”.
vi.mock("../CompanyFormDialog", () => ({
  CompanyFormDialog: ({
    initialNip,
    onSaved,
    onOpenChange,
  }: {
    initialNip?: string;
    onSaved?: (company: { id: number }) => void;
    onOpenChange: (open: boolean) => void;
  }) => (
    <div role="dialog" aria-label={`Nowa firma ${initialNip ?? ""}`}>
      <button
        type="button"
        onClick={() => {
          onSaved?.({ id: 42 });
          onOpenChange(false);
        }}
      >
        zapisz
      </button>
      <button type="button" onClick={() => onOpenChange(false)}>
        anuluj
      </button>
    </div>
  ),
}));

import { CompaniesList } from "../CompaniesList";

beforeEach(() => {
  vi.clearAllMocks();
  params.value = new URLSearchParams("nowa=1111111111");
  editor.value = true;
});

describe("lista Firm z ?nowa=<NIP>", () => {
  it("otwiera okno z NIP-em, a po zapisie prowadzi na kartę, nie z powrotem na listę", () => {
    render(<CompaniesList />);
    expect(screen.getByRole("dialog", { name: "Nowa firma 1111111111" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "zapisz" }));
    expect(push).toHaveBeenCalledWith("/sales/companies/42");
    expect(replace).not.toHaveBeenCalled();
  });

  it("anulowanie zdejmuje ?nowa= z adresu", () => {
    render(<CompaniesList />);
    fireEvent.click(screen.getByRole("button", { name: "anuluj" }));
    expect(replace).toHaveBeenCalledWith("/sales/companies");
    expect(push).not.toHaveBeenCalled();
  });

  it("bez edycji Sprzedaży adres z NIP-em nie otwiera okna", () => {
    editor.value = false;
    render(<CompaniesList />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
