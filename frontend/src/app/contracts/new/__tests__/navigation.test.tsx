import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  create: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
  showSuccess: vi.fn(),
  canManageFinance: false,
  // Prawdziwa bramka `RequirePermission` czyta konto ze store'u.
  user: { role: "delivery_lead" } as {
    role: string;
    roles?: string[];
    effective_action_access?: Record<string, string>;
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: mocks.showSuccess,
    showError: vi.fn(),
  }),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (state: { user: typeof mocks.user; hydrated: boolean }) => unknown,
  ) => selector({ user: mocks.user, hydrated: true }),
  canManageCandidateFinance: () => mocks.canManageFinance,
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  // `fetchRecruitmentRates` (podpowiedź stawek z rekrutacji) używa eksportu nazwanego.
  api: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  contractsApi: {
    create: (...args: unknown[]) => mocks.create(...args),
  },
  extractErrorMsg: () => "Nie udało się utworzyć kontraktu",
  CONTRACT_FIELD_LABELS: {},
}));

// Portale Radix nie są częścią regresji. Treść obu wyszukiwarek renderujemy
// inline i otwieramy je po montażu, aby useQuery pobrał opcje formularza.
vi.mock("@/components/ui/popover", () => ({
  Popover: ({
    children,
    onOpenChange,
  }: {
    children: React.ReactNode;
    onOpenChange?: (open: boolean) => void;
  }) => {
    React.useEffect(() => onOpenChange?.(true), [onOpenChange]);
    return <>{children}</>;
  },
  PopoverTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PopoverContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/components/ui/command", () => ({
  Command: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CommandInput: ({
    value,
    onValueChange,
    placeholder,
  }: {
    value?: string;
    onValueChange?: (value: string) => void;
    placeholder?: string;
  }) => (
    <input
      aria-label={placeholder}
      value={value}
      onChange={(event) => onValueChange?.(event.target.value)}
    />
  ),
  CommandList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CommandEmpty: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CommandGroup: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CommandItem: ({
    children,
    onSelect,
  }: {
    children: React.ReactNode;
    onSelect?: () => void;
  }) => (
    <button type="button" onClick={() => onSelect?.()}>
      {children}
    </button>
  ),
}));

// Formularz używa Radix Select. W jsdom testujemy zmianę wartości i payload,
// nie mechanikę pointer capture/portalu biblioteki, więc mapujemy selecty na
// semantyczne kontrolki natywne.
vi.mock("@/components/ui/select", () => {
  const SelectTrigger = () => null;
  const SelectContent = () => null;
  const SelectItem = () => null;
  const SelectValue = () => null;

  return {
    Select: ({
      children,
      value,
      onValueChange,
      disabled,
    }: {
      children: React.ReactNode;
      value?: string;
      onValueChange?: (value: string) => void;
      disabled?: boolean;
    }) => {
      const elements = React.Children.toArray(children).filter(React.isValidElement);
      const trigger = elements.find((child) => child.type === SelectTrigger) as
        | React.ReactElement<{ "aria-label"?: string }>
        | undefined;
      const content = elements.find((child) => child.type === SelectContent) as
        | React.ReactElement<{ children?: React.ReactNode }>
        | undefined;
      const items = React.Children.toArray(content?.props.children).filter(
        React.isValidElement,
      ) as React.ReactElement<{ value: string; children?: React.ReactNode }>[];

      return (
        <select
          aria-label={trigger?.props["aria-label"]}
          value={value}
          disabled={disabled}
          onChange={(event) => onValueChange?.(event.target.value)}
        >
          <option value="">—</option>
          {items.map((item) => (
            <option key={item.props.value} value={item.props.value}>
              {item.props.children}
            </option>
          ))}
        </select>
      );
    },
    SelectTrigger,
    SelectContent,
    SelectItem,
    SelectValue,
  };
});

import NewContractPage from "../page";

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <NewContractPage />
    </QueryClientProvider>,
  );
}

// Wariant B (20.11.2026): przycisk główny w karcie „Podsumowanie” mówi, co
// powstanie — przy domyślnym statusie „Utwórz szkic” (dawniej „Utwórz kontrakt”).
const CREATE_DRAFT = "Utwórz szkic";

