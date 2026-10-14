import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const byCandidate = vi.fn();
const contractDocuments = vi.fn();
const apiGet = vi.fn();

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => apiGet(...args) },
  extractErrorMsg: () => "",
  contractsApi: {
    byCandidate: (...args: unknown[]) => byCandidate(...args),
    documents: (...args: unknown[]) => contractDocuments(...args),
  },
}));
vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listCandidateOrderDocuments: vi.fn(async () => ({ data: { documents: [] } })),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showToast: vi.fn(), showSuccess: vi.fn() }),
}));
vi.mock("@/components/v2/files/FilePreviewModal", async () => {
  const actual = await vi.importActual<
    typeof import("@/components/v2/files/FilePreviewModal")
  >("@/components/v2/files/FilePreviewModal");
  return { ...actual, FilePreviewModal: () => null };
});
// Edytor szkicu (TipTap) i karta Autenti — zaślepki mówią tylko, czy się renderują.
vi.mock("next/dynamic", () => ({
  default: () =>
    function DraftEditorStub() {
      return <div data-testid="draft-editor" />;
    },
}));
vi.mock("@/components/v2/contract/AutentiEnvelopeCard", () => ({
  AutentiEnvelopeCard: () => <div data-testid="autenti-card" />,
}));

import { FilesContractsTab } from "../FilesContractsTab";
import { useAuthStore } from "@/store/auth";

/**
 * D7 (13.10.2026): umowy z `GET /api/contracts` tylko z `delivery_view`.
 * Bez niego — neutralny blok „Umowy prowadzi Delivery” z umowami z `/history`
 * i Delivery Leadem; nigdy „Brak umowy z nami”. Załączniki, Autenti i szkic
 * za `contractAccess()` (kwoty / edycja kontraktów).
 */

const CANDIDATE = { id: 42, phone: "+48 600 000 000", legal_name: null, nip: null };

// `/history` wysyła przy umowie też stawki — widok nie może ich pokazać.
const HISTORY_CONTRACTS = [
  {
    contract_id: 11,
    client_name: "Bank Polski",
    start_date: "2025-03-01",
    end_date: null,
    status: "active",
    rate_candidate: 18350,
    rate_client: 24990,
    currency: "PLN",
  },
  {
    contract_id: 7,
    client_name: "Ubezpieczenia SA",
    start_date: "2023-01-01",
    end_date: "2024-06-30",
    status: "ended",
  },
];

const MARKER = {
  phase: "working",
  source: "contract",
  clients: [
    { client_name: "Bank Polski", phase: "working", delivery_lead_name: "Anna Nowak" },
    { client_name: "Telekom", phase: "working", delivery_lead_name: "Piotr Zieliński" },
    { client_name: "Bank Polski 2", phase: "working", delivery_lead_name: " Anna Nowak " },
  ],
};

const ACTIVE_CONTRACT = {
  id: 501,
  client_id: 9,
  client_name: "Bank Polski",
  status: "active",
  start_date: "2025-03-01",
  end_date: null,
  rate_candidate: 160,
  rate_client: 200,
  margin: 40,
  rate_unit: "hourly",
  currency: "PLN",
  work_mode: "zdalnie",
};

const DRAFT_CONTRACT = {
  id: 502,
  client_id: 9,
  client_name: "Bank Polski",
  status: "draft",
  start_date: "2026-11-01",
};

function setUser(user: Record<string, unknown>) {
  useAuthStore.setState({ user: { id: 5, ...user }, realUser: null } as never);
}

