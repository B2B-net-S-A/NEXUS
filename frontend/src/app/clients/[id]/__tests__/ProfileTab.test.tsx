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
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ContractStructureResponse,
  ExecutiveContractReviewResponse,
} from "@/lib/api/executiveContracts";
import { EZDROWIE_CLIENT_ID } from "@/lib/ezdrowie";
import type { ClientProfileResponse } from "@/types/client-profile";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  // Struktura umów e-Zdrowia — osobny klient API, mockowany per metoda.
  ecStructure: vi.fn(),
  ecReview: vi.fn(),
  ecCreate: vi.fn(),
  ecAssign: vi.fn(),
}));

// Czyste funkcje (`frameworkPartHeader`, `executiveContractOptionGroups`)
// i hooki zostają PRAWDZIWE — podmieniamy wyłącznie metody obiektu API,
// które hooki wołają przez tę samą referencję.
vi.mock("@/lib/api/executiveContracts", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/api/executiveContracts")>();
  Object.assign(actual.executiveContractsApi, {
    structure: (...args: unknown[]) => mocks.ecStructure(...args),
    review: (...args: unknown[]) => mocks.ecReview(...args),
    create: (...args: unknown[]) => mocks.ecCreate(...args),
    assign: (...args: unknown[]) => mocks.ecAssign(...args),
  });
  return { ...actual };
});

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
  api: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  contractsApi: {},
  CONTRACT_TERMINATION_REASONS: [
    { value: "project_ended", label: "Koniec projektu" },
  ],
}));

