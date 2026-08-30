import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { NewContractorOrderDialog } from "@/components/NewContractorOrderDialog";
import { dlPortalApi, type OrderType } from "@/lib/api/dlPortal";
import { useAuthStore, type User } from "@/store/auth";

// Komponent importuje instancję DOMYŚLNIE (`import api from "@/lib/api"`),
// więc podmiana samego eksportu nazwanego zostawiłaby mu prawdziwego axiosa.
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  const mocked = { ...actual.api, get: vi.fn(), post: vi.fn() };
  return { ...actual, api: mocked, default: mocked };
});

vi.mock("@/lib/api/dlPortal", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/dlPortal")>();
  return {
    ...actual,
    dlPortalApi: {
      ...actual.dlPortalApi,
      createContractWithOrder: vi.fn(),
    },
  };
});

import api from "@/lib/api";

const createContractWithOrder = vi.mocked(dlPortalApi.createContractWithOrder);

function financeAdmin(): User {
  return {
    id: 1,
    email: "admin@example.com",
    name: "Admin",
    role: "admin",
    roles: ["admin"],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    capabilities: ["manage_finance"],
  };
}

function assignedDeliveryLead(): User {
  return {
    ...financeAdmin(),
    id: 17,
    email: "dl@example.com",
    name: "Delivery Lead",
    role: "delivery_lead",
    roles: ["delivery_lead"],
    capabilities: ["view_client_operations"],
  };
}

