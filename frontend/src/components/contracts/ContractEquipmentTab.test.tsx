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

// Rejestr „Sprzęt” (moduł „Ludzi w NEXUSIE”): domyślnie brak konfiguracji —
// zakładka działa jak przed modułem.
const register = vi.hoisted(() => ({
  config: undefined as unknown,
  holder: undefined as unknown,
}));
vi.mock("@/lib/api/hr", () => ({
  useHrConfig: () => ({ data: register.config }),
}));
vi.mock("@/lib/api/equipment", () => ({
  useHolderEquipment: () => ({ data: register.holder }),
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

  beforeEach(() => {
    vi.clearAllMocks();
    register.config = undefined;
    register.holder = undefined;
    mocks.list.mockResolvedValue({ data: [manual, linked] });
  });

  it("bez uprawnienia „Sprzęt” pozycja z magazynu nie ma „Zwrócono” ani usuwania", async () => {
    renderTab(false);

    expect(await screen.findByText("Dell Vostro 3530")).toBeInTheDocument();
    expect(screen.getByText(/TEST0001 · z magazynu/)).toBeInTheDocument();
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
      active: [{ assignment_id: 21 }],
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
      active: [{ assignment_id: 21 }],
      history: [],
      protocols: [],
    };
    renderTab(false);

    const buttons = await screen.findAllByRole("button", { name: /Przyjmij zwrot/i });
    await userEvent.click(buttons[buttons.length - 1]);
    expect(screen.getByText("kreator zwrotu")).toBeInTheDocument();
  });
});
