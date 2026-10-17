import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const del = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    delete: (...a: unknown[]) => del(...a),
  },
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { IntuneTab } from "@/components/equipment/IntuneTab";
import { deviceLabel, intuneStatusTone } from "@/components/equipment/intune-format";
import type {
  IntuneDevice,
  IntuneDiscrepancies,
  IntuneDiscrepancy,
  IntuneStatus,
} from "@/lib/api/equipment-intune";

// Dane fikcyjne — repo jest publiczne.
const LIVE: IntuneStatus = {
  mode: "live",
  health: "healthy",
  last_run_at: "2026-10-16T03:31:00+00:00",
  last_success_at: "2026-10-16T03:31:00+00:00",
  device_count: 152,
  error: null,
  error_code: null,
};

function device(overrides: Partial<IntuneDevice>): IntuneDevice {
  return {
    id: 1,
    device_name: "LAPTOP-TEST-01",
    serial_number: "TESTSN0001",
    manufacturer: "Lenovo",
    model: "ThinkPad T14",
    operating_system: "Windows",
    user_principal_name: "anna.przykladowa@example.com",
    user: { id: 7, name: "Anna Przykładowa" },
    compliance_state: "compliant",
    last_sync_at: null,
    last_seen_at: null,
    missing_since: null,
    item_id: null,
    resolution: null,
    resolution_note: null,
    resolved_at: null,
    ...overrides,
  };
}

const ROWS: IntuneDiscrepancy[] = [
  {
    key: "device:3",
    kind: "zniknal_z_intune",
    device: device({ id: 3, device_name: "LAPTOP-GONE", missing_since: "2026-10-12T03:30:00+00:00" }),
    item: null,
    holder: null,
  },
  {
    key: "device:1",
    kind: "brak_w_ewidencji",
    device: device({ id: 1 }),
    item: null,
    holder: null,
  },
  {
    key: "device:2",
    kind: "inny_posiadacz",
    device: device({ id: 2, device_name: "LAPTOP-OTHER", serial_number: "TESTSN0002" }),
    item: {
      id: 40,
      inventory_number: "T-221",
      serial_number: "TESTSN0002",
      model_name: "Latitude 5440",
      category: "laptop",
      status: "wydany",
    },
    holder: { kind: "user", id: 9, name: "Ewa Testowa" },
  },
  {
    key: "item:41",
    kind: "brak_w_intune",
    device: null,
    item: {
      id: 41,
      inventory_number: null,
      serial_number: "TESTSN0041",
      model_name: "ProBook 450",
      category: "laptop",
      status: "wydany",
    },
    holder: { kind: "contract", id: 5, name: "Jan Przykładowy" },
  },
];

const RESOLVED = [
  {
    key: "device:8",
    device: device({
      id: 8,
      device_name: "LAPTOP-SKIPPED",
      serial_number: "TESTSN0008",
      resolution: "pominiete" as const,
      resolution_note: "Sprzęt testowy działu IT",
      resolved_at: "2026-10-15T09:00:00+00:00",
    }),
    item: null,
    holder: null,
  },
];

const REPORT: IntuneDiscrepancies = {
  rows: ROWS,
  resolved: RESOLVED,
  counts: {
    zniknal_z_intune: 1,
    brak_w_ewidencji: 1,
    inny_posiadacz: 1,
    brak_w_intune: 1,
    zgodne: 120,
    wyjasnione: 1,
  },
  checked: true,
  devices: 152,
};

const EMPTY: IntuneDiscrepancies = {
  rows: [],
  resolved: [],
  counts: {
    zniknal_z_intune: 0,
    brak_w_ewidencji: 0,
    inny_posiadacz: 0,
    brak_w_intune: 0,
    zgodne: 0,
    wyjasnione: 0,
  },
  checked: false,
  devices: 0,
};

