/**
 * `?aneks=` na zakładce „Aneksy” (wariant A, 19.11.2026): przycisk „Dodaj
 * aneks” w nagłówku kontraktu otwiera zakładkę od razu z właściwym oknem,
 * a zakładka zdejmuje parametr natywną historią (nie routerem), żeby
 * odświeżenie nie otwierało okna drugi raz.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  params: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => mocks.params,
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: vi.fn(),
  },
  CONTRACT_FIELD_LABELS: {},
  CONTRACT_TERMINATION_REASONS: [],
}));

vi.mock("@/store/auth", async () => {
  const actual =
    await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  const state = { user: { id: 1, role: "admin", roles: ["admin"] } };
  return {
    ...actual,
    useAuthStore: (selector: (s: typeof state) => unknown) => selector(state),
    canViewClientFinance: () => true,
  };
});

import { ContractAmendmentsTab } from "@/components/ContractAmendmentsTab";

type Props = Partial<React.ComponentProps<typeof ContractAmendmentsTab>>;

function setUrl(search: string) {
  window.history.replaceState(null, "", `/contracts/5${search}`);
  mocks.params = new URLSearchParams(search);
}

function renderTab(props: Props = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const ui = (p: Props) => (
    <QueryClientProvider client={client}>
      <ContractAmendmentsTab contractId={5} clientId={2} {...p} />
    </QueryClientProvider>
  );
  const view = render(ui(props));
  return { ...view, rerenderWith: (p: Props) => view.rerender(ui(p)) };
}

let replaceState: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  mocks.get.mockReset();
  mocks.get.mockResolvedValue({ data: [] });
  replaceState = vi.spyOn(window.history, "replaceState");
});

afterEach(() => {
  replaceState.mockRestore();
  setUrl("");
});

describe("aneks= otwiera okno przy wejściu na zakładkę", () => {
  it("zmiana zakresu: okno otwarte, parametr zdjęty natywną historią, reszta adresu została", async () => {
    setUrl("?tab=amendments&aneks=scope_change&from=contracts");
    replaceState.mockClear();
    renderTab();

    expect(await screen.findByRole("dialog", { name: "Zmiana zakresu" })).toBeInTheDocument();
    expect(replaceState).toHaveBeenCalledWith(null, "", "/contracts/5?tab=amendments&from=contracts");
    expect(window.location.search).toBe("?tab=amendments&from=contracts");
  });

  it("zmiana stawki i przedłużenie otwierają swoje formularze", async () => {
    setUrl("?tab=amendments&aneks=rate_change");
    const first = renderTab();
    expect(await screen.findByRole("dialog", { name: "Zmiana stawki" })).toBeInTheDocument();
    expect(screen.getByLabelText("Nowa stawka klienta")).toBeInTheDocument();
    first.unmount();

    setUrl("?tab=amendments&aneks=extension");
    renderTab();
    expect(await screen.findByRole("dialog", { name: "Przedłużenie" })).toBeInTheDocument();
    expect(screen.getByLabelText("Nowa data zakończenia")).toBeInTheDocument();
  });

  it("zakończenie wcześniej idzie oknem strony — raz, mimo kolejnych renderów", async () => {
    setUrl("?tab=amendments&aneks=early_termination");
    const terminate = vi.fn();
    const view = renderTab({ onRequestTermination: terminate });
    await waitFor(() => expect(terminate).toHaveBeenCalledTimes(1));
    // Strona przekazuje nową funkcję przy każdym renderze; adres w `useSearchParams`
    // może jeszcze stać — okno nie otwiera się drugi raz.
    view.rerenderWith({ onRequestTermination: () => terminate() });
    await screen.findByText(/Brak aneksów/);
    expect(terminate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("kolejna zmiana adresu na zamontowanej zakładce (przycisk w nagłówku) znów otwiera okno", async () => {
    setUrl("?tab=amendments");
    const view = renderTab();
    await screen.findByText(/Brak aneksów/);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    setUrl("?tab=amendments&aneks=scope_change");
    view.rerenderWith({});
    expect(await screen.findByRole("dialog", { name: "Zmiana zakresu" })).toBeInTheDocument();
  });

  it("zablokowane przedłużenie umowy B2B: zamiast okna zdanie, dlaczego; da się je zamknąć", async () => {
    setUrl("?tab=amendments&aneks=extension");
    renderTab({ extensionLocked: true });
    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent(/nie ma czego przedłużać/);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(window.location.search).toBe("?tab=amendments");

    fireEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("tryb podglądu niczego nie otwiera, a parametr i tak znika", async () => {
    setUrl("?tab=amendments&aneks=scope_change");
    const terminate = vi.fn();
    renderTab({ readOnly: true, onRequestTermination: terminate });
    expect(await screen.findByRole("status")).toHaveTextContent(/trybie podglądu/);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(terminate).not.toHaveBeenCalled();
    expect(window.location.search).toBe("?tab=amendments");
  });

  it("nieznana wartość: parametr znika bez okna i bez komunikatu", async () => {
    setUrl("?tab=amendments&aneks=usun");
    renderTab();
    await screen.findByText(/Brak aneksów/);
    expect(window.location.search).toBe("?tab=amendments");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