async function fillRequiredFieldsAndSubmit() {
  const user = userEvent.setup({ delay: null });
  renderPage();

  await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
  await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));
  await user.click(screen.getByRole("button", { name: CREATE_DRAFT }));
}

/** Waluty, jednostka, harmonogramy, zużycie i status są w zwiniętych „Zaawansowanych”. */
async function openAdvanced(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Zaawansowane/ }));
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.canManageFinance = false;
  mocks.user = { role: "delivery_lead" };
  mocks.apiGet.mockImplementation((url: string) => {
    if (url === "/api/clients-lookup") {
      return Promise.resolve({ data: [{ id: 2, name: "Klient Testowy" }] });
    }
    if (url === "/api/cv-generator/candidates") {
      return Promise.resolve({
        data: [
          {
            id: 42,
            name: "Jan",
            lastname: "Kowalski",
            full_name: "Jan Kowalski",
            email: "jan@example.com",
          },
        ],
      });
    }
    if (url === "/api/cv-generator/candidates/42/recruitments") {
      return Promise.resolve({ data: [] });
    }
    return Promise.reject(new Error(`Nieoczekiwany GET: ${url}`));
  });
});

describe("Nowy kontrakt — historia nawigacji po zapisie", () => {
  it("zastępuje formularz szczegółami kontraktu, aby Wstecz wracał do listy", async () => {
    mocks.create.mockResolvedValue({ data: { id: 77 } });

    await fillRequiredFieldsAndSubmit();

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({ work_mode: null }),
    );
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/clients-lookup", {
      // Runda 6 audytu: DL widzi w pickerze Kontraktów tylko swój portfel.
      params: { contract_eligible: true, delivery_scope: true },
    });
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/contracts/77"));
    expect(mocks.replace).toHaveBeenCalledTimes(1);
    expect(mocks.push).not.toHaveBeenCalled();
    expect(mocks.showSuccess).toHaveBeenCalledWith("Kontrakt utworzony");
  });

  it("również zastępuje formularz listą, gdy odpowiedź nie zawiera id", async () => {
    mocks.create.mockResolvedValue({ data: {} });

    await fillRequiredFieldsAndSubmit();

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/contracts"));
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("pozwala wyczyścić wcześniej wybraną opcjonalną rekrutację", async () => {
    mocks.apiGet.mockImplementation((url: string) => {
      if (url === "/api/clients-lookup") {
        return Promise.resolve({ data: [{ id: 2, name: "Klient Testowy" }] });
      }
      if (url === "/api/cv-generator/candidates") {
        return Promise.resolve({
          data: [
            {
              id: 42,
              name: "Jan",
              lastname: "Kowalski",
              full_name: "Jan Kowalski",
            },
          ],
        });
      }
      if (url === "/api/cv-generator/candidates/42/recruitments") {
        return Promise.resolve({
          data: [
            {
              stage_id: 7,
              job_id: 17,
              job_title: "Backend Engineer",
            },
          ],
        });
      }
      return Promise.reject(new Error(`Nieoczekiwany GET: ${url}`));
    });
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Rekrutacja" }),
      "7",
    );

    const clearRecruitment = screen.getByRole("button", {
      name: "Wyczyść rekrutację",
    });
    await user.click(clearRecruitment);
    expect(
      screen.queryByRole("button", { name: "Wyczyść rekrutację" }),
    ).not.toBeInTheDocument();
  });

  it("zmiana klienta czyści rekrutację innego klienta, a rekrutację bez klienta zostawia", async () => {
    // UAT B24: rekrutacja poprzedniego klienta zostawała w formularzu po zmianie
    // klienta — backend odrzucał `job_client_mismatch`, ale dopiero przy zapisie.
    mocks.apiGet.mockImplementation((url: string) => {
      if (url === "/api/clients-lookup") {
        return Promise.resolve({
          data: [
            { id: 2, name: "Klient Testowy" },
            { id: 3, name: "Inny Klient" },
          ],
        });
      }
      if (url === "/api/cv-generator/candidates") {
        return Promise.resolve({
          data: [{ id: 42, name: "Jan", lastname: "Kowalski", full_name: "Jan Kowalski" }],
        });
      }
      if (url === "/api/cv-generator/candidates/42/recruitments") {
        return Promise.resolve({
          data: [
            { stage_id: 7, job_id: 17, job_title: "Backend Engineer", client_id: 2 },
            { stage_id: 8, job_id: 18, job_title: "Bez klienta", client_id: null },
          ],
        });
      }
      return Promise.reject(new Error(`Nieoczekiwany GET: ${url}`));
    });
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
    const recruitment = screen.getByRole("combobox", { name: "Rekrutacja" });
    await user.selectOptions(recruitment, "7");

    // Klient zgodny z rekrutacją — nic nie znika.
    await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));
    expect(recruitment).toHaveValue("7");

    // Inny klient — rekrutacja poprzedniego klienta zostaje wyczyszczona.
    await user.click(screen.getByRole("button", { name: /Inny Klient/ }));
    expect(recruitment).toHaveValue("");
    expect(
      screen.queryByRole("button", { name: "Wyczyść rekrutację" }),
    ).not.toBeInTheDocument();

    // Po wyborze innego klienta lista nie oferuje rekrutacji poprzedniego
    // (retest UAT B24: dało się ją wybrać ponownie z listy).
    expect(
      within(recruitment).queryByRole("option", { name: "Backend Engineer" }),
    ).not.toBeInTheDocument();

    // Rekrutacja bez klienta nie jest sprzeczna z żadnym — zostaje.
    await user.selectOptions(recruitment, "8");
    await user.click(screen.getByRole("button", { name: /Klient Testowy/ }));
    expect(recruitment).toHaveValue("8");
  });

  it("wysyła niezależne waluty stawki przychodowej i kosztowej", async () => {
    mocks.canManageFinance = true;
    mocks.create.mockResolvedValue({ data: { id: 77 } });
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
    await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));
    await openAdvanced(user);

    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "Waluta stawki przychodowej (klienta)",
      }),
      "EUR",
    );
    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "Waluta stawki kosztowej (kandydata / umowy ramowej)",
      }),
      "PLN",
    );
    await user.click(screen.getByRole("button", { name: CREATE_DRAFT }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        rate_client_currency: "EUR",
        rate_candidate_currency: "PLN",
      }),
    );
    expect(mocks.create.mock.calls[0]?.[0]).not.toHaveProperty("currency");
  });
});

