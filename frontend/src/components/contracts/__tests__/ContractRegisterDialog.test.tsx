import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  contractsApi: {
    create: (...args: unknown[]) => mocks.create(...args),
    update: (...args: unknown[]) => mocks.update(...args),
  },
  extractErrorMsg: () => "Nie udało się zapisać kontraktu",
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
  }),
}));

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DialogContent: ({ children }: { children: React.ReactNode }) => (
    <section>{children}</section>
  ),
  DialogDescription: ({ children }: { children: React.ReactNode }) => (
    <p>{children}</p>
  ),
  DialogFooter: ({ children }: { children: React.ReactNode }) => (
    <footer>{children}</footer>
  ),
  DialogHeader: ({ children }: { children: React.ReactNode }) => (
    <header>{children}</header>
  ),
  DialogTitle: ({ children }: { children: React.ReactNode }) => (
    <h1>{children}</h1>
  ),
  DialogBody: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

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

vi.mock("@/components/contracts/CandidateRateScheduleFields", () => ({
  CandidateRateScheduleFields: ({
    onChange,
  }: {
    onChange: (rows: Array<{ rate: string; effectiveFrom: string }>) => void;
  }) => (
    <label>
      Stawka kosztowa
      <input
        aria-label="Stawka kosztowa"
        onChange={(event) =>
          onChange([{ rate: event.target.value, effectiveFrom: "" }])
        }
      />
    </label>
  ),
}));

import { ContractRegisterDialog } from "@/components/contracts/ContractRegisterDialog";

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ContractRegisterDialog
        open
        onOpenChange={vi.fn()}
        clientId={11}
        clientName="Klient Testowy"
        onSaved={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.apiGet.mockResolvedValue({
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
  mocks.create.mockResolvedValue({ data: { id: 563 } });
});

describe("ContractRegisterDialog — waluta stawki kosztowej", () => {
  it("wysyła wybraną walutę kandydata bez legacy currency", async () => {
    const user = userEvent.setup({ delay: null });
    renderDialog();

    await user.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
    await user.type(screen.getByRole("textbox", { name: "Stawka kosztowa" }), "125");
    await user.selectOptions(
      screen.getByRole("combobox", {
        name: "Waluta stawki kosztowej (kandydata)",
      }),
      "EUR",
    );
    await user.click(screen.getByRole("button", { name: "Dodaj kontrakt" }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.create).toHaveBeenCalledWith(
      expect.objectContaining({
        client_id: 11,
        candidate_id: 42,
        rate_candidate_currency: "EUR",
        candidate_rate_schedule: [
          expect.objectContaining({ rate: 125 }),
        ],
      }),
    );
    expect(mocks.create.mock.calls[0]?.[0]).not.toHaveProperty("currency");
  });
});
