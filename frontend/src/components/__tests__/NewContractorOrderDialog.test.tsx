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
