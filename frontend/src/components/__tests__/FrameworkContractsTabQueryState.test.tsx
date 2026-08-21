/**
 * Zakładka „Umowy" (MSA): 403 NIE może twierdzić, że klient nie ma umowy ramowej.
 *
 * Odczyt stoi za `can_view_legal_documents` (admin/HoR/DL/TAC + przypisanie do
 * klienta), a sam profil klienta otwiera każdy `OperationalUser`. Recruiter,
 * sourcer, finance i nieprzypisany DL/TAC dostawali więc „Brak umów ramowych.
 * Dodaj pierwszą MSA aby móc tworzyć zamówienia." — w body leasingu to zdanie
 * jest różnicą między „możemy obsadzić tego klienta" a „nie możemy", a przycisk
 * zapraszał do zduplikowania MSA, która już istnieje (POST i tak zwracał 403).
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

interface TestUser {
  role: string;
  roles?: string[];
}

const authState: { user: TestUser | null } = { user: null };

const mocks = vi.hoisted(() => ({ list: vi.fn() }));

vi.mock("@/store/auth", async () => {
  const actual =
    await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  return {
    ...actual,
    useAuthStore: (selector: (s: { user: TestUser | null }) => unknown) =>
      selector(authState),
  };
});

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn() }),
}));

vi.mock("@/lib/authenticated-files", () => ({
  downloadAuthenticatedFile: vi.fn(),
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listFrameworkContracts: (...a: unknown[]) => mocks.list(...a),
    deleteFrameworkContract: vi.fn(),
    listAmendments: vi.fn(),
    deleteAmendment: vi.fn(),
  },
}));

import { FrameworkContractsTab } from "@/components/FrameworkContractsTab";

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
  authState.user = { role: "admin" };
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
    authState.user = { role: "tac" };
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