describe("Nowy kontrakt — awaria wyszukiwarek to nie pusta lista", () => {
  it("błąd wyszukiwania kandydata i listy klientów daje „Ponów”, nie „Brak wyników.”", async () => {
    mocks.apiGet.mockRejectedValue(new Error("503"));
    renderPage();

    expect(
      await screen.findByText("Nie udało się wyszukać kandydatów."),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Nie udało się pobrać listy klientów."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak wyników.")).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Ponów/ })).toHaveLength(2);
  });

  it("puste wyniki nadal mówią „Brak wyników.”", async () => {
    mocks.apiGet.mockResolvedValue({ data: [] });
    renderPage();

    await waitFor(() => expect(screen.getAllByText("Brak wyników.")).toHaveLength(2));
  });
});

/** Komplet kluczy z `/api/auth/me` — bez `delivery_view` profil liczyłby się z ról. */
function snapshot(...granted: string[]): Record<string, string> {
  const keys = [
    "delivery_view",
    "clients_edit",
    "contracts_orders_edit",
    "contract_status",
    "b2b_signature_confirmation",
    "recruitment_manage",
    "amounts_view",
    "amounts_edit",
    "finance_module",
  ];
  return Object.fromEntries(
    keys.map((key) => [key, granted.includes(key) ? "manage" : "none"]),
  );
}