function renderTab(props: Partial<Parameters<typeof FilesContractsTab>[0]> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = (ui: ReactNode) => (
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
  return render(
    wrap(
      <FilesContractsTab
        candidate={CANDIDATE}
        candidateName="Jan Kowalski"
        readOnly={false}
        focus="files"
        recruitments={[]}
        {...props}
      />,
    ),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiGet.mockResolvedValue({ data: [] });
  byCandidate.mockResolvedValue({ data: { items: [ACTIVE_CONTRACT] } });
  contractDocuments.mockResolvedValue({
    data: [{ id: 1, filename: "umowa-podpisana.pdf", doc_type: "contract" }],
  });
});

describe("Dokumenty — umowy bez podglądu Delivery (D7)", () => {
  it("rekruter: bez zapytania o umowy, neutralny blok z umowami z historii i Delivery Leadami", async () => {
    setUser({ role: "recruiter" });
    renderTab({ historyContracts: HISTORY_CONTRACTS, employmentMarker: MARKER });

    const section = screen.getByRole("region", { name: "Umowy" });
    expect(within(section).getByText("Umowy prowadzi Delivery")).toBeInTheDocument();
    expect(within(section).getByText("Anna Nowak, Piotr Zieliński")).toBeInTheDocument();
    const list = within(section).getByRole("list", { name: "Umowy kandydata" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Bank Polski");
    expect(rows[0]).toHaveTextContent("Aktywny");
    expect(rows[0]).toHaveTextContent("bezterminowo");
    expect(rows[1]).toHaveTextContent("Ubezpieczenia SA");
    expect(rows[1]).toHaveTextContent("Zakończony");
    // Bez kwot i bez zdania, którego front nie może wiedzieć.
    expect(section).not.toHaveTextContent(/PLN|18350|24990|Stawka|Marża/);
    expect(screen.queryByText(/Brak umowy/)).toBeNull();

    // Lista plików ładuje się normalnie — tylko umowy nie lecą do serwera.
    await screen.findByRole("heading", { name: "Pliki" });
    expect(byCandidate).not.toHaveBeenCalled();
    expect(contractDocuments).not.toHaveBeenCalled();
  });

  it("bez umów w historii i bez znacznika: sam neutralny blok, nigdy „Brak umowy”", async () => {
    setUser({ role: "recruiter" });
    renderTab();

    expect(screen.getByText("Umowy prowadzi Delivery")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Umowy kandydata" })).toBeNull();
    expect(screen.queryByText(/Delivery Lead:/)).toBeNull();
    expect(screen.queryByText(/Brak umowy/)).toBeNull();
    await screen.findByRole("heading", { name: "Pliki" });
    expect(byCandidate).not.toHaveBeenCalled();
  });

  it("wyjątek osoby: rola z Delivery, ale bez `delivery_view` w profilu → też bez zapytania", async () => {
    setUser({
      role: "delivery_lead",
      effective_action_access: { delivery_view: "none", amounts_view: "none" },
    });
    renderTab({ historyContracts: HISTORY_CONTRACTS });

    expect(screen.getByText("Umowy prowadzi Delivery")).toBeInTheDocument();
    await screen.findByRole("heading", { name: "Pliki" });
    expect(byCandidate).not.toHaveBeenCalled();
  });
});

describe("Dokumenty — umowy z podglądem Delivery (D7)", () => {
  it("TCM (podgląd Delivery, bez kwot): umowa widoczna, bez załączników, Autenti i stawek", async () => {
    setUser({ role: "talent_community_manager" });
    renderTab({ historyContracts: HISTORY_CONTRACTS });

    expect(await screen.findByText("Zarządzaj kontraktem →")).toBeInTheDocument();
    expect(byCandidate).toHaveBeenCalledWith(42);
    expect(screen.queryByText("Umowy prowadzi Delivery")).toBeNull();
    expect(screen.getByText("Tryb pracy")).toBeInTheDocument();
    expect(screen.queryByText("Stawka kandydata")).toBeNull();
    expect(screen.queryByText("Dokumenty")).toBeNull();
    expect(screen.queryByTestId("autenti-card")).toBeNull();
    expect(contractDocuments).not.toHaveBeenCalled();
  });

  it("Finanse (kwoty + edycja kontraktów): załączniki, Autenti i edytor szkicu", async () => {
    setUser({ role: "finance" });
    byCandidate.mockResolvedValue({ data: { items: [ACTIVE_CONTRACT, DRAFT_CONTRACT] } });
    renderTab();

    expect(await screen.findByText("umowa-podpisana.pdf")).toBeInTheDocument();
    expect(contractDocuments).toHaveBeenCalledWith(501);
    expect(screen.getByText("Stawka kandydata")).toBeInTheDocument();
    expect(screen.getByTestId("autenti-card")).toBeInTheDocument();
    expect(screen.getByTestId("draft-editor")).toBeInTheDocument();
  });

  it("kwoty bez edycji kontraktów: załączniki tak, Autenti i edytor szkicu nie", async () => {
    setUser({
      role: "finance",
      effective_action_access: {
        delivery_view: "manage",
        amounts_view: "manage",
        contracts_orders_edit: "none",
      },
    });
    byCandidate.mockResolvedValue({ data: { items: [ACTIVE_CONTRACT, DRAFT_CONTRACT] } });
    renderTab();

    expect(await screen.findByText("umowa-podpisana.pdf")).toBeInTheDocument();
    expect(screen.queryByTestId("autenti-card")).toBeNull();
    expect(screen.queryByTestId("draft-editor")).toBeNull();
    expect(screen.getByText("Szkic umowy")).toBeInTheDocument();
  });

  it("403 na załącznikach chowa sekcję zamiast udawać „Brak załączników”", async () => {
    setUser({ role: "finance" });
    contractDocuments.mockRejectedValue({ response: { status: 403 } });
    renderTab();

    expect(await screen.findByText("Zarządzaj kontraktem →")).toBeInTheDocument();
    await waitFor(() => expect(contractDocuments).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText("Wczytywanie…")).toBeNull());
    expect(screen.queryByText(/Brak załączników/)).toBeNull();
    expect(screen.queryByText(/Nie udało się wczytać listy załączników/)).toBeNull();
  });

  it("awaria pobrania umów to błąd z „Ponów”, nie pusta lista", async () => {
    setUser({ role: "finance" });
    byCandidate.mockRejectedValue(new Error("500"));
    renderTab();

    expect(await screen.findByText("Nie udało się pobrać umów")).toBeInTheDocument();
    expect(screen.queryByText(/Brak umowy/)).toBeNull();
  });
});

describe("Dokumenty — układ", () => {
  it("kolejność: Umowy → Pliki → Dane do umowy (JDG) na dole", async () => {
    setUser({ role: "recruiter" });
    renderTab();

    const contracts = screen.getByRole("region", { name: "Umowy" });
    const files = await screen.findByRole("heading", { name: "Pliki" });
    const jdg = screen.getByRole("button", { name: /Dane do umowy \(JDG \/ firma\)/ });
    expect(contracts.compareDocumentPosition(files) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(files.compareDocumentPosition(jdg) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(jdg).toHaveAttribute("aria-expanded", "false");
    // CV i umiejętności mają własną zakładkę „CV”.
    expect(screen.queryByText("CV i umiejętności")).toBeNull();
  });

  it("tylko do odczytu: bez danych do umowy", async () => {
    setUser({ role: "recruiter" });
    renderTab({ readOnly: true });

    await screen.findByRole("heading", { name: "Pliki" });
    expect(screen.queryByRole("button", { name: /Dane do umowy/ })).toBeNull();
  });

  it("plik z kodem rekrutacji osoby trafia do „CV dla klientów”", async () => {
    setUser({ role: "recruiter" });
    apiGet.mockImplementation(async (url: string) =>
      url === "/api/candidates/42/documents"
        ? {
            data: [
              {
                id: 1,
                filename: "cv.pdf",
                content_type: "application/pdf",
                size_bytes: 10,
                document_kind: "cv",
                is_primary: true,
                uploaded_at: null,
                created_at: "2026-09-01T10:00:00Z",
                external_source: null,
              },
              {
                id: 2,
                filename: "42700_Jan_Kowalski.docx",
                content_type: "application/pdf",
                size_bytes: 10,
                document_kind: "other",
                is_primary: false,
                uploaded_at: null,
                created_at: "2026-09-02T10:00:00Z",
                external_source: "traffit",
              },
            ],
          }
        : { data: [] },
    );
    renderTab({
      recruitments: [{ job_title: "Analityk (42700)" }, { job_title: "Java Developer" }],
    });

    const client = await screen.findByRole("region", { name: /CV dla klientów/ });
    expect(within(client).getByText("42700_Jan_Kowalski.docx")).toBeInTheDocument();
  });

  it("`?documents=contracts` przewija do umów", async () => {
    setUser({ role: "recruiter" });
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    renderTab({ focus: "contracts" });

    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    expect(scrollIntoView.mock.contexts[0]).toBe(
      screen.getByRole("region", { name: "Umowy" }),
    );
  });
});