import { ProfileTab } from "@/app/clients/[id]/ProfileTab";
import { useAuthStore, type User } from "@/store/auth";

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
      // Tabela pokazuje stawki GODZINOWO (MD ÷ 8 po stronie backendu) —
      // wartości różne od miesięcznych, żeby pomylenie pól było mierzalne.
      hourly_rate_candidate: 125,
      hourly_rate_client: 167.5,
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
      hourly_rate_candidate: null,
      hourly_rate_client: null,
      currency: "PLN",
      project_part: null,
    },
  ],
  // Kontrakt aktywny statusem z PRZYSZŁYM startem — planowany, nie obecny
  // (UAT B46). Marża wypełniona, żeby wyciek do „Obecnych" był mierzalny.
  planned_consultants: [
    {
      contract_id: 531,
      candidate: {
        id: 4,
        name: "Piotr Planowany",
        avatar_url: null,
        competence_category: null,
        linkedin: null,
      },
      job_id: null,
      job_title: null,
      job_from_order: false,
      start_date: "2099-10-19",
      end_date: null,
      days_to_end: null,
      monthly_rate_candidate: 9000,
      monthly_rate_client: 15000,
      monthly_margin: 6000,
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
        hourly_rate_candidate: 135,
        hourly_rate_client: 155,
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

function renderTab(clientId = 42, profile: ClientProfileResponse = PROFILE) {
  mocks.apiGet.mockResolvedValue({ data: profile });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProfileTab clientId={clientId} />
    </QueryClientProvider>,
  );
}


// Przyciski zapisu umów wykonawczych widzi tylko admin i przypisany DL
// (`DlAssignedOrAdmin`, audyt 24.09.2026, S11) — testy działają jako admin.
const ADMIN_USER = {
  id: 1,
  email: "admin@example.com",
  name: "Admin",
  role: "admin",
  roles: ["admin"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
} as unknown as User;

beforeEach(() => {
  useAuthStore.setState({ user: ADMIN_USER, hydrated: true });
  mocks.apiGet.mockReset();
  mocks.ecStructure.mockReset();
  mocks.ecReview.mockReset();
  mocks.ecCreate.mockReset();
  mocks.ecAssign.mockReset();
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
      "Stawka kosztowa [godz.]",
      "Stawka przychodowa [godz.]",
      "Marża [mc]",
      "Akcje",
    ]);
    // Ta sekcja pokazuje TYLKO aktualnie przypisanych konsultantów, więc data
    // zakończenia nie ma tu prawa istnieć — oni jeszcze nie zakończyli.
    expect(headers).not.toContain("End date");
  });

  it("pokazuje stawki godzinowe i miesięczną marżę w osobnych kolumnach", async () => {
    renderTab();
    await screen.findByText("Tomasz Sadowski");

    const row = screen.getByText("Tomasz Sadowski").closest("tr");
    // Intl wstawia twardą spację przed „zł" — normalizujemy, liczy się kwota.
    const cells = Array.from(row?.querySelectorAll("td") ?? []).map((td) =>
      (td.textContent ?? "").replace(/\s/g, " ").trim(),
    );
    expect(cells.slice(2, 5)).toEqual(["125,00 zł", "167,50 zł", "6000,00 zł"]);
    // Kwoty miesięczne stawek NIE trafiają już do tabeli.
    expect(screen.queryByText("12 000,00 zł")).toBeNull();
    expect(screen.queryByText("18 000,00 zł")).toBeNull();
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
      "Stawka kosztowa [godz.]",
      "Stawka przychodowa [godz.]",
      "Marża [mc]",
      "End date",
      "Akcje",
    ]);
    expect(screen.getByText("31.03.2026")).toBeInTheDocument();
    // Archiwum niesie ten sam komplet stawek co „Obecni" — też godzinowo.
    expect(screen.getByText("135,00 zł")).toBeInTheDocument();
    expect(screen.getByText("155,00 zł")).toBeInTheDocument();
  });

  it("planowani konsultanci mają własną zakładkę i nie siedzą w Obecnych", async () => {
    const user = userEvent.setup({ delay: null });
    renderTab();
    await screen.findByText("Tomasz Sadowski");

    // Obecni: osoby z kontraktem, który JUŻ obowiązuje — bez przyszłego startu.
    expect(screen.queryByText("Piotr Planowany")).toBeNull();
    expect(screen.getByRole("tab", { name: /Obecni konsultanci/ })).toHaveTextContent("2");
    const plannedTab = screen.getByRole("tab", { name: /Planowani konsultanci/ });
    expect(plannedTab).toHaveTextContent("1");

    await user.click(plannedTab);
    expect(await screen.findByText("Piotr Planowany")).toBeInTheDocument();
    expect(screen.getByText("19.10.2099")).toBeInTheDocument();
    expect(screen.queryByText("Tomasz Sadowski")).toBeNull();
    expect(screen.getByText(/nie wchodzą do „Obecnych”/i)).toBeInTheDocument();
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

// ── Centrum e-Zdrowia: struktura umów wykonawczych ───────────────────────────
// Klient 115 dostaje NAD konsultantami sekcję „Struktura umów" (ramowa → umowy
// wykonawcze), a filtr „Obecnych" grupuje umowy wykonawcze pod częściami.
// Zmyślone osoby i numery — repo jest prywatne, ale zasada jest ta sama.

const EC_UW1 = {
  id: 10,
  number: "CeZ/145/2025/UW-1",
  status: "active" as const,
  framework_contract_id: 2,
  project_part: "cz2",
};
const EC_UW2 = {
  id: 11,
  number: "CeZ/145/2025/UW-2",
  status: "ended" as const,
  framework_contract_id: 2,
  project_part: "cz2",
};
const EC_UW4 = {
  id: 12,
  number: "CeZ/147/2025/UW-1",
  status: "active" as const,
  framework_contract_id: 4,
  project_part: "cz4",
};

const STRUCTURE: ContractStructureResponse = {
  framework_contracts: [
    { id: 1, name: "CeZ/144/2025 – cz. I", project_part: "cz1", status: "active", executive_contracts: [] },
    {
      id: 2,
      name: "CeZ/145/2025 – cz. II",
      project_part: "cz2",
      status: "active",
      executive_contracts: [
        { ...EC_UW1, notes: null, consultants_count: 1, created_at: null },
        { ...EC_UW2, notes: null, consultants_count: 0, created_at: null },
      ],
    },
    {
      id: 4,
      name: "CeZ/147/2025 – cz. IV",
      project_part: "cz4",
      status: "active",
      executive_contracts: [
        { ...EC_UW4, notes: null, consultants_count: 0, created_at: null },
      ],
    },
    { id: 5, name: "CeZ/148/2025 – cz. V", project_part: "cz5", status: "active", executive_contracts: [] },
    { id: 6, name: "CeZ/149/2025 – cz. VI", project_part: "cz6", status: "active", executive_contracts: [] },
  ],
};

const REVIEW: ExecutiveContractReviewResponse = {
  rows: [
    {
      contract_id: 530,
      candidate: { id: 2, name: "Anna Bez Rekrutacji" },
      start_date: "2026-05-04",
      bucket: "active",
      legacy_project_part: "cz2",
      representative_order_id: 900,
      suggested_framework_contract_id: 2,
    },
  ],
  total: 1,
};

const EZDROWIE_PROFILE: ClientProfileResponse = {
  ...PROFILE,
  active_consultants: [
    { ...PROFILE.active_consultants[0], project_part: "cz2", executive_contract: EC_UW1 },
    // Legacy: część wpisana, ale bez umowy wykonawczej — do przeglądu.
    { ...PROFILE.active_consultants[1], project_part: "cz2", executive_contract: null },
  ],
};

function renderEzdrowie() {
  mocks.ecStructure.mockResolvedValue(STRUCTURE);
  mocks.ecReview.mockResolvedValue(REVIEW);
  return renderTab(EZDROWIE_CLIENT_ID, EZDROWIE_PROFILE);
}

describe("ProfileTab — Centrum e-Zdrowia: struktura umów wykonawczych", () => {
  it("u klienta spoza e-Zdrowia nie ma sekcji struktury ani filtra", async () => {
    renderTab();
    await screen.findByText("Tomasz Sadowski");
    expect(screen.queryByText("Struktura umów")).toBeNull();
    expect(screen.queryByRole("group", { name: "Filtr umów wykonawczych" })).toBeNull();
    expect(mocks.ecStructure).not.toHaveBeenCalled();
  });

  it("sekcja „Struktura umów” stoi NAD konsultantami i pokazuje chipy umów", async () => {
    renderEzdrowie();
    const heading = await screen.findByRole("heading", { name: "Struktura umów" });
    const consultants = screen.getByRole("tab", { name: /Obecni konsultanci/ });
    expect(heading.compareDocumentPosition(consultants) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Nagłówek części z numerem umowy ramowej sprzed myślnika (struktura
    // dojeżdża asynchronicznie, nagłówek sekcji jest od razu).
    expect((await screen.findAllByText("Cz. II — CeZ/145/2025")).length).toBeGreaterThan(0);
    // Część bez umów: widoczny tekst, przycisk „Dodaj" przy KAŻDEJ ramowej.
    expect(screen.getAllByText("brak umowy wykonawczej").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: "Dodaj umowę wykonawczą: Cz. I — CeZ/144/2025" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Zakończona")).toBeInTheDocument();
  });

  it("filtr grupuje umowy pod częściami; „Nieprzypisani” zawęża do osób bez umowy", async () => {
    const user = userEvent.setup({ delay: null });
    renderEzdrowie();
    const filter = await screen.findByRole("group", { name: "Filtr umów wykonawczych" });
    await within(filter).findByText("Cz. II — CeZ/145/2025");

    expect(within(filter).getByRole("button", { name: "Wszystkie" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    // Część bez umowy: nagłówek + kursywa, NIE przycisk.
    const noContract = within(filter).getAllByText("brak umowy wykonawczej");
    expect(noContract).toHaveLength(3);
    expect(noContract[0]).toHaveAttribute("aria-disabled", "true");
    expect(within(filter).queryByRole("button", { name: /brak umowy/ })).toBeNull();
    // Umowa zakończona nadal filtruje (są do niej przypisani historycznie).
    expect(
      within(filter).getByRole("button", { name: /CeZ\/145\/2025\/UW-2/ }),
    ).toHaveTextContent("(zakończona)");

    await user.click(within(filter).getByRole("button", { name: "CeZ/145/2025/UW-1" }));
    expect(screen.getByText("Tomasz Sadowski")).toBeInTheDocument();
    expect(screen.queryByText("Anna Bez Rekrutacji", { selector: "a" })).toBeNull();
    expect(screen.getByRole("tab", { name: /Obecni konsultanci/ })).toHaveTextContent("1");

    await user.click(within(filter).getByRole("button", { name: "Nieprzypisani (1)" }));
    expect(screen.queryByText("Tomasz Sadowski")).toBeNull();
    expect(screen.getByRole("link", { name: "Anna Bez Rekrutacji" })).toBeInTheDocument();
  });

  it("badge w tabeli pokazuje NUMER umowy wykonawczej, legacy — samą część", async () => {
    renderEzdrowie();
    const assigned = (await screen.findByText("Tomasz Sadowski")).closest("tr");
    expect(within(assigned as HTMLElement).getByText("CeZ/145/2025/UW-1")).toHaveAttribute(
      "title",
      "E-zdrowie cz.2",
    );
    const legacy = screen.getByRole("link", { name: "Anna Bez Rekrutacji" }).closest("tr");
    expect(within(legacy as HTMLElement).getByText("E-zdrowie cz.2")).toBeInTheDocument();
    expect(within(legacy as HTMLElement).queryByText(/UW-/)).toBeNull();
  });

  it("panel przeglądu: select pusty, grupa tej samej części oznaczona, ale NIE preselekcjonowana", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.ecAssign.mockResolvedValue({
      contract_id: 530,
      order_id: 900,
      executive_contract: EC_UW1,
      created_draft: false,
    });
    renderEzdrowie();
    // Po przypisaniu panel unieważnia przegląd — serwer odsyła już bez wiersza.
    mocks.ecReview.mockResolvedValueOnce(REVIEW).mockResolvedValue({ rows: [], total: 0 });

    const select = await screen.findByRole("combobox", {
      name: "Umowa wykonawcza dla Anna Bez Rekrutacji",
    });
    expect(select).toHaveValue("");
    const groups = Array.from(select.querySelectorAll("optgroup")).map((g) => g.label);
    expect(groups).toEqual([
      "Cz. II — CeZ/145/2025 (ta sama część co dziś)",
      "Cz. IV — CeZ/147/2025",
    ]);
    // Zakończona umowa nie jest do wyboru — backend odmówiłby 422.
    expect(within(select).queryByRole("option", { name: "CeZ/145/2025/UW-2" })).toBeNull();
    expect(screen.getByText("dziś: E-zdrowie cz.2")).toBeInTheDocument();

    const assignBtn = screen.getByRole("button", { name: "Przypisz: Anna Bez Rekrutacji" });
    expect(assignBtn).toBeDisabled();
    await user.selectOptions(select, "10");
    await user.click(assignBtn);

    await waitFor(() =>
      expect(mocks.ecAssign).toHaveBeenCalledWith(EZDROWIE_CLIENT_ID, {
        contract_id: 530,
        executive_contract_id: 10,
      }),
    );
    // Wiersz znika, profil zostaje unieważniony (ponowny GET).
    await waitFor(() =>
      expect(
        screen.queryByRole("combobox", { name: "Umowa wykonawcza dla Anna Bez Rekrutacji" }),
      ).toBeNull(),
    );
    await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledTimes(2));
  });

  it("pusta lista przeglądu = wszyscy przypisani (na isSuccess), awaria = „Ponów”", async () => {
    const user = userEvent.setup({ delay: null });
    mocks.ecStructure.mockResolvedValue(STRUCTURE);
    mocks.ecReview
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce({ rows: [], total: 0 });
    renderTab(EZDROWIE_CLIENT_ID, EZDROWIE_PROFILE);

    const retry = await screen.findByRole("button", { name: /Ponów/ });
    expect(screen.queryByText(/Wszyscy obecni konsultanci/)).toBeNull();
    await user.click(retry);
    expect(
      await screen.findByText("Wszyscy obecni konsultanci mają przypisaną umowę wykonawczą."),
    ).toBeInTheDocument();
  });
});

describe("ProfileTab — audyt 24.09.2026", () => {
  it("kontrakt kandydata usuniętego (RODO) zostaje wierszem bez linku (S6)", async () => {
    renderTab(42, {
      ...PROFILE,
      active_consultants: [
        {
          ...PROFILE.active_consultants[0],
          contract_id: 777,
          candidate: {
            id: null,
            name: "Konsultant usunięty (RODO)",
            avatar_url: null,
            competence_category: null,
            linkedin: null,
          },
        },
      ],
    });
    const name = await screen.findByText("Konsultant usunięty (RODO)");
    expect(name.closest("a")).toBeNull();
  });

  it("przycięte archiwum mówi, ile pokazano z ilu (S7)", async () => {
    const user = userEvent.setup({ delay: null });
    renderTab(42, {
      ...PROFILE,
      historical: { ...PROFILE.historical, placements_total: 250 },
    });
    await screen.findByText("Tomasz Sadowski");
    const archiveTab = screen.getByRole("tab", { name: /Archiwum konsultantów/ });
    expect(archiveTab).toHaveTextContent("250");
    await user.click(archiveTab);
    expect(
      await screen.findByText(/Pokazano 1 najnowszych z 250 zakończonych kontraktów/),
    ).toBeInTheDocument();
  });

  it("„Przedłuż” tylko przy kontrakcie kończącym się (W2)", async () => {
    renderTab(42, {
      ...PROFILE,
      active_consultants: [
        { ...PROFILE.active_consultants[0], contract_status: "ending" },
        { ...PROFILE.active_consultants[1], contract_status: "active" },
      ],
    });
    await screen.findByText("Tomasz Sadowski");
    expect(screen.getAllByRole("button", { name: /Przedłuż/ })).toHaveLength(1);
  });

  it("gdy osób jest mniej niż kontraktów, mówi o tym wprost (N1)", async () => {
    renderTab(42, {
      ...PROFILE,
      summary: { ...PROFILE.summary, active_consultants: 1 },
    });
    await screen.findByText("Tomasz Sadowski");
    expect(screen.getByText(/2 kontrakty · 1 osoba/)).toBeInTheDocument();
  });

  it("awaria profilu ma „Spróbuj ponownie” (S10)", async () => {
    mocks.apiGet.mockRejectedValue({ response: { status: 500 } });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ProfileTab clientId={42} />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Spróbuj ponownie")).toBeInTheDocument();
  });
});
