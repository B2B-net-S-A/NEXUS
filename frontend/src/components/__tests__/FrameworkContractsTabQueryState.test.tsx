/**
 * Zakładka „Umowy" (MSA): 403 NIE może twierdzić, że klient nie ma umowy ramowej.
 *
 * Odczyt stoi za `can_view_legal_documents`, a sam profil klienta otwiera
 * szerszy zestaw ról operacyjnych. Recruiter, sourcer i TAC bez dostępu
 * dostawali więc „Brak umów ramowych.
 * Dodaj pierwszą MSA aby móc tworzyć zamówienia." — w body leasingu to zdanie
 * jest różnicą między „możemy obsadzić tego klienta" a „nie możemy", a przycisk
 * zapraszał do zduplikowania MSA, która już istnieje (POST i tak zwracał 403).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

interface TestUser {
  role: string;
  roles?: string[];
  effective_action_access?: Record<string, string>;
}

interface AuthState {
  user: TestUser | null;
  realUser: TestUser | null;
}

const authState: AuthState = { user: null, realUser: null };

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  showToast: vi.fn(),
  // Podgląd kwot klienta liczy `store/auth` (zakres Delivery Leada itd.) —
  // tutaj sterujemy samym wynikiem.
  canViewClientFinance: vi.fn(),
}));

vi.mock("@/store/auth", async () => {
  const actual =
    await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  return {
    ...actual,
    useAuthStore: (selector: (s: AuthState) => unknown) => selector(authState),
    canViewClientFinance: (...a: unknown[]) => mocks.canViewClientFinance(...a),
  };
});

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.showToast }),
}));

vi.mock("@/lib/authenticated-files", () => ({
  downloadAuthenticatedFile: vi.fn(),
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listFrameworkContracts: (...a: unknown[]) => mocks.list(...a),
    deleteFrameworkContract: vi.fn(),
    createFrameworkContract: (...a: unknown[]) => mocks.create(...a),
    listAmendments: vi.fn(),
    deleteAmendment: vi.fn(),
  },
}));

import { FrameworkContractsTab } from "@/components/FrameworkContractsTab";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";

const FALSE_CLAIM = /Brak umów ramowych\. Dodaj pierwszą MSA/;
const NEW_BUTTON = /Nowa umowa/;

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <FrameworkContractsTab clientId={3} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.list.mockReset();
  mocks.create.mockReset();
  mocks.showToast.mockReset();
  mocks.canViewClientFinance.mockReset();
  mocks.canViewClientFinance.mockReturnValue(true);
  authState.user = { role: "admin" };
  authState.realUser = null;
});

describe("FrameworkContractsTab", () => {
  it("403 renderuje brak uprawnień zamiast zaproszenia do duplikatu MSA", async () => {
    authState.user = { role: "recruiter" };
    mocks.list.mockRejectedValue(httpError(403));

    renderTab();

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText(FALSE_CLAIM)).not.toBeInTheDocument();
    expect(screen.queryByText(NEW_BUTTON)).not.toBeInTheDocument();
  });

  it("500 renderuje awarię z ponowieniem, nie pusty stan", async () => {
    mocks.list.mockRejectedValue(httpError(500));

    renderTab();

    expect(
      await screen.findByText("Nie udało się pobrać danych"),
    ).toBeInTheDocument();
    expect(screen.queryByText(FALSE_CLAIM)).not.toBeInTheDocument();
  });

  it("rola bez prawa zapisu widzi listę, ale nie dostaje zachęty do dodania MSA", async () => {
    authState.user = { role: "recruiter" };
    mocks.list.mockResolvedValue({ data: { items: [] } });

    renderTab();

    expect(
      await screen.findByText("Brak umów ramowych dla tego klienta."),
    ).toBeInTheDocument();
    expect(screen.queryByText(NEW_BUTTON)).not.toBeInTheDocument();
  });

  it("sukces z zerem umów u admina nadal zachęca do dodania pierwszej MSA", async () => {
    mocks.list.mockResolvedValue({ data: { items: [] } });

    renderTab();

    expect(await screen.findByText(FALSE_CLAIM)).toBeInTheDocument();
    expect(screen.getByText(NEW_BUTTON)).toBeInTheDocument();
  });
});

describe("FrameworkContractsTab — zapis: edycja kontraktów + kwoty tego klienta", () => {
  async function renderEmptyList() {
    mocks.list.mockResolvedValue({ data: { items: [] } });
    renderTab();
    await screen.findByText(/Brak umów ramowych/);
  }

  it.each(["delivery_lead", "finance"])(
    "%s ma edycję kontraktów domyślnie i dodaje umowę ramową",
    async (role) => {
      authState.user = { role };
      await renderEmptyList();

      expect(screen.getByText(NEW_BUTTON)).toBeInTheDocument();
      // Kwoty liczą się per klient — pytanie dotyczy klienta tej zakładki.
      expect(mocks.canViewClientFinance).toHaveBeenCalledWith(authState.user, 3);
    },
  );

  it("rekruter z nadaną edycją kontraktów i podglądem kwot dodaje umowę ramową", async () => {
    authState.user = {
      role: "recruiter",
      effective_action_access: permissionSnapshot(
        "contracts_orders_edit",
        "amounts_view",
      ),
    };
    await renderEmptyList();

    expect(screen.getByText(NEW_BUTTON)).toBeInTheDocument();
  });

  it("Delivery Lead z wyłączoną edycją kontraktów nie dostaje „Nowa umowa”", async () => {
    authState.user = {
      role: "delivery_lead",
      effective_action_access: permissionSnapshot("clients_edit", "amounts_view"),
    };
    await renderEmptyList();

    expect(screen.queryByText(NEW_BUTTON)).not.toBeInTheDocument();
    expect(screen.getByText("Brak umów ramowych dla tego klienta.")).toBeInTheDocument();
  });

  it("edycja kontraktów bez podglądu kwot tego klienta nie wystarcza", async () => {
    // Np. Delivery Lead u klienta spoza przypisania albo osoba z samą edycją
    // kontraktów — umowa ramowa niesie stawki.
    mocks.canViewClientFinance.mockReturnValue(false);
    authState.user = { role: "delivery_lead" };
    await renderEmptyList();

    expect(screen.queryByText(NEW_BUTTON)).not.toBeInTheDocument();
  });

  it("w podglądzie jako inny użytkownik zakładka jest tylko do odczytu", async () => {
    authState.user = { role: "delivery_lead" };
    authState.realUser = { role: "admin" };
    await renderEmptyList();

    expect(screen.queryByText(NEW_BUTTON)).not.toBeInTheDocument();
  });
});

describe("Nowa umowa ramowa — odwrócone daty (runda 10, F12)", () => {
  async function openDialog() {
    mocks.list.mockResolvedValue({ data: { items: [] } });
    const view = renderTab();
    fireEvent.click(await screen.findByText(NEW_BUTTON));
    fireEvent.change(screen.getByPlaceholderText("np. MSA 2026"), {
      target: { value: "MSA test" },
    });
    return view;
  }

  function dateInputs(container: HTMLElement) {
    return container.querySelectorAll<HTMLInputElement>('input[type="date"]');
  }

  it("koniec przed początkiem: komunikat przy polu „Wygasa”, bez żądania", async () => {
    const { container } = await openDialog();
    const [from, to] = Array.from(dateInputs(container));
    fireEvent.change(from, { target: { value: "2026-10-01" } });
    fireEvent.change(to, { target: { value: "2026-09-30" } });
    fireEvent.click(screen.getByRole("button", { name: /Zapisz/ }));

    expect(
      await screen.findByText(/nie może być wcześniejsza niż „Obowiązuje od”/),
    ).toBeInTheDocument();
    expect(to).toHaveAttribute("aria-invalid", "true");
    expect(document.activeElement).toBe(to);
    expect(mocks.create).not.toHaveBeenCalled();
    expect(to).toHaveValue("2026-09-30");
  });

  it("odmowa serwera pokazuje jego polski komunikat, nie kod HTTP", async () => {
    mocks.create.mockRejectedValue(
      Object.assign(new Error("Request failed with status code 422"), {
        response: { status: 422, data: { detail: "Waluta to trzyliterowy kod, np. PLN albo EUR." } },
      }),
    );
    await openDialog();
    fireEvent.click(screen.getByRole("button", { name: /Zapisz/ }));
    await waitFor(() =>
      expect(mocks.showToast).toHaveBeenCalledWith(
        "Waluta to trzyliterowy kod, np. PLN albo EUR.",
        "error",
      ),
    );
    expect(mocks.showToast).not.toHaveBeenCalledWith(
      expect.stringMatching(/status code/),
      "error",
    );
  });
});
