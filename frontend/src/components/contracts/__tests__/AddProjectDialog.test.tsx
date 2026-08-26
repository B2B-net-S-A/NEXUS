import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  create: vi.fn(),
  push: vi.fn(),
  showSuccess: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess }),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  contractsApi: {
    create: (...args: unknown[]) => mocks.create(...args),
  },
  extractErrorMsg: () => "Nie udało się dodać projektu",
  CONTRACT_FIELD_LABELS: {},
}));

// Zachowujemy prawdziwy formularz i jego przyciski, a upraszczamy wyłącznie
// warstwę portali Radix. Dzięki temu test sprawdza handleSubmit i rzeczywisty
// payload, nie szczegóły pozycjonowania modala/popovera niedostępne w jsdom.
vi.mock("@/components/ds/AppModal", () => ({
  AppModal: ({
    open,
    title,
    description,
    footer,
    children,
  }: {
    open: boolean;
    title: string;
    description?: string;
    footer?: React.ReactNode;
    children: React.ReactNode;
  }) =>
    open ? (
      <section aria-label={title}>
        <h1>{title}</h1>
        {description ? <p>{description}</p> : null}
        {children}
        {footer}
      </section>
    ) : null,
}));

vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: React.ReactNode }) => <>{children}</>,
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

import { AddProjectDialog } from "@/components/contracts/AddProjectDialog";

function renderDialog({ canManageFinance = true } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AddProjectDialog
        open
        onOpenChange={vi.fn()}
        candidateId={42}
        candidateName="Jan Kowalski"
        baseContract={{
          id: 10,
          client_id: 1,
          contract_type: "b2b",
          rate_unit: "monthly",
          currency: "PLN",
          billing_hours_per_month: 160,
          work_mode: "remote",
        }}
        canManageFinance={canManageFinance}
      />
    </QueryClientProvider>,
  );
}

async function selectClient(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /Klient Testowy/ }));
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.apiGet.mockImplementation((url: string) => {
    if (url === "/api/clients-lookup") {
      return Promise.resolve({ data: [{ id: 2, name: "Klient Testowy Sp. z o.o." }] });
    }
    if (url === "/api/jobs") {
      return Promise.resolve({ data: { items: [] } });
    }
    return Promise.reject(new Error(`Nieoczekiwany GET: ${url}`));
  });
  mocks.create.mockResolvedValue({
    data: { id: 77, client_id: 2, draft_order_id: 88 },
  });
});

describe("AddProjectDialog", () => {
  it("zapisuje aktywny projekt bez daty zakończenia jako bezterminowy", async () => {
    const user = userEvent.setup({ delay: null });
    renderDialog();

    await selectClient(user);
    await user.type(screen.getByPlaceholderText("np. 125,00"), "125,00");
    await user.type(screen.getByPlaceholderText("np. 175,00"), "175,00");
    await user.click(screen.getByRole("button", { name: "Dodaj projekt" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        candidate_id: 42,
        client_id: 2,
        start_date: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
        end_date: null,
        rate_candidate: 125,
        rate_client: 175,
        work_mode: "remote",
        status: "active",
        source_contract_id: 10,
      }),
    );
    expect(
      screen.queryByText("Status „Aktywny” wymaga daty zakończenia."),
    ).not.toBeInTheDocument();
    expect(mocks.showSuccess).toHaveBeenCalledWith(
      "Dodano kolejny projekt i utworzono szkic zamówienia",
    );
  });

  it("nadal blokuje zapis bez wymaganej daty rozpoczęcia", async () => {
    const user = userEvent.setup({ delay: null });
    const { container } = renderDialog({ canManageFinance: false });

    await selectClient(user);
    const startDateInput = container.querySelector<HTMLInputElement>('input[type="date"]');
    expect(startDateInput).not.toBeNull();
    fireEvent.change(startDateInput!, { target: { value: "" } });
    await user.click(screen.getByRole("button", { name: "Dodaj projekt" }));

    expect(mocks.create).not.toHaveBeenCalled();
    expect(
      screen.getByText("Podaj datę rozpoczęcia nowego projektu."),
    ).toBeInTheDocument();
  });

  it("dla klienta kosztowego kieruje do jawnego wyboru typu zamówienia", async () => {
    mocks.create.mockResolvedValueOnce({
      data: { id: 77, client_id: 2, draft_order_id: null },
    });
    const user = userEvent.setup({ delay: null });
    renderDialog();

    await selectClient(user);
    await user.type(screen.getByPlaceholderText("np. 125,00"), "125,00");
    await user.type(screen.getByPlaceholderText("np. 175,00"), "175,00");
    await user.click(screen.getByRole("button", { name: "Dodaj projekt" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.showSuccess).toHaveBeenCalledWith(
      "Dodano kolejny projekt — zamówienie dodaj w zakładce klienta i wybierz typ rozliczenia",
    );
  });
});
