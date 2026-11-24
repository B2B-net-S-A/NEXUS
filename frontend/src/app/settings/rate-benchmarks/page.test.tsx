import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RateBenchmarksPage from "./page";

const mocks = vi.hoisted(() => ({
  user: { role: "finance", roles: ["finance"] },
  list: vi.fn(),
  create: vi.fn(),
  delete: vi.fn(),
  importCsv: vi.fn(),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user, hydrated: true }),
  hasRole: (
    user: { role?: string; roles?: string[] } | null,
    ...roles: string[]
  ) =>
    !!user &&
    roles.some((role) =>
      new Set([user.role, ...(user.roles ?? [])]).has(role),
    ),
}));

vi.mock("@/lib/api", () => ({
  rateBenchmarksApi: {
    list: mocks.list,
    create: mocks.create,
    delete: mocks.delete,
    importCsv: mocks.importCsv,
  },
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <RateBenchmarksPage />
    </QueryClientProvider>,
  );
}

describe("RateBenchmarksPage — Finance read-only", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({
      data: [
        {
          id: 1,
          role: "Java Developer",
          seniority: "senior",
          currency: "PLN",
          rate_unit: "daily",
          market_min: 1000,
          market_median: 1200,
          market_max: 1400,
          location: "Warszawa",
          source: "Raport testowy",
          source_date: "2026-08-01",
          notes: null,
        },
      ],
    });
  });

  it("pokazuje min, medianę i max, ale ukrywa import/dodawanie/usuwanie", async () => {
    const { container } = renderPage();

    expect(await screen.findByText("Java Developer")).toBeInTheDocument();
    expect(screen.getByText(/1[\s\u00a0]?000/)).toBeInTheDocument();
    expect(screen.getByText(/1[\s\u00a0]?200/)).toBeInTheDocument();
    expect(screen.getByText(/1[\s\u00a0]?400/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Import CSV/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Dodaj$/i })).not.toBeInTheDocument();
    expect(container.querySelector('input[type="file"]')).not.toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.delete).not.toHaveBeenCalled();
    expect(mocks.importCsv).not.toHaveBeenCalled();
  });
});

describe("RateBenchmarksPage — pusty stan i wzór pliku (20.10.2026)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.user = { role: "admin", roles: ["admin"] };
  });

  it("pusty rejestr mówi, co zrobić, a zamiast nagłówka CSV jest wzór pliku", async () => {
    mocks.list.mockResolvedValue({ data: [] });
    renderPage();
    expect(await screen.findByText(/Nie ma jeszcze stawek rynkowych\. Dodaj je ręcznie/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz wzór pliku" })).toBeInTheDocument();
    expect(screen.queryByText(/CSV header/)).not.toBeInTheDocument();
  });

  it("awaria pobrania to błąd z ponowieniem, nie pusta lista", async () => {
    mocks.list.mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie|Ponów/ })).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma jeszcze stawek rynkowych/)).not.toBeInTheDocument();
  });

  it("Finanse (tylko odczyt) nie dostają wzoru pliku do importu", async () => {
    mocks.user = { role: "finance", roles: ["finance"] };
    mocks.list.mockResolvedValue({ data: [] });
    renderPage();
    expect(await screen.findByText("Nie ma jeszcze stawek rynkowych.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pobierz wzór pliku" })).not.toBeInTheDocument();
  });
});

describe("RateBenchmarksPage — nieudany zapis, usunięcie i import", () => {
  const refusal = (detail: string) => ({ response: { status: 422, data: { detail } } });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.user = { role: "admin", roles: ["admin"] };
    mocks.list.mockResolvedValue({
      data: [
        {
          id: 1,
          role: "Java Developer",
          seniority: "senior",
          currency: "PLN",
          rate_unit: "daily",
          market_min: 1000,
          market_median: 1200,
          market_max: 1400,
          location: "Warszawa",
          source: "Raport testowy",
          source_date: "2026-08-01",
          notes: null,
        },
      ],
    });
  });

  it("odmowa dodania: komunikat przy formularzu, formularz z wpisanymi danymi zostaje", async () => {
    mocks.create.mockRejectedValue(refusal("Mediana musi leżeć między min a max."));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Java Developer");

    await user.click(screen.getByRole("button", { name: /^Dodaj$/ }));
    await user.type(screen.getByPlaceholderText("Java Developer"), "Analityk testowy");
    await user.type(screen.getByRole("spinbutton", { name: "Mediana *" }), "900");
    await user.type(screen.getByPlaceholderText("Hays Guide 2026"), "Raport fikcyjny");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Mediana musi leżeć między min a max.",
    );
    expect(screen.getByPlaceholderText("Java Developer")).toHaveValue("Analityk testowy");
  });

  it("odmowa usunięcia pokazuje komunikat, wiersz zostaje", async () => {
    mocks.delete.mockRejectedValue(refusal("Wpis jest używany w kontrakcie."));
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Java Developer");

    await user.click(screen.getByRole("button", { name: "Usuń wpis: Java Developer" }));
    await user.click(await screen.findByRole("button", { name: "Usuń" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Wpis jest używany w kontrakcie.",
    );
    expect(screen.getByText("Java Developer")).toBeInTheDocument();
  });

  it("odmowa importu CSV pokazuje komunikat zamiast ciszy", async () => {
    mocks.importCsv.mockRejectedValue(refusal("Plik nie ma kolumny role."));
    const user = userEvent.setup();
    const { container } = renderPage();
    await screen.findByText("Java Developer");

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["x"], "stawki.csv", { type: "text/csv" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Plik nie ma kolumny role.");
  });
});

