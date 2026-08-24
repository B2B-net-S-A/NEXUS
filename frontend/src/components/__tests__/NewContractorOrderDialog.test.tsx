import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { NewContractorOrderDialog } from "@/components/NewContractorOrderDialog";

// Komponent importuje instancję DOMYŚLNIE (`import api from "@/lib/api"`),
// więc podmiana samego eksportu nazwanego zostawiłaby mu prawdziwego axiosa.
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  const mocked = { ...actual.api, get: vi.fn(), post: vi.fn() };
  return { ...actual, api: mocked, default: mocked };
});

import api from "@/lib/api";

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <NewContractorOrderDialog
          clientId={11}
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
});

describe("NewContractorOrderDialog — wyszukiwarka kandydatów", () => {
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

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Nie udało się wyszukać kandydatów/i,
    );
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
