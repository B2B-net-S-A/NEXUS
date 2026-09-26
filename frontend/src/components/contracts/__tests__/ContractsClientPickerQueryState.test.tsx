import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContractsClientPicker } from "@/components/contracts/ContractsClientPicker";

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => getMock(...args) },
}));

// react-query v5: po błędzie `isLoading` jest false, więc gałąź
// `isLoading ? … : <CommandEmpty>` pokazywała awarię jako „Brak wyników.”
// (czyli „nie ma takiego klienta”).
function renderPicker() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ContractsClientPicker value={null} onChange={vi.fn()} />
    </QueryClientProvider>,
  );
}

async function openPicker() {
  const user = userEvent.setup();
  await user.click(
    screen.getByRole("button", { name: /Wszyscy klienci \(lista globalna\)/ }),
  );
  return user;
}

beforeEach(() => {
  getMock.mockReset();
});

describe("ContractsClientPicker — stan zapytania", () => {
  it("pyta o klientów w zakresie Delivery (portfel DL), nie o całą organizację", async () => {
    // Runda 6 audytu: zapis kontraktu u klienta spoza portfela DL daje 403,
    // więc picker Kontraktów nie może go podpowiadać.
    getMock.mockResolvedValueOnce({ data: [] });
    renderPicker();
    await openPicker();
    expect(getMock).toHaveBeenCalledWith("/api/clients-lookup", {
      params: { delivery_scope: true },
    });
  });

  it("awaria listy klientów to błąd z „Ponów”, nie „Brak wyników.”", async () => {
    getMock.mockRejectedValueOnce(new Error("503"));
    renderPicker();
    const user = await openPicker();

    expect(
      await screen.findByText("Nie udało się pobrać listy klientów."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak wyników.")).not.toBeInTheDocument();

    getMock.mockResolvedValueOnce({ data: [{ id: 7, name: "Bank Testowy" }] });
    await user.click(screen.getByRole("button", { name: /Ponów/ }));
    expect(await screen.findByText("Bank Testowy")).toBeInTheDocument();
  });

  it("w trakcie ładowania pokazuje „Ładowanie klientów…”", async () => {
    getMock.mockReturnValueOnce(new Promise(() => {}));
    renderPicker();
    await openPicker();

    expect(await screen.findByText("Ładowanie klientów…")).toBeInTheDocument();
    expect(screen.queryByText("Brak wyników.")).not.toBeInTheDocument();
  });

  it("udana pusta lista nie udaje awarii ani ładowania", async () => {
    getMock.mockResolvedValueOnce({ data: [] });
    renderPicker();
    await openPicker();

    // Pozycja „Wszyscy klienci” jest zawsze na liście (wybór listy globalnej),
    // więc przy sukcesie zostaje sama — bez komunikatu o błędzie i ładowaniu.
    expect(
      await screen.findByRole("option", { name: /Wszyscy klienci/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Ładowanie klientów…")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Nie udało się pobrać listy klientów."),
    ).not.toBeInTheDocument();
  });
});
