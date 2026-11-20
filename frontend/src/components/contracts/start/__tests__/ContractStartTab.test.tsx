/**
 * „Start i sprzęt” jako checklista (wariant A, 20.11.2026): nagłówek liczy
 * postęp z listy, która obowiązuje (lista wejścia albo stara lista przy
 * wyłączonym module), „Formalności” mówią o umowie w dokumentach i dokumentach
 * do startu, a sekcje list, sprzętu i panelu zostają w swoich komponentach.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const client = { get: (...a: unknown[]) => mocks.get(...a), post: vi.fn(), patch: vi.fn(), delete: vi.fn() };
  return { ...(await importOriginal<typeof import("@/lib/api")>()), default: client, api: client };
});

// Sekcje z własnymi testami — tu liczy się układ i nagłówek.
vi.mock("@/components/hr/onboarding/ContractEntryTab", () => ({
  ContractEntryTab: (props: { readOnly?: boolean }) => <p>lista startowa{props.readOnly ? " (odczyt)" : ""}</p>,
}));
vi.mock("@/components/contracts/ContractEquipmentTab", () => ({
  ContractEquipmentTab: (props: { documentNames?: string[] }) => (
    <section aria-label="Sprzęt">sprzęt · pliki: {(props.documentNames ?? []).join(", ")}</section>
  ),
}));
vi.mock("@/components/hr/onboarding/ConsultantPanelCard", () => ({
  ConsultantPanelCard: () => <section aria-label="Panel konsultanta">panel</section>,
}));

import { ContractStartTab } from "../ContractStartTab";
import type { ContractDocument } from "@/lib/contract-document-folders";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });
}

const AGREEMENT: ContractDocument = {
  id: 1,
  contract_id: 7,
  filename: "Umowa B2B — Jan Testowy.pdf",
  doc_type: "contract",
  content_type: "application/pdf",
  size_bytes: 10,
  expiry_date: null,
  uploaded_by: null,
  uploaded_by_email: null,
  created_at: "2026-11-02T10:00:00Z",
};

const ONBOARDING = [
  { id: 1, label: "BHP — szkolenie", status: "done", created_at: "2026-11-01T10:00:00Z", order: 0 },
  { id: 2, label: "Konto w Slacku klienta", status: "pending", created_at: "2026-11-01T10:00:00Z", order: 1 },
  { id: 3, label: "Email firmowy", status: "na", created_at: "2026-11-01T10:00:00Z", order: 2 },
  { id: 4, label: "Dostęp do repozytorium", status: "pending", created_at: "2026-11-01T10:00:00Z", order: 3 },
];

function serve({ entry, pair }: { entry: "off" | "notFound" | "case"; pair?: unknown }) {
  mocks.get.mockImplementation((url: string) => {
    if (url === "/api/hr/lifecycle/contracts/7/entry") {
      if (entry === "notFound") return Promise.reject(httpError(404));
      return Promise.resolve({
        data: {
          contract_id: 7,
          module_on: entry === "case",
          start_date: "2026-11-15",
          case:
            entry === "case"
              ? {
                  id: 3,
                  status: "active",
                  started_at: "2026-11-05T09:00:00Z",
                  tasks: [{ status: "done" }, { status: "skipped" }, { status: "open" }],
                }
              : null,
          composition: {},
          missing_reason: entry === "case" ? null : "module_off",
          can_create: false,
          can_add_task: false,
          legacy_items: 0,
        },
      });
    }
    if (url === "/api/contracts/7/onboarding") return Promise.resolve({ data: ONBOARDING });
    if (url === "/api/start-documents/pair") return Promise.resolve({ data: pair ?? null });
    if (url === "/api/start-documents/clients/3") return Promise.resolve({ data: { items: [], not_required: null } });
    return Promise.resolve({ data: null });
  });
}

function renderTab(props: Partial<React.ComponentProps<typeof ContractStartTab>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onOpenDocuments = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <ContractStartTab
        contractId={7}
        clientId={3}
        candidateId={9}
        jobId={11}
        startDate="2026-11-15"
        readOnly={false}
        documents={[AGREEMENT]}
        canViewDocuments
        onOpenDocuments={onOpenDocuments}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onOpenDocuments };
}

beforeEach(() => {
  mocks.get.mockReset();
});

describe("ContractStartTab", () => {
  it("stara lista przy wyłączonym module: postęp bez „nie dotyczy”, data założenia, pasek", async () => {
    serve({ entry: "off" });
    renderTab();
    await screen.findByText(/1 z 3 kroków/);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Start u klienta · 1 z 3 kroków");
    expect(screen.getByText(/Współpraca od 15\.11\.2026 · lista założona 01\.11\.2026/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Postęp listy startowej" })).toHaveAttribute("aria-valuenow", "33");
    // Sekcje w kolejności z makiety.
    const sections = screen.getAllByRole("region").map((region) => region.getAttribute("aria-label"));
    expect(sections).toEqual(["Formalności", "Lista startowa", "Sprzęt", "Panel konsultanta"]);
  });

  it("404 modułu to też stara lista; lista wejścia liczy zrobione i pominięte", async () => {
    serve({ entry: "notFound" });
    renderTab();
    expect(await screen.findByRole("heading", { name: /1 z 3 kroków/ })).toBeInTheDocument();

    serve({ entry: "case" });
    renderTab();
    expect(await screen.findByRole("heading", { name: /2 z 3 kroków/ })).toBeInTheDocument();
    expect(screen.getByText("ze ścieżki wejścia")).toBeInTheDocument();
  });

  it("formalności: umowa w dokumentach z linkiem do zakładki, braki dokumentów do startu z nazwy", async () => {
    const user = userEvent.setup();
    serve({
      entry: "off",
      pair: {
        done: 1,
        total: 2,
        deadline: "2099-12-01",
        items: [
          { name: "NDA", state: "delivered" },
          { name: "Wyciąg z KRK", state: "missing" },
        ],
      },
    });
    const { onOpenDocuments } = renderTab();
    const formalities = await screen.findByRole("region", { name: "Formalności" });
    expect(within(formalities).getByText("Umowa w dokumentach")).toBeInTheDocument();
    expect(formalities).toHaveTextContent("„Umowa B2B — Jan Testowy.pdf” · dodano 02.11.2026");
    expect(await within(formalities).findByText(/Brakuje: Wyciąg z KRK · 1 z 2 gotowe · termin 01\.12\.2099/)).toBeInTheDocument();
    await user.click(within(formalities).getAllByRole("button", { name: "Dokumenty" })[0]);
    expect(onOpenDocuments).toHaveBeenCalled();
  });

  it("bez umowy w dokumentach to brak; bez wglądu w dokumenty wiersza nie ma", async () => {
    serve({ entry: "off" });
    renderTab({ documents: [] });
    expect(await screen.findByText("Brak umowy w dokumentach")).toBeInTheDocument();
    expect(screen.getByLabelText("brak")).toBeInTheDocument();

    serve({ entry: "off" });
    renderTab({ documents: undefined, canViewDocuments: false });
    const sections = await screen.findAllByRole("region", { name: "Formalności" });
    expect(within(sections[1]).queryByText(/Umowa w dokumentach|Brak umowy/)).toBeNull();
  });

  it("kontrakt bez rekrutacji: dokumenty do startu nie mają pary — zdanie zamiast zgadywania", async () => {
    serve({ entry: "off" });
    renderTab({ jobId: null });
    expect(await screen.findByText(/Kontrakt bez rekrutacji/)).toBeInTheDocument();
    expect(mocks.get.mock.calls.some(([url]) => url === "/api/start-documents/pair")).toBe(false);
    expect(screen.getByRole("link", { name: "Wejście u klienta" })).toHaveAttribute("href", "/clients/3?tab=wejscie");
  });

  it("przekazuje odczyt do sekcji i nazwy plików do podpowiedzi sprzętu", async () => {
    serve({ entry: "off" });
    renderTab({ readOnly: true });
    expect(await screen.findByText("lista startowa (odczyt)")).toBeInTheDocument();
    expect(screen.getByText(/pliki: Umowa B2B — Jan Testowy\.pdf/)).toBeInTheDocument();
  });
});
