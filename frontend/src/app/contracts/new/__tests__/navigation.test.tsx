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
  canManageCandidateFinance: () => false,
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
});