describe("Nowy kontrakt — formularz widzi posiadacz uprawnienia, nie rola", () => {
  const DENIAL =
    /Brakuje Ci uprawnienia „Kontrakty i zamówienia: tworzenie i edycja”/;

  it("Finanse mają uprawnienie domyślnie i widzą formularz", async () => {
    mocks.user = { role: "finance" };
    renderPage();

    expect(
      await screen.findByRole("button", { name: CREATE_DRAFT }),
    ).toBeInTheDocument();
    expect(screen.queryByText(DENIAL)).not.toBeInTheDocument();
  });

  it("rekruter bez uprawnienia dostaje nazwę brakującej pozycji zamiast formularza", async () => {
    mocks.user = { role: "recruiter" };
    renderPage();

    expect(await screen.findByText(DENIAL)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: CREATE_DRAFT }),
    ).not.toBeInTheDocument();
    expect(mocks.apiGet).not.toHaveBeenCalled();
  });

  it("osoba z nadanym uprawnieniem widzi formularz mimo roli spoza domyślnych", async () => {
    mocks.user = {
      role: "talent_community_manager",
      effective_action_access: snapshot("delivery_view", "contracts_orders_edit"),
    };
    renderPage();

    expect(
      await screen.findByRole("button", { name: CREATE_DRAFT }),
    ).toBeInTheDocument();
  });

  it("Delivery Lead z wyłączonym uprawnieniem nie widzi formularza", async () => {
    mocks.user = {
      role: "delivery_lead",
      effective_action_access: snapshot("delivery_view", "clients_edit"),
    };
    renderPage();

    expect(await screen.findByText(DENIAL)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: CREATE_DRAFT }),
    ).not.toBeInTheDocument();
  });
});

/** Tekst bez spacji twardych z formatowania kwot. */
function plainText(element: Element): string {
  return (element.textContent ?? "").replace(/ /g, " ");
}

