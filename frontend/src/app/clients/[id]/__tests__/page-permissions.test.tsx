/**
 * Profil klienta: zakładka „Umowy” i zapis materiałów idą za uprawnieniami
 * konta, nie za rolą.
 *
 * Do 02.10.2026 strona miała dwie lokalne listy ról (`admin/delivery_lead/
 * finance` dla umów, `admin/delivery_lead` + zapis Delivery dla materiałów).
 * Teraz pyta wspólne helpery: `canViewClientFinance(user, clientId)` (kwoty
 * TEGO klienta — „Stawki i kwoty: podgląd”, Delivery Lead u klientów
 * z przypisania) i `canManageClientDelivery(user)` („Klienci: dodawanie
 * i edycja”). Reguły helperów mają własne testy — tu sprawdzamy, że strona
 * słucha ich wyniku i pyta o właściwego klienta.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  search: "",
  replace: vi.fn(),
  apiGet: vi.fn(),
  canViewClientFinance: vi.fn(),
  canManageClientDelivery: vi.fn(),
  canEditClientLegalDocuments: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "7" }),
  useRouter: () => ({ replace: mocks.replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(mocks.search),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  api: { get: (...args: unknown[]) => mocks.apiGet(...args) },
  clientTeamApi: {
    get: () => Promise.resolve({ data: { delivery_leads: [] } }),
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("@/hooks/useCapability", () => ({ useCapability: () => false }));
vi.mock("@/hooks/useCanonicalClientRedirect", () => ({
  useCanonicalClientRedirect: () => {},
}));

vi.mock("@/store/auth", async () => {
  const actual =
    await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  return {
    ...actual,
    canViewClientFinance: (...args: unknown[]) =>
      mocks.canViewClientFinance(...args),
  };
});
vi.mock("@/components/client-profile/permissions", () => ({
  canManageClientDelivery: (...args: unknown[]) =>
    mocks.canManageClientDelivery(...args),
  canEditClientLegalDocuments: (...args: unknown[]) =>
    mocks.canEditClientLegalDocuments(...args),
}));

// Treść zakładek nie jest przedmiotem tego testu — liczy się, co strona im
// przekazuje i które w ogóle renderuje.
vi.mock("@/components/AppShell", () => ({ EditClientModal: () => null }));
vi.mock("@/components/ConfirmDialog", () => ({ DeleteButton: () => null }));
vi.mock("@/components/RateCardsTab", () => ({
  RateCardsTab: () => <p>cennik klienta</p>,
}));
vi.mock("../MaterialsTab", () => ({
  MaterialsTab: (props: {
    readOnly?: boolean;
    showContractTerms?: boolean;
    contractTermsReadOnly?: boolean;
  }) => (
    <p
      data-testid="materials"
      data-read-only={String(props.readOnly)}
      data-contract-terms={String(props.showContractTerms)}
      data-contract-terms-read-only={String(props.contractTermsReadOnly)}
    >
      materiały
    </p>
  ),
}));
vi.mock("../OwnersTab", () => ({ OwnersTab: () => null }));
vi.mock("../ProfileTab", () => ({ ProfileTab: () => <p>profil klienta</p> }));
vi.mock("../ProjectsTab", () => ({ ProjectsTab: () => null }));
vi.mock("@/components/FrameworkContractsTab", () => ({
  FrameworkContractsTab: () => <p>umowy ramowe</p>,
}));
vi.mock("@/components/client-profile/orders/MultiConsultantOrdersTab", () => ({
  MultiConsultantOrdersTab: () => null,
}));
vi.mock("@/components/client-profile/orders/ClientMdImportsTab", () => ({
  ClientMdImportsTab: () => null,
}));
vi.mock("@/components/AnalyticsTab", () => ({ AnalyticsTab: () => null }));
vi.mock("@/components/KeyRelationshipDialog", () => ({
  KeyRelationshipDialog: () => null,
}));
vi.mock("@/components/client-playbook/ClientPlaybookTab", () => ({
  ClientPlaybookTab: () => null,
}));
vi.mock("@/components/client-profile/DeleteClientDialog", () => ({
  DeleteClientDialog: () => null,
}));
vi.mock("@/components/client-profile/ClientConflictsSection", () => ({
  ClientConflictsSection: () => null,
}));

import ClientDetailPage from "../page";
import { useAuthStore } from "@/store/auth";

const CLIENT = {
  id: 7,
  name: "Klient Testowy",
  status: "active",
  website: null,
  nda_signed: false,
  notes: null,
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ClientDetailPage />
    </QueryClientProvider>,
  );
}

// Sekcje profilu (19.11.2026: pięć sekcji): grupy i podzakładki to przyciski
// z `aria-current`. Umowy stoją w „Umowie i pieniądzach”.
const contractsGroup = () => screen.queryByRole("button", { name: "Umowa i pieniądze" });
// Od 19.11.2026 „Umowa” to jedna strona: umowy, stawki i raporty.
const contractsSubTab = () => screen.queryByRole("button", { name: "Umowa" });

beforeEach(() => {
  vi.clearAllMocks();
  mocks.search = "";
  // Karty zakładki Profil są rozwinięte i od razu pytają o statystyki
  // współpracy, a nagłówek o liczby klienta — to nie jest przedmiot tego
  // testu, więc poza samym klientem serwer odmawia (sekcje wtedy milczą).
  mocks.apiGet.mockImplementation((url: string) =>
    url === "/api/clients/7"
      ? Promise.resolve({ data: CLIENT })
      : Promise.reject({ response: { status: 403 } }),
  );
  mocks.canViewClientFinance.mockReturnValue(true);
  mocks.canManageClientDelivery.mockReturnValue(true);
  mocks.canEditClientLegalDocuments.mockReturnValue(true);
  useAuthStore.setState({
    // Rola spoza dawnej listy admin/Delivery Lead/Finanse — o widoczności
    // decyduje odpowiedź helpera, nie rola.
    user: { id: 3, role: "recruiter", roles: ["recruiter"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("profil klienta — umowy za podglądem kwot klienta", () => {
  it("pokazuje umowy temu, kto widzi kwoty TEGO klienta — pyta o jego id", async () => {
    renderPage();

    expect(await screen.findByText("profil klienta")).toBeInTheDocument();
    expect(contractsGroup()).toBeInTheDocument();
    expect(mocks.canViewClientFinance).toHaveBeenCalledWith(
      expect.objectContaining({ id: 3 }),
      7,
    );

    fireEvent.click(contractsGroup() as HTMLElement);
    expect(await screen.findByText("umowy ramowe")).toBeInTheDocument();
    expect(contractsSubTab()).toHaveAttribute("aria-current", "page");
  });

  it("bez kwot tego klienta „Umowa i pieniądze” nie ma umów ani stawek", async () => {
    mocks.canViewClientFinance.mockReturnValue(false);
    renderPage();

    expect(await screen.findByText("profil klienta")).toBeInTheDocument();
    fireEvent.click(contractsGroup() as HTMLElement);
    expect(screen.queryByText("umowy ramowe")).not.toBeInTheDocument();
    expect(contractsSubTab()).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stawki i cennik" })).not.toBeInTheDocument();
  });

  it("link `?tab=umowy-ramowe` bez podglądu kwot ląduje na Profilu, nie na pustej zakładce", async () => {
    mocks.search = "tab=umowy-ramowe";
    mocks.canViewClientFinance.mockReturnValue(false);
    renderPage();

    expect(await screen.findByText("profil klienta")).toBeInTheDocument();
    expect(screen.queryByText("umowy ramowe")).not.toBeInTheDocument();
  });

  it("link `?tab=umowy-ramowe` z podglądem kwot otwiera umowy", async () => {
    mocks.search = "tab=umowy-ramowe";
    renderPage();

    expect(await screen.findByText("umowy ramowe")).toBeInTheDocument();
  });

  it("„Umowa” to jedna strona: link `?tab=raporty` otwiera ją ze stawkami i raportami (19.11.2026)", async () => {
    // jsdom nie przewija — wystarczy, że wywołanie nie wywraca strony.
    Element.prototype.scrollIntoView = vi.fn();
    mocks.search = "tab=raporty";
    renderPage();

    expect(await screen.findByText("umowy ramowe")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Stawki i cennik" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Raporty dla klienta" })).toBeInTheDocument();
    expect(contractsSubTab()).toHaveAttribute("aria-current", "page");
    // Stawki i raporty nie są już osobnymi podzakładkami.
    expect(screen.queryByRole("button", { name: "Stawki i cennik" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Raporty dla klienta" })).not.toBeInTheDocument();
  });
});

describe("profil klienta — materiały za edycją klientów", () => {
  // Od 18.11.2026 materiały to podzakładka grupy „Rekrutacje”.
  async function openMaterials() {
    renderPage();
    await screen.findByText("profil klienta");
    fireEvent.click(screen.getByRole("button", { name: "Rekrutacje" }));
    fireEvent.click(await screen.findByRole("button", { name: "Materiały dla rekruterów" }));
    return waitFor(() => screen.getByTestId("materials"));
  }

  it.each([
    [true, true, "false", "true"],
    [false, false, "true", "false"],
  ])(
    "edycja klientów: %s, podgląd kwot: %s → readOnly=%s, warunki umowy=%s",
    async (canEdit, canViewLegal, readOnly, contractTerms) => {
      mocks.canManageClientDelivery.mockReturnValue(canEdit);
      mocks.canViewClientFinance.mockReturnValue(canViewLegal);

      const materials = await openMaterials();

      expect(materials).toHaveAttribute("data-read-only", readOnly);
      expect(materials).toHaveAttribute("data-contract-terms", contractTerms);
    },
  );

  // Warunki kontraktowe zapisuje `PUT …/contract-terms` = „Kontrakty
  // i zamówienia” + podgląd kwot u tego klienta, a nie edycja klientów:
  // Finanse je edytują, osoba z samą edycją klientów — nie.
  it.each([
    [false, true, "true", "false"],
    [true, false, "false", "true"],
  ])(
    "edycja klientów: %s, dokumenty prawne: %s → materiały readOnly=%s, warunki readOnly=%s",
    async (canEdit, canEditLegal, readOnly, termsReadOnly) => {
      mocks.canManageClientDelivery.mockReturnValue(canEdit);
      mocks.canEditClientLegalDocuments.mockReturnValue(canEditLegal);

      const materials = await openMaterials();

      expect(materials).toHaveAttribute("data-read-only", readOnly);
      expect(materials).toHaveAttribute(
        "data-contract-terms-read-only",
        termsReadOnly,
      );
      expect(mocks.canEditClientLegalDocuments).toHaveBeenCalledWith(
        expect.objectContaining({ id: 3 }),
        7,
      );
    },
  );
});
