import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

    expect(await screen.findByText("umowa.pdf")).toBeInTheDocument();
    expect(screen.getByTitle("Pobierz")).toBeInTheDocument();
    expect(screen.queryByText("Dodaj plik")).not.toBeInTheDocument();
    expect(screen.queryByText("Nowy folder")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Usuń")).not.toBeInTheDocument();
  });
});
