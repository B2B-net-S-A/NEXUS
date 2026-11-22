import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContractEquipmentTab } from "./ContractEquipmentTab";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  contractEquipmentApi: {
    list: mocks.list,
    create: mocks.create,
    update: mocks.update,
    delete: mocks.remove,
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

// Rejestr „Sprzęt” (moduł „Ludzi w NEXUSIE”): domyślnie brak konfiguracji
// i moduł wyłączony (404) — zakładka działa jak przed modułem.
const register = vi.hoisted(() => ({
  config: undefined as unknown,
  holder: undefined as unknown,
}));
vi.mock("@/lib/api/hr", () => ({
  useHrConfig: () => ({ data: register.config }),
}));
vi.mock("@/lib/api/equipment", () => ({
  useClientProvider: () => ({ data: undefined }),
  useHolderEquipment: () => ({ data: register.holder }),
  useContractEquipmentRegister: () =>
    register.holder
      ? { data: register.holder, isLoading: false, isSuccess: true, error: null, refetch: vi.fn() }
      : {
          data: undefined,
          isLoading: false,
          isSuccess: false,
          error: { response: { status: 404 } },
          refetch: vi.fn(),
        },
}));
vi.mock("@/components/equipment/IssueWizard", () => ({
  IssueWizard: () => <div>kreator wydania</div>,
}));
vi.mock("@/components/equipment/ReturnWizard", () => ({
  ReturnWizard: () => <div>kreator zwrotu</div>,
}));

function renderTab(readOnly = true) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ContractEquipmentTab contractId={42} readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

describe("ContractEquipmentTab — read-only", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({
      data: [
        {
          id: 3,
          item_type: "laptop",
          owner: "ours",
          brand_model: "ThinkPad",
          serial_number: "ABC-123",
          handed_over_date: "2026-08-01",
          return_due_date: "2026-09-01",
          returned_date: null,
          return_status: "pending",
          description: null,
        },
      ],
    });
  });

  it("pokazuje sprzęt bez akcji dodania, zwrotu i usunięcia", async () => {
    renderTab();

    expect(await screen.findByText("ThinkPad")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Dodaj sprzęt/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zwrócono/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Akcje")).not.toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
    expect(mocks.update).not.toHaveBeenCalled();
    expect(mocks.remove).not.toHaveBeenCalled();
  });
});

describe("ContractEquipmentTab — pozycje z magazynu (rejestr „Sprzęt”)", () => {
  const manual = {
    id: 3,
    item_type: "laptop",
    owner: "ours",
    brand_model: "ThinkPad",
    serial_number: "ABC-123",
    handed_over_date: "2026-08-01",
    return_due_date: "2026-09-01",
    returned_date: null,
    return_status: "pending",
    description: null,
    item_id: null,
    assignment_id: null,
  };
  const linked = {
    ...manual,
    id: 4,
    brand_model: "Dell Vostro 3530",
    serial_number: "TEST0001",
    item_id: 11,
    assignment_id: 21,
  };
  // To samo wydanie w rejestrze — zakładka pokazuje je raz, z rejestru.
  const issued = {
    assignment_id: 21,
    item_id: 11,
    category: "laptop",
    model_name: "Dell Vostro 3530",
    inventory_number: null,
    serial_number: "TEST0001",
    imei: null,
    phone_number: null,
    access_card_number: null,
    ownership: "nasz",
    item_status: "wydany",
    holder: { kind: "contract", id: 42, name: "Jan Testowy", client_name: null },
    issued_at: "2026-08-01T08:00:00+00:00",
    returned_at: null,
    return_condition: null,
    return_notes: null,
    issue_protocol: null,
    issue_protocol_id: null,
    return_protocol: null,
    return_protocol_id: null,
    unit_value: null,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    register.config = undefined;
    register.holder = undefined;
    mocks.list.mockResolvedValue({ data: [manual, linked] });
  });

  it("bez uprawnienia „Sprzęt” pozycja z magazynu nie ma „Zwrócono” ani usuwania", async () => {
    renderTab(false);

    expect(await screen.findByText("Dell Vostro 3530")).toBeInTheDocument();
    // Wariant A (20.11.2026): numer w kolumnie „Numer”, pochodzenie pod nazwą urządzenia.
    expect(screen.getByText("S/N TEST0001")).toBeInTheDocument();
    expect(screen.getByText("Laptop · nasz · z magazynu")).toBeInTheDocument();
    expect(screen.getByText("zwrot przyjmuje recepcja")).toBeInTheDocument();
    // Ręczny wpis zachowuje dotychczasowe akcje.
    expect(screen.getAllByRole("button", { name: /Zwrócono/i })).toHaveLength(1);
    expect(screen.getByRole("button", { name: /Usuń pozycję: Laptop/i })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Usuń pozycję/i })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Wydaj z magazynu/i })).not.toBeInTheDocument();
  });

  it("recepcja wydaje z magazynu i przyjmuje zwrot kreatorem", async () => {
    register.config = {
      open_modules: { equipment: true },
      me: { equipment: true, is_admin: false },
    };
    register.holder = {
      holder: { kind: "contract", id: 42, name: "Jan Testowy", email: null, detail: null },
      active: [issued],
      history: [],
      protocols: [],
    };
    renderTab(false);

    expect(await screen.findByText("Dell Vostro 3530")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Wydaj z magazynu/i }));
    expect(screen.getByText("kreator wydania")).toBeInTheDocument();
  });

  it("przycisk zwrotu w wierszu otwiera kreator zwrotu", async () => {
    register.config = {
      open_modules: { equipment: true },
      me: { equipment: false, is_admin: true },
    };
    register.holder = {
      holder: { kind: "contract", id: 42, name: "Jan Testowy", email: null, detail: null },
      active: [issued],
      history: [],
      protocols: [],
    };
    renderTab(false);

    const buttons = await screen.findAllByRole("button", { name: /Przyjmij zwrot/i });
    await userEvent.click(buttons[buttons.length - 1]);
    expect(screen.getByText("kreator zwrotu")).toBeInTheDocument();
  });
});
