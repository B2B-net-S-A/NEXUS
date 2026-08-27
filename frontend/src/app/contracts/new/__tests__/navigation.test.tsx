import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  create: vi.fn(),
  push: vi.fn(),
  replace: vi.fn(),
  showSuccess: vi.fn(),
  canManageFinance: false,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: mocks.replace }),
}));

vi.mock("@/components/RequireRole", () => ({
  RequireRole: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: mocks.showSuccess,
    showError: vi.fn(),
  }),
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (state: { user: { role: string } }) => unknown,
  ) => selector({ user: { role: "delivery_lead" } }),
  canManageCandidateFinance: () => mocks.canManageFinance,
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
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

async function fillRequiredFieldsAndSubmit() {
  const user = userEvent.setup({ delay: null });
  renderPage();

  await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
  await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));
  await user.click(screen.getByRole("button", { name: "Utwórz kontrakt" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.canManageFinance = false;
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
      params: { contract_eligible: true },
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

  it("wysyła niezależne waluty stawki przychodowej i kosztowej", async () => {
    mocks.canManageFinance = true;
    mocks.create.mockResolvedValue({ data: { id: 77 } });
    const user = userEvent.setup({ delay: null });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
    await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));

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
    await user.click(screen.getByRole("button", { name: "Utwórz kontrakt" }));

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