describe("Nowy kontrakt — karta „Podsumowanie” (wariant B)", () => {
  function recruitmentRatesFor(rate: Record<string, unknown> | null) {
    mocks.apiGet.mockImplementation((url: string) => {
      if (url === "/api/clients-lookup") {
        return Promise.resolve({ data: [{ id: 2, name: "Klient Testowy" }] });
      }
      if (url === "/api/cv-generator/candidates") {
        return Promise.resolve({
          data: [{ id: 42, name: "Jan", lastname: "Kowalski", full_name: "Jan Kowalski" }],
        });
      }
      if (url === "/api/cv-generator/candidates/42/recruitments") {
        return Promise.resolve({
          data: [{ stage_id: 7, job_id: 17, job_title: "Backend Engineer", client_id: 2 }],
        });
      }
      if (url === "/api/clients/2/recruitment-rates") {
        return Promise.resolve({ data: { rate, amounts_redacted: false } });
      }
      return Promise.reject(new Error(`Nieoczekiwany GET: ${url}`));
    });
  }

  it("liczy marżę na godzinę i w miesiącu ze stawek wpisanych w formularzu", async () => {
    mocks.canManageFinance = true;
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
    await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));
    await user.type(screen.getByLabelText(/Klient płaci/), "157");
    await user.type(screen.getByLabelText(/Konsultant dostaje/), "110");

    const summary = screen.getByRole("region", { name: "Podsumowanie" });
    expect(plainText(summary)).toContain("47,00 zł/h · 29,9 %");
    expect(plainText(summary)).toContain("Miesięcznie (168 h)");
    expect(plainText(summary)).toContain("≈ 7 896 zł");
    expect(plainText(summary)).toContain("Po utworzeniu: szkic");
  });

  it("bez uprawnienia do kwot karta nie pokazuje stawek ani marży", async () => {
    renderPage();

    const summary = await screen.findByRole("region", { name: "Podsumowanie" });
    expect(within(summary).queryByText("Klient płaci")).not.toBeInTheDocument();
    expect(within(summary).queryByText(/Miesięcznie/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Klient płaci/)).not.toBeInTheDocument();
    expect(screen.getByText(/tu kontrakt powstaje bez kwot/)).toBeInTheDocument();
  });

  it("różne waluty stawek: przychód i koszt zostają, marży nie liczymy", async () => {
    mocks.canManageFinance = true;
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
    await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));
    await user.type(screen.getByLabelText(/Klient płaci/), "40");
    await user.type(screen.getByLabelText(/Konsultant dostaje/), "110");
    await openAdvanced(user);
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Waluta stawki przychodowej (klienta)" }),
      "EUR",
    );

    const summary = screen.getByRole("region", { name: "Podsumowanie" });
    expect(plainText(summary)).toContain("Różne waluty stawek (EUR / PLN) — marży nie liczymy.");
    expect(plainText(summary)).toContain("6 720 EUR");
    expect(plainText(summary)).not.toContain("%");
  });

  it("status z „Zaawansowanych” zmienia przycisk i wysyła się w zapisie", async () => {
    mocks.canManageFinance = true;
    mocks.create.mockResolvedValue({ data: { id: 77 } });
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
    await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));
    await user.type(screen.getByLabelText(/Klient płaci/), "157");
    await user.type(screen.getByLabelText(/Konsultant dostaje/), "110");
    await openAdvanced(user);
    await user.click(screen.getByRole("radio", { name: "Aktywny" }));
    await user.click(screen.getByRole("button", { name: "Utwórz jako aktywny" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        status: "active",
        rate_client: 157,
        candidate_rate_schedule: [
          expect.objectContaining({ rate: 110, effective_to: null }),
        ],
      }),
    );
  });

  it("odmowa statusu „Aktywny” bez kwot rozwija „Zaawansowane” z komunikatem przy polu", async () => {
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
    await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));
    await openAdvanced(user);
    await user.click(screen.getByRole("radio", { name: "Aktywny" }));
    // Zwinięcie sekcji nie chowa błędu — po odmowie rozwinie się sama.
    await user.click(screen.getByRole("button", { name: /Zaawansowane/ }));
    await user.click(screen.getByRole("button", { name: "Utwórz jako aktywny" }));

    expect(
      await screen.findByText(/Aktywacja wymaga stawek/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zaawansowane/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Uzupełnij brakujące pola");
    expect(mocks.create).not.toHaveBeenCalled();
  });

  it("„Kończący się” nie jest do wyboru przy umowie B2B", async () => {
    const user = userEvent.setup({ delay: null });
    renderPage();

    await screen.findByRole("region", { name: "Podsumowanie" });
    await openAdvanced(user);
    expect(screen.queryByRole("radio", { name: "Kończący się" })).not.toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Typ umowy" }), "uop");
    expect(screen.getByRole("radio", { name: "Kończący się" })).toBeInTheDocument();
  });

  it("stawka konsultanta z rekrutacji wpisuje się dopiero po „Użyj”; stawka klienta jest samą informacją", async () => {
    mocks.canManageFinance = true;
    recruitmentRatesFor({
      candidate_id: 42,
      job_id: 17,
      job_title: "Backend Engineer",
      client_rate_value: 157,
      client_rate_unit: "hourly",
      client_rate_currency: "PLN",
      client_rate_at: "2026-10-27",
      client_rate_by_name: "Anna Przykładowa",
      client_rate_redacted: false,
      candidate_rate_value: 110,
      candidate_rate_unit: "hourly",
      candidate_rate_currency: "PLN",
      candidate_rate_at: "2026-10-26",
    });
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
    await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));

    // Bez wybranej rekrutacji nie pytamy: najnowsza para u klienta bywa sprzed lat.
    expect(mocks.apiGet).not.toHaveBeenCalledWith(
      "/api/clients/2/recruitment-rates",
      expect.anything(),
    );
    expect(screen.queryByText(/w rekrutacji:/)).not.toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Rekrutacja" }), "7");

    const candidateRate = screen.getByLabelText(/Konsultant dostaje/);
    expect(candidateRate).toHaveValue("");
    expect(
      await screen.findByText(/w rekrutacji: 157,00\s+zł\/h · Anna Przykładowa, 27\.10\.2026/),
    ).toBeInTheDocument();
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/clients/2/recruitment-rates", {
      params: { candidate_id: 42, job_id: 17 },
    });
    // Jedno „Użyj” — przy stawce konsultanta; nic nie wpisało się samo.
    expect(screen.getAllByRole("button", { name: "Użyj" })).toHaveLength(1);
    expect(screen.getByLabelText(/Klient płaci/)).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "Użyj" }));
    expect(candidateRate).toHaveValue("110,00");
    expect(screen.getByText(/z rekrutacji: 110,00\s+zł\/h · 26\.10\.2026/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Użyj" })).not.toBeInTheDocument();
  });
});
