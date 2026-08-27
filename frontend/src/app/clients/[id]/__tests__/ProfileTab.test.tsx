/**
 * Profil klienta NIE pokazuje rekrutacji — ani list, ani liczników.
 *
 * Wszystkie asercje w tym pliku są negatywne, a to najbardziej zwodnicza klasa
 * testów: przechodzą również wtedy, gdy komponent nic nie wyrenderował z zupełnie
 * innego powodu. Dlatego (1) fixture podaje NIEPUSTĄ `lost_jobs` — przy pustej
 * liście stary kod renderował empty-state, więc test „nie ma przegranych"
 * przechodziłby z fałszywego powodu, oraz (2) każdy test ma asercję POZYTYWNĄ
 * na sekcję, która ma zostać, żeby dowieść, że profil w ogóle się wyrenderował.
 *
 * Dotąd Profil klienta nie miał ani jednego testu, więc usunięcie sekcji
 * przeszłoby CI niezależnie od poprawności — i wróciłoby przy pierwszym merge'u.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientProfileResponse } from "@/types/client-profile";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

// `ExtendContractMenu` (akcja przy Obecnych konsultantach) woła `useToast`
// w ciele komponentu, więc bez tego mocka cały Profil wywala się w renderze.
vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
    showActionToast: vi.fn(),
  }),
}));

// Mock zastępuje CAŁY moduł, więc musi wystawić też to, co importują
// komponenty potomne Profilu (`ReEngageButton`, `TerminateContractModal`) —
// inaczej plik nie zdąży się nawet załadować.
vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  contractsApi: {},
  CONTRACT_TERMINATION_REASONS: [
    { value: "project_ended", label: "Koniec projektu" },
  ],
}));

import { ProfileTab } from "@/app/clients/[id]/ProfileTab";

const PROFILE: ClientProfileResponse = {
  summary: {
    open_jobs: 7,
    active_consultants: 3,
    active_contracts: 4,
    total_placements: 12,
    active_mrr: 45000,
    ltv: 900000,
    avg_time_to_fill_days: 21,
  },
  open_jobs: [],
  // Bez rzutowań `as unknown as`: pierwsza wersja tego fixture'u miała zły
  // kształt konsultanta (płaskie `candidate_name` zamiast obiektu `candidate`),
  // a rzutowanie zdusiło dokładnie ten błąd, który typy by pokazały — test
  // wywalił się dopiero w runtime, na wierszu konsultanta.
  active_consultants: [
    {
      contract_id: 529,
      candidate: {
        id: 1,
        name: "Tomasz Sadowski",
        avatar_url: null,
        competence_category: null,
        linkedin: null,
      },
      job_id: 11,
      job_title: "Specjalista: Engineer DevOps",
      job_from_order: false,
      start_date: "2026-07-27",
      end_date: null,
      days_to_end: null,
      // Wszystkie trzy kwoty wypełnione: przy brakującej „Stawce kosztowej"
      // kolumna nie miałaby pokrycia i regresja w niej przeszłaby niezauważona.
      monthly_rate_candidate: 12000,
      monthly_rate_client: 18000,
      monthly_margin: 6000,
      currency: "PLN",
      project_part: null,
    },
    {
      contract_id: 530,
      candidate: {
        id: 2,
        name: "Anna Bez Rekrutacji",
        avatar_url: null,
        competence_category: "backend",
        linkedin: null,
      },
      // Brak powiązanej rekrutacji — wiersz ma zostać PUSTY (wymóg ticketu).
      job_id: null,
      job_title: null,
      job_from_order: false,
      start_date: "2026-05-04",
      end_date: null,
      days_to_end: null,
      monthly_rate_candidate: null,
      monthly_rate_client: null,
      monthly_margin: null,
      currency: "PLN",
      project_part: null,
    },
  ],
  historical: {
    placements: [
      {
        contract_id: 400,
        candidate: {
          id: 3,
          name: "Marek Archiwalny",
          avatar_url: null,
          competence_category: "data_ai",
          linkedin: null,
        },
        job_id: 12,
        // Rekrutacja z ZAMÓWIENIA — kolumna musi oznaczyć inną proweniencję.
        job_title: "Data Engineer",
        job_from_order: true,
        start_date: "2025-02-01",
        end_date: "2026-03-31",
        terminated_at: null,
        termination_reason: null,
        duration_months: 13,
        monthly_rate_candidate: 21600,
        monthly_rate_client: 24800,
        monthly_margin: 3200,
        total_revenue: 322400,
      },
    ],
    // NIEPUSTA celowo — patrz docstring.
    lost_jobs: [
      {
        job_id: 88,
        title: "Tester Manualny",
        closed_at: "2026-06-01",
        close_reason: null,
        close_notes: "Klient wycofał zapytanie",
        candidate_count_reached: 4,
      },
    ],
  },
};

function renderTab() {
  mocks.apiGet.mockResolvedValue({ data: PROFILE });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProfileTab clientId={42} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.apiGet.mockReset();
});

describe("ProfileTab — brak rekrutacji w Profilu", () => {
  it("nie pokazuje sekcji „Przegrane rekrutacje” nawet gdy dane są niepuste", async () => {
    renderTab();

    // Dowód, że profil się wyrenderował.
    expect(await screen.findByText("Aktywni konsultanci")).toBeInTheDocument();

    expect(screen.queryByText("Przegrane rekrutacje")).not.toBeInTheDocument();
    // Ani sam nagłówek, ani treść wiersza przegranej.
    expect(screen.queryByText("Tester Manualny")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Klient wycofał zapytanie/),
    ).not.toBeInTheDocument();
    // Ani empty-state tej sekcji.
    expect(
      screen.queryByText(/żadna rekrutacja u tego klienta/i),
    ).not.toBeInTheDocument();
  });

  it("nie pokazuje licznika „Otwarte rekrutacje” w pasku podsumowania", async () => {
    renderTab();

    // Pasek podsumowania istnieje i ma pozostałe kafle…
    expect(await screen.findByText("Aktywni konsultanci")).toBeInTheDocument();
    expect(screen.getByText("Aktywne MRR")).toBeInTheDocument();

    // …ale bez duplikatu licznika z zakładki Projekty. `open_jobs: 7`
    // w fixture jest po to, żeby wyciek tej liczby był widoczny.
    expect(screen.queryByText("Otwarte rekrutacje")).not.toBeInTheDocument();
    // `open_jobs: 7` nie może wyciec do żadnego kafla. Szukamy w PASKU
    // PODSUMOWANIA, nie w całym dokumencie: przełącznik zakładek ma własne
    // liczniki, więc globalne `queryByText("7")` fałszywie czerwieniłoby się
    // przy trzech konsultantach albo siedmiu wierszach archiwum.
    const mrrTile = screen.getByText("Aktywne MRR").closest("div");
    const summaryBar = mrrTile?.parentElement?.parentElement;
    expect(summaryBar?.textContent).not.toContain("7");
  });

  it("zostawia sekcję Konsultantów — to kontrakty, nie rekrutacje", async () => {
    renderTab();

    expect(await screen.findByText("Tomasz Sadowski")).toBeInTheDocument();
  });
});

describe("ProfileTab — tabela konsultantów", () => {
  it("Obecni konsultanci mają komplet kolumn BEZ daty zakończenia", async () => {
    renderTab();
    await screen.findByText("Tomasz Sadowski");

    const headers = Array.from(document.querySelectorAll("th")).map((th) =>
      (th.textContent ?? "").trim(),
    );
    expect(headers).toEqual([
      "Konsultant",
      "Start date",
      "Stawka kosztowa",
      "Stawka przychodowa",
      "Marża",
      "Akcje",
    ]);
    // Ta sekcja pokazuje TYLKO aktualnie przypisanych konsultantów, więc data
    // zakończenia nie ma tu prawa istnieć — oni jeszcze nie zakończyli.
    expect(headers).not.toContain("End date");
  });

  it("pokazuje stawki i marżę w osobnych kolumnach", async () => {
    renderTab();
    await screen.findByText("Tomasz Sadowski");

    expect(screen.getByText("12 000,00 zł")).toBeInTheDocument();
    expect(screen.getByText("18 000,00 zł")).toBeInTheDocument();
    expect(screen.getByText("6000,00 zł")).toBeInTheDocument();
  });

  it("rekrutacja stoi pod nazwiskiem, a jej brak zostawia PUSTY wiersz", async () => {
    renderTab();

    expect(
      await screen.findByRole("link", { name: "Specjalista: Engineer DevOps" }),
    ).toBeInTheDocument();
    // Konsultant bez rekrutacji nie dostaje komunikatu zastępczego — tekst
    // w kolumnie danych czyta się jak wartość, a nie jak jej brak.
    expect(screen.getByText("Anna Bez Rekrutacji")).toBeInTheDocument();
    expect(screen.queryByText(/brak powiązanej rekrutacji/i)).toBeNull();
  });

  it("zredagowane kwoty renderują się jako „—”, a nie znikają", async () => {
    // Backend zeruje stawki dla ról bez VIEW_FINANCE. Znikająca komórka
    // zostawiłaby trzy puste kolumny bez wyjaśnienia.
    renderTab();
    await screen.findByText("Anna Bez Rekrutacji");

    const row = screen.getByText("Anna Bez Rekrutacji").closest("tr");
    const cells = Array.from(row?.querySelectorAll("td") ?? []).map((td) =>
      (td.textContent ?? "").trim(),
    );
    expect(cells.slice(2, 5)).toEqual(["—", "—", "—"]);
  });

  it("rekrutacja z zamówienia jest oznaczona, nie zlana z kontraktową", async () => {
    // `Contract.job_id` jest pusty w całej bazie prod, więc fallback na
    // `ClientOrder.job_id` jest jedyną szansą, żeby ta kolumna cokolwiek
    // pokazała. Ale to INNA proweniencja — milczące zlanie obu znaczeń
    // w jednej kolumnie byłoby przemilczeniem, nie uproszczeniem.
    const user = userEvent.setup({ delay: null });
    renderTab();
    await screen.findByText("Tomasz Sadowski");
    // Wiersz z rekrutacją własną kontraktu — bez znacznika.
    expect(screen.queryByText("· z zamówienia")).toBeNull();

    await user.click(screen.getByRole("tab", { name: /Archiwum konsultantów/ }));
    expect(await screen.findByText("Data Engineer")).toBeInTheDocument();
    expect(screen.getByText("· z zamówienia")).toBeInTheDocument();
  });

  it("Archiwum dokłada kolumnę End date", async () => {
    const user = userEvent.setup({ delay: null });
    renderTab();
    await screen.findByText("Tomasz Sadowski");

    await user.click(screen.getByRole("tab", { name: /Archiwum konsultantów/ }));
    await screen.findByText("Marek Archiwalny");

    const headers = Array.from(document.querySelectorAll("th")).map((th) =>
      (th.textContent ?? "").trim(),
    );
    expect(headers).toEqual([
      "Konsultant",
      "Start date",
      "Stawka kosztowa",
      "Stawka przychodowa",
      "Marża",
      "End date",
      "Akcje",
    ]);
    expect(screen.getByText("31.03.2026")).toBeInTheDocument();
    // Archiwum niesie ten sam komplet stawek co „Obecni".
    expect(screen.getByText("21 600,00 zł")).toBeInTheDocument();
    expect(screen.getByText("24 800,00 zł")).toBeInTheDocument();
  });

  it("podzakładki są prawdziwymi tabami (rola + aria-selected)", async () => {
    // Poprzedni, ręcznie zrobiony przełącznik był parą zwykłych przycisków —
    // czytnik ekranu nie wiedział, że to jeden wybór z dwóch.
    renderTab();
    const current = await screen.findByRole("tab", {
      name: /Obecni konsultanci/,
    });
    expect(current).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("tab", { name: /Archiwum konsultantów/ }),
    ).toHaveAttribute("aria-selected", "false");
  });
});