function mockApi({
  status = LIVE,
  report = REPORT,
  reportFails = false,
}: {
  status?: IntuneStatus;
  report?: IntuneDiscrepancies;
  reportFails?: boolean;
} = {}) {
  get.mockImplementation((url: string) => {
    if (url === "/api/equipment/intune/status") return Promise.resolve({ data: status });
    if (url === "/api/equipment/intune/discrepancies") {
      if (reportFails) {
        return Promise.reject({ response: { status: 500, data: { detail: "Błąd" } } });
      }
      return Promise.resolve({ data: report });
    }
    if (url === "/api/equipment/items") {
      return Promise.resolve({
        data: {
          items: [
            {
              id: 77,
              model: { id: 3, category: "laptop", name: "ThinkPad T14", manufacturer: null, price_pln: null, is_active: true },
              category: "laptop",
              inventory_number: "T-300",
              serial_number: "TESTSN0O01",
              imei: null,
              iccid: null,
              phone_number: null,
              access_card_number: null,
              status: "wydany",
              ownership: "nasz",
              purchase_date: null,
              location: null,
              notes: null,
              holder: { kind: "user", id: 7, name: "Anna Przykładowa" },
              issue_protocol: null,
            },
          ],
          total: 1,
        },
      });
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

const onOpenItem = vi.fn();

function renderTab({ isAdmin = false } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <IntuneTab isAdmin={isAdmin} onOpenItem={onOpenItem} />
    </QueryClientProvider>,
  );
}

// Lista Radix (filtr rodzaju) potrzebuje API wskaźnika, którego jsdom nie ma.
beforeAll(() => {
  for (const [name, value] of [
    ["hasPointerCapture", () => false],
    ["setPointerCapture", () => undefined],
    ["releasePointerCapture", () => undefined],
    ["scrollIntoView", () => undefined],
  ] as const) {
    if (!(name in Element.prototype)) {
      Object.defineProperty(Element.prototype, name, { configurable: true, value });
    }
  }
});

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  del.mockReset();
  showToast.mockReset();
  onOpenItem.mockReset();
});

describe("IntuneTab", () => {
  it("explains the switched-off read calmly and shows no manual run", async () => {
    mockApi({ status: { ...LIVE, mode: "off", health: "disabled" }, report: EMPTY });
    renderTab({ isAdmin: true });
    expect(await screen.findByText("Odczyt z Intune: wyłączony")).toBeInTheDocument();
    expect(screen.getByText(/czeka na zgodę administratora Microsoft 365/)).toBeInTheDocument();
    expect(
      await screen.findByText("Lista pojawi się po pierwszym odczycie urządzeń z Intune."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Odczytaj teraz/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Ostatni udany odczyt/)).not.toBeInTheDocument();
  });

  it("lists every kind with the registry side and counts, filtered by kind", async () => {
    mockApi();
    renderTab();
    expect(await screen.findByText(/Ostatni udany odczyt: 16\.10\.2026, 05:31/)).toBeInTheDocument();
    const other = await screen.findByTestId("intune-row-device:2");
    expect(within(other).getByText("Inny posiadacz")).toBeInTheDocument();
    expect(within(other).getByText("Ewa Testowa")).toBeInTheDocument();
    expect(within(other).getByText("Anna Przykładowa")).toBeInTheDocument();
    expect(within(screen.getByTestId("intune-row-device:3")).getByText("od 12.10.2026")).toBeInTheDocument();
    const missing = screen.getByTestId("intune-row-item:41");
    expect(within(missing).getByText("nie ma w Intune")).toBeInTheDocument();
    expect(within(missing).queryByRole("button", { name: "Pomiń" })).not.toBeInTheDocument();
    await userEvent.click(within(missing).getByRole("button", { name: "Otwórz pozycję" }));
    expect(onOpenItem).toHaveBeenCalledWith(41);
    // „Powiąż” tylko przy urządzeniu bez egzemplarza.
    expect(within(screen.getByTestId("intune-row-device:1")).getByRole("button", { name: /Powiąż/ })).toBeInTheDocument();
    expect(within(other).queryByRole("button", { name: /Powiąż/ })).not.toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("combobox", { name: "Rodzaj rozjazdu" }));
    await userEvent.click(await screen.findByRole("option", { name: "Brak w Intune (1)" }));
    await waitFor(() => expect(screen.queryByTestId("intune-row-device:2")).not.toBeInTheDocument());
    expect(screen.getByTestId("intune-row-item:41")).toBeInTheDocument();
  });

  it("shows a failure as an error, not as an empty list", async () => {
    mockApi({ reportFails: true });
    renderTab();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.queryByText(/nie ma nic do wyjaśnienia/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Lista pojawi się/)).not.toBeInTheDocument();
  });

  it("skips a device with a note", async () => {
    mockApi();
    post.mockResolvedValue({ data: device({ id: 1, resolution: "pominiete" }) });
    renderTab();
    const row = await screen.findByTestId("intune-row-device:1");
    await userEvent.click(within(row).getByRole("button", { name: "Pomiń" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("LAPTOP-TEST-01 · S/N TESTSN0001")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByRole("textbox"), "Sprzęt testowy działu IT");
    await userEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/equipment/intune/devices/1/resolve", {
        resolution: "pominiete",
        note: "Sprzęt testowy działu IT",
      }),
    );
    expect(showToast).toHaveBeenCalledWith("Urządzenie pominięte", "success");
  });

  it("lists resolved devices only in their own view and undoes a decision", async () => {
    mockApi();
    del.mockResolvedValue({ data: device({ id: 8 }) });
    renderTab();
    await screen.findByTestId("intune-row-device:1");
    // Urządzenie z decyzją nie jest rozjazdem — nie ma go na liście „Wszystkie rozjazdy”.
    expect(screen.queryByTestId("intune-resolved-device:8")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("combobox", { name: "Rodzaj rozjazdu" }));
    await userEvent.click(await screen.findByRole("option", { name: "Wyjaśnione i pominięte (1)" }));
    const row = await screen.findByTestId("intune-resolved-device:8");
    expect(screen.queryByTestId("intune-row-device:1")).not.toBeInTheDocument();
    expect(within(row).getByText("Pominięte")).toBeInTheDocument();
    expect(within(row).getByText("Sprzęt testowy działu IT")).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Pomiń" })).not.toBeInTheDocument();

    await userEvent.click(within(row).getByRole("button", { name: "Cofnij decyzję" }));
    await waitFor(() =>
      expect(del).toHaveBeenCalledWith("/api/equipment/intune/devices/8/resolution"),
    );
    expect(showToast).toHaveBeenCalledWith("Decyzja cofnięta", "success");
  });

  it("shows an empty resolved view calmly", async () => {
    mockApi({ report: { ...REPORT, resolved: [], counts: { ...REPORT.counts, wyjasnione: 0 } } });
    renderTab();
    await userEvent.click(await screen.findByRole("combobox", { name: "Rodzaj rozjazdu" }));
    await userEvent.click(await screen.findByRole("option", { name: "Wyjaśnione i pominięte (0)" }));
    expect(await screen.findByText("Żadne urządzenie nie ma jeszcze decyzji recepcji.")).toBeInTheDocument();
  });

  it("tells why an undo was refused", async () => {
    mockApi();
    del.mockRejectedValue({
      response: { status: 409, data: { detail: "To urządzenie nie ma decyzji do cofnięcia." } },
    });
    renderTab();
    await userEvent.click(await screen.findByRole("combobox", { name: "Rodzaj rozjazdu" }));
    await userEvent.click(await screen.findByRole("option", { name: "Wyjaśnione i pominięte (1)" }));
    const row = await screen.findByTestId("intune-resolved-device:8");
    await userEvent.click(within(row).getByRole("button", { name: "Cofnij decyzję" }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("To urządzenie nie ma decyzji do cofnięcia.", "error"),
    );
  });

  it("shows the server reason when linking an item already taken", async () => {
    mockApi();
    post.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: "Ten egzemplarz jest już powiązany z innym urządzeniem z Intune." },
      },
    });
    renderTab();
    const row = await screen.findByTestId("intune-row-device:1");
    await userEvent.click(within(row).getByRole("button", { name: /Powiąż/ }));
    const dialog = await screen.findByRole("dialog");
    // Podpowiedź: szukanie zaczyna się od osoby z Intune.
    expect(within(dialog).getByRole("textbox", { name: "Szukaj pozycji w rejestrze" })).toHaveValue(
      "Anna Przykładowa",
    );
    await userEvent.click(await within(dialog).findByRole("button", { name: "Powiąż" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/equipment/intune/devices/1/link", { item_id: 77 }),
    );
    expect(showToast).toHaveBeenCalledWith(
      "Ten egzemplarz jest już powiązany z innym urządzeniem z Intune.",
      "error",
    );
  });

  it("shows the last failure in words and hides the run from non-admins", async () => {
    mockApi({ status: { ...LIVE, error: "Microsoft odmówił odczytu urządzeń (403).", health: "degraded" } });
    renderTab();
    expect(await screen.findByText(/się nie udał\. Microsoft odmówił odczytu/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Odczytaj teraz/ })).not.toBeInTheDocument();
  });

  it("runs the read for the admin", async () => {
    mockApi();
    post.mockResolvedValue({ data: { status: "ok", devices: 152, error_text: null } });
    renderTab({ isAdmin: true });
    await userEvent.click(await screen.findByRole("button", { name: /Odczytaj teraz/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/equipment/intune/sync"));
    expect(showToast).toHaveBeenCalledWith("Odczytano urządzenia z Intune: 152", "success");
  });
});

describe("Intune format helpers", () => {
  it("picks a calm tone per mode and health", () => {
    expect(intuneStatusTone({ mode: "off", health: "disabled" })).toBe("neutral");
    expect(intuneStatusTone({ mode: "simulate", health: "degraded" })).toBe("info");
    expect(intuneStatusTone({ mode: "live", health: "healthy" })).toBe("success");
    expect(intuneStatusTone({ mode: "live", health: "degraded" })).toBe("warning");
  });

  it("labels the device by name and S/N, falling back when either is missing", () => {
    expect(deviceLabel(ROWS[2])).toBe("LAPTOP-OTHER · S/N TESTSN0002");
    expect(deviceLabel({ ...ROWS[1], device: device({ device_name: null, serial_number: null }) })).toBe(
      "Urządzenie bez nazwy",
    );
    expect(deviceLabel(ROWS[3])).toBe("");
  });
});