function renderDialog({
  orderType,
  onOrderTypeChange,
  canManageFinance,
}: {
  orderType?: OrderType;
  onOrderTypeChange?: (orderType: OrderType) => void;
  canManageFinance?: boolean;
} = {}) {
  // `retry: 1` LUSTRZANIE do produkcji (`QueryProvider`), nie `false`. Przy
  // `retry: false` test przechodziłby, nie dotykając realnego opóźnienia:
  // zanim `isError` stanie się `true`, leci jeszcze jedna próba z backoffem.
  // Chcemy dowodu, że gałąź błędu pokazuje się przy ustawieniach produkcyjnych.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: 1 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <NewContractorOrderDialog
          clientId={11}
          orderType={orderType}
          onOrderTypeChange={onOrderTypeChange}
          canManageFinance={canManageFinance}
          onClose={() => {}}
          onCreated={() => {}}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/** Odpowiada na `/api/jobs` pustą listą, a na `/api/candidates` wg `candidates`. */
function mockApi(candidates: () => Promise<unknown>) {
  vi.mocked(api.get).mockImplementation(((url: string) => {
    if (url.includes("/api/candidates")) return candidates();
    return Promise.resolve({ data: [] });
  }) as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  act(() => {
    useAuthStore.setState({ user: financeAdmin(), hydrated: true });
  });
  createContractWithOrder.mockResolvedValue({
    data: {
      contract_id: 563,
      order_id: 991,
      candidate_name: "Jan Kowalski",
      monthly_margin: null,
    },
  } as never);
});

afterEach(() => {
  act(() => {
    useAuthStore.setState({ user: null, hydrated: true });
  });
});

describe("NewContractorOrderDialog — wyszukiwarka kandydatów", () => {
  it("pokazuje przełącznik typu na górze formularza", async () => {
    const user = userEvent.setup();
    const onOrderTypeChange = vi.fn();
    mockApi(() => Promise.resolve({ data: { items: [] } }));
    renderDialog({ orderType: "periodic", onOrderTypeChange });

    expect(screen.getByRole("radio", { name: "Okresowe" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(screen.getByRole("radio", { name: "Kosztowe" }));
    expect(onOrderTypeChange).toHaveBeenCalledWith("cost");
  });

  it("awaria zapytania NIE renderuje się jako „Brak wyników”", async () => {
    // Realny przypadek z produkcji (import Nordei): chwilowy rate limit ukrył
    // kandydata, którego `/api/candidates` zwraca bez problemu. Na tej ścieżce
    // zakłada się kontrakt, więc pustka podpowiada, żeby założyć DRUGI rekord
    // komuś, kto w bazie już jest.
    const user = userEvent.setup();
    mockApi(() => Promise.reject(new Error("429")));
    renderDialog();

    await user.type(
      screen.getByPlaceholderText(/Szukaj po imieniu/i),
      "Skrzypek",
    );

    // Okno musi pokryć debounce (300 ms) ORAZ jedno ponowienie react-query
    // (~1 s backoffu przy `retry: 1`). Domyślne 1000 ms `findBy*` tu nie
    // wystarcza — i to jest realny koszt produkcyjny tej ścieżki, nie artefakt
    // testu: użytkownik widzi „Szukam…" przez tę chwilę, zanim pojawi się błąd.
    expect(
      await screen.findByRole("alert", {}, { timeout: 5000 }),
    ).toHaveTextContent(/Nie udało się wyszukać kandydatów/i);
    expect(screen.queryByText(/Brak wyników/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Ponów" }),
    ).toBeInTheDocument();
  });

  it("pusty wynik nadal mówi „Brak wyników”", async () => {
    // Odwrotna strona tej samej reguły: prawdziwe zero musi zostać zerem,
    // inaczej poprawka zamieniłaby jeden mylący komunikat na drugi.
    const user = userEvent.setup();
    mockApi(() => Promise.resolve({ data: { items: [] } }));
    renderDialog();

    await user.type(
      screen.getByPlaceholderText(/Szukaj po imieniu/i),
      "Nieistniejacy",
    );

    expect(await screen.findByText(/Brak wyników/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("NewContractorOrderDialog — jednostka i waluta zamówienia", () => {
  it("pokazuje pola przypisanemu DL na podstawie serwerowego uprawnienia", () => {
    act(() => {
      useAuthStore.setState({ user: assignedDeliveryLead(), hydrated: true });
    });
    mockApi(() => Promise.resolve({ data: { items: [] } }));
    renderDialog({ canManageFinance: true });

    expect(
      screen.getByRole("radiogroup", { name: "Jednostka stawki" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", {
        name: "Waluta zamówienia (przychodowa)",
      }),
    ).toBeInTheDocument();
  });

  it("przelicza obie stawki hour → MD i zachowuje niezależne waluty", async () => {
    const user = userEvent.setup({ delay: null });
    mockApi(() =>
      Promise.resolve({
        data: {
          items: [
            {
              id: 42,
              name: "Jan",
              lastname: "Kowalski",
              email: "jan@example.com",
            },
          ],
        },
      }),
    );
    renderDialog();

    await user.type(
      screen.getByPlaceholderText(/Szukaj po imieniu/i),
      "Jan",
    );
    await user.click(
      await screen.findByRole("button", { name: /Jan Kowalski/ }, { timeout: 2000 }),
    );
    await user.type(screen.getByLabelText(/Numer zamówienia/i), "45767");
    await user.type(screen.getByLabelText(/Contract start/i), "2026-09-01");
    await user.click(screen.getByRole("radio", { name: "Godzinowa" }));
    await user.type(screen.getByPlaceholderText("np. 215,60"), "215,60");
    await user.type(screen.getByPlaceholderText("np. 150,40"), "150,40");

    expect(screen.getByText(/Marża \/h \(przybl\.\):/i)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "MD" }));
    expect(screen.getByLabelText(/Klient płaci/)).toHaveValue("1724.8");
    expect(screen.getByLabelText(/My płacimy kontraktorowi/)).toHaveValue(
      "1203.2",
    );
    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "Waluta zamówienia (przychodowa)",
      }),
      "EUR",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Waluta stawki kosztowej" }),
      "PLN",
    );
    expect(screen.queryByText(/Marża \/MD \(przybl\.\):/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/Marża zostanie pokazana po niezależnym przeliczeniu/i),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Stwórz Contract + Order" }),
    );

    await waitFor(() => expect(createContractWithOrder).toHaveBeenCalledTimes(1));
    expect(createContractWithOrder).toHaveBeenCalledWith(
      11,
      expect.objectContaining({
        rate_client: 1724.8,
        rate_candidate: 1203.2,
        rate_unit: "daily",
        rate_client_currency: "EUR",
        rate_candidate_currency: "PLN",
      }),
    );
    expect(createContractWithOrder.mock.calls[0]?.[1]).not.toHaveProperty(
      "currency",
    );
  });
});
