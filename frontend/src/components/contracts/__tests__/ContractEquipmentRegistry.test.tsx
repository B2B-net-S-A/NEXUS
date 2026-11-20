/**
 * Zakładka „Sprzęt” kontraktu czyta rejestr „Sprzęt”, nie tylko wpisy ręczne
 * (zgłoszenie 19.11.2026).
 *
 * Na kopii produkcji z 19.11 tabela wpisów ręcznych `contract_equipment` miała
 * 0 wierszy, a 27 obowiązujących kontraktów miało niezwrócone urządzenia
 * w rejestrze (wydania z importu plików recepcji nie zakładają wpisów
 * zakładki). Zakładka mówiła „Sprzęt kontraktora (0) — Brak pozycji” obok
 * „Przyjmij zwrot”, więc przy końcu współpracy nikt nie widział, co odebrać.
 *
 * Test mockuje tylko granicę HTTP (`api.get`), hooki rejestru są prawdziwe.
 * Dane fikcyjne — repo jest publiczne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  update: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get },
  contractEquipmentApi: {
    list: (contractId: number) => mocks.get(`/api/contracts/${contractId}/equipment`),
    create: vi.fn(),
    update: mocks.update,
    delete: mocks.remove,
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

vi.mock("@/components/equipment/IssueWizard", () => ({
  IssueWizard: () => <div>kreator wydania</div>,
}));
vi.mock("@/components/equipment/ReturnWizard", () => ({
  ReturnWizard: () => <div>kreator zwrotu</div>,
}));

import { ContractEquipmentTab } from "../ContractEquipmentTab";

const CONTRACT_ID = 474;
const HOLDER = {
  kind: "contract",
  id: CONTRACT_ID,
  name: "Jan Testowy",
  email: null,
  detail: "Klient Testowy",
};

function assignment(overrides: Record<string, unknown>) {
  return {
    assignment_id: 1,
    item_id: 1,
    category: "laptop",
    model_name: "Laptop Testowy 14",
    inventory_number: null,
    serial_number: null,
    imei: null,
    phone_number: null,
    access_card_number: null,
    ownership: "nasz",
    item_status: "wydany",
    holder: { kind: "contract", id: CONTRACT_ID, name: "Jan Testowy", client_name: null },
    issued_at: "2026-10-18T08:00:00+00:00",
    returned_at: null,
    return_condition: null,
    return_notes: null,
    issue_protocol: null,
    issue_protocol_id: null,
    return_protocol: null,
    return_protocol_id: null,
    unit_value: null,
    ...overrides,
  };
}

const LAPTOP = assignment({
  assignment_id: 60,
  item_id: 113,
  model_name: "Laptop Testowy 14",
  inventory_number: "T-001",
  serial_number: "TESTSN0001",
});
const MONITOR = assignment({
  assignment_id: 153,
  item_id: 271,
  category: "monitor",
  model_name: "Monitor Testowy 24",
  serial_number: "TESTSN0002",
});
const CARD = assignment({
  assignment_id: 272,
  item_id: 427,
  category: "karta_dostepu",
  model_name: "Karta dostępu",
  access_card_number: "0001",
});

function manualRow(overrides: Record<string, unknown>) {
  return {
    id: 1,
    contract_id: CONTRACT_ID,
    item_type: "phone",
    owner: "client",
    brand_model: "Telefon od klienta",
    serial_number: "TESTSN0009",
    description: null,
    deposit_amount: null,
    deposit_currency: null,
    handed_over_date: "2026-08-01",
    return_due_date: null,
    returned_date: null,
    return_status: "pending",
    notes: null,
    created_at: "2026-08-01T08:00:00+00:00",
    updated_at: "2026-08-01T08:00:00+00:00",
    item_id: null,
    assignment_id: null,
    ...overrides,
  };
}

interface Api {
  config?: { equipment: boolean };
  registry?: unknown;
  registryError?: number;
  manual?: unknown[];
}

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
}

function routeApi({ config = { equipment: false }, registry, registryError, manual = [] }: Api) {
  mocks.get.mockImplementation(async (url: string) => {
    if (url === "/api/hr/config") {
      return {
        data: {
          program: true,
          modules: { equipment: true },
          open_modules: { equipment: true },
          me: { equipment: config.equipment, is_admin: false },
        },
      };
    }
    if (url === `/api/contracts/${CONTRACT_ID}/equipment`) return { data: manual };
    if (
      url === `/api/equipment/contracts/${CONTRACT_ID}` ||
      url === `/api/equipment/holders/contract/${CONTRACT_ID}`
    ) {
      if (registryError) throw httpError(registryError);
      const body = registry as Record<string, unknown>;
      return {
        data: url.includes("/holders/") ? { holder: HOLDER, ...body } : body,
      };
    }
    throw httpError(404);
  });
}

function renderTab(readOnly = false) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ContractEquipmentTab contractId={CONTRACT_ID} readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ContractEquipmentTab — urządzenia z rejestru „Sprzęt”", () => {
  it("Delivery widzi urządzenia wydane z rejestru, a licznik je liczy (kontrakt #474)", async () => {
    routeApi({ registry: { active: [LAPTOP, MONITOR, CARD], history: [], protocols: [] } });
    renderTab();

    expect(
      await screen.findByRole("heading", { name: "Sprzęt u konsultanta 3 u konsultanta" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Laptop Testowy 14")).toBeInTheDocument();
    expect(screen.getByText("Monitor Testowy 24")).toBeInTheDocument();
    expect(screen.getByText(/TESTSN0001/)).toBeInTheDocument();
    expect(screen.getAllByText("z magazynu · bez protokołu")).toHaveLength(3);
    expect(screen.queryByText(/Brak pozycji/)).not.toBeInTheDocument();
    // Bez uprawnienia „Sprzęt” zwrot przyjmuje recepcja — przy każdej pozycji.
    expect(screen.getAllByText("zwrot przyjmuje recepcja")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /Zwrócono/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Usuń pozycję/ })).not.toBeInTheDocument();
  });

  it("pokazuje też zwrócone, zostawia wpisy ręczne i nie dubluje pozycji z wydania", async () => {
    const returned = assignment({
      assignment_id: 70,
      item_id: 200,
      model_name: "Laptop Zwrócony 13",
      serial_number: "TESTSN0003",
      issued_at: "2026-06-01T08:00:00+00:00",
      returned_at: "2026-09-30T08:00:00+00:00",
      return_condition: "sprawny",
    });
    routeApi({
      registry: { active: [LAPTOP], history: [returned], protocols: [] },
      manual: [
        manualRow({ id: 5 }),
        // Wpis zakładki założony przy wydaniu kreatorem — ta sama rzecz co LAPTOP.
        manualRow({
          id: 6,
          item_type: "laptop",
          owner: "ours",
          brand_model: "Laptop Testowy 14",
          serial_number: "TESTSN0001",
          return_due_date: "2027-01-31",
          item_id: 113,
          assignment_id: 60,
        }),
      ],
    });
    renderTab();

    expect(
      await screen.findByRole("heading", { name: "Sprzęt u konsultanta 2 u konsultanta · 1 zwrócone" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Laptop Testowy 14")).toHaveLength(1);
    expect(screen.getByText("Laptop Zwrócony 13")).toBeInTheDocument();
    expect(screen.getByText("Telefon od klienta")).toBeInTheDocument();
    expect(screen.getByText("zwrócony")).toBeInTheDocument();
    // Termin zwrotu z wpisu zakładki zostaje przy pozycji z rejestru.
    expect(screen.getByText("zwrot do 31.01.2027")).toBeInTheDocument();
    // Ręczny wpis zachowuje swoje akcje.
    expect(screen.getAllByRole("button", { name: /Zwrócono/ })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /Usuń pozycję/ })).toHaveLength(1);
  });

  it("anulowane wydanie nie wraca na listę jako zwrócone", async () => {
    const cancelled = assignment({
      assignment_id: 80,
      item_id: 300,
      model_name: "Laptop z Anulowanego",
      returned_at: "2026-10-20T08:00:00+00:00",
      return_condition: "sprawny",
      return_notes: "Anulowany protokół PZO/2026/10/1",
      issue_protocol: "PZO/2026/10/1",
      issue_protocol_id: 9,
    });
    routeApi({
      registry: {
        active: [LAPTOP],
        history: [cancelled],
        protocols: [
          { id: 9, number: "PZO/2026/10/1", kind: "wydanie", status: "anulowany", protocol_date: "2026-10-20" },
        ],
      },
    });
    renderTab();

    expect(
      await screen.findByRole("heading", { name: "Sprzęt u konsultanta 1 u konsultanta" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Laptop z Anulowanego")).not.toBeInTheDocument();
  });

  it("recepcja przyjmuje zwrot z wiersza urządzenia z rejestru", async () => {
    routeApi({
      config: { equipment: true },
      registry: { active: [LAPTOP], history: [], protocols: [] },
    });
    renderTab();

    await screen.findByRole("heading", { name: "Sprzęt u konsultanta 1 u konsultanta" });
    // Przycisk w nagłówku (po odczycie posiadacza) i w wierszu.
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /Przyjmij zwrot/ })).toHaveLength(2),
    );
    const buttons = screen.getAllByRole("button", { name: /Przyjmij zwrot/ });
    await userEvent.click(buttons[1]);
    expect(screen.getByText("kreator zwrotu")).toBeInTheDocument();
  });

  it("moduł „Sprzęt” wyłączony (404): zakładka jak dotąd, z wpisów ręcznych", async () => {
    routeApi({ registryError: 404, manual: [manualRow({ id: 5 })] });
    renderTab();

    expect(
      await screen.findByRole("heading", { name: "Sprzęt u konsultanta 1 u konsultanta" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Telefon od klienta")).toBeInTheDocument();
    expect(screen.queryByText("Nie udało się pobrać danych")).not.toBeInTheDocument();
  });

  it("awaria rejestru nie wygląda jak „Brak pozycji”", async () => {
    routeApi({ registryError: 500, manual: [] });
    renderTab();

    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText(/Brak pozycji/)).not.toBeInTheDocument();
    // Bez liczby przy awarii — zaniżona liczba czytałaby się jak „nic nie wydano”.
    expect(screen.getByRole("heading", { name: "Sprzęt u konsultanta" })).toBeInTheDocument();
  });
});
