import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ContractDocumentsTab } from "@/components/ContractDocumentsTab";

vi.mock("@/lib/api", () => ({
  contractsApi: {
    documents: vi.fn().mockResolvedValue({
      data: [
        {
          id: 9,
          contract_id: 3,
          filename: "umowa.pdf",
          doc_type: "contract",
          content_type: "application/pdf",
          size_bytes: 128,
          expiry_date: null,
          uploaded_by: 1,
          uploaded_by_email: "admin@example.com",
          created_at: "2026-09-01T10:00:00Z",
        },
      ],
    }),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
    documentFolders: vi.fn().mockResolvedValue({
      data: {
        folders: [],
        orders_folder_name: "Zamówienia",
        current_contract_number: null,
        suggestions: [],
      },
    }),
  },
  // Etykiety historii kontraktu (`personFromEmail` z `lib/contract-history`).
  CONTRACT_FIELD_LABELS: {},
  CONTRACT_TERMINATION_REASONS: [],
}));
vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listContractOrderDocuments: vi.fn().mockResolvedValue({ data: { documents: [] } }),
  },
}));
vi.mock("@/components/OrderDocumentsSection", () => ({
  OrderDocumentsSection: () => null,
}));

function renderTab(readOnly: boolean) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ContractDocumentsTab contractId={3} readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

describe("ContractDocumentsTab section access", () => {
  it("keeps downloads but hides upload and delete in read-only mode", async () => {
    renderTab(true);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("umowa.pdf")).toBeInTheDocument();
    expect(screen.getByTitle("Pobierz")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz umowę: umowa.pdf" })).toBeInTheDocument();
    expect(screen.queryByText("Dodaj plik")).not.toBeInTheDocument();
    expect(screen.queryByText("Nowy folder")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Więcej akcji/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Usuń plik…")).not.toBeInTheDocument();
  });

  it("with write access deletion sits in the file menu, not as a bin on top", async () => {
    renderTab(false);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("umowa.pdf")).toBeInTheDocument();
    expect(screen.getByText("Dodaj plik")).toBeInTheDocument();
    expect(screen.queryByTitle("Usuń")).not.toBeInTheDocument();
    fireEvent.pointerDown(screen.getByRole("button", { name: "Więcej akcji: umowa.pdf" }), {
      button: 0,
      ctrlKey: false,
    });
    expect(await screen.findByRole("menuitem", { name: "Usuń plik…" })).toBeInTheDocument();
  });

  it("shows the uploader's name, never the e-mail address", async () => {
    renderTab(true);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Admin")).toBeInTheDocument();
    expect(screen.queryByText(/admin@example\.com/)).not.toBeInTheDocument();
  });
});
