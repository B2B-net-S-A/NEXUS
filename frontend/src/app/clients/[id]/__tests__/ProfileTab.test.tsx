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
// komponenty potomne Profilu (`PlacementRow`, `TerminateContractModal`) —
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
    total_placements: 12,
    active_mrr: 45000,
    ltv: 900000,
    avg_time_to_fill_days: 21,
  },
  open_jobs: [],
  // Bez rzutowań `as unknown as`: pierwsza wersja tego fixture'u miała zły
  // kształt konsultanta (płaskie `candidate_name` zamiast obiektu `candidate`),
  // a rzutowanie zdusiło dokładnie ten błąd, który typy by pokazały — test
  // wywalił się dopiero w runtime, na `ConsultantRow`.
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
      start_date: "2026-07-27",
      end_date: null,
      days_to_end: null,
      monthly_rate_client: 18000,
      monthly_margin: 6000,
      currency: "PLN",
      project_part: null,
    },
  ],
  historical: {
    placements: [],
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
    expect(screen.queryByText("7")).not.toBeInTheDocument();
  });

  it("zostawia sekcję Konsultantów — to kontrakty, nie rekrutacje", async () => {
    renderTab();

    expect(await screen.findByText("Tomasz Sadowski")).toBeInTheDocument();
  });
});
