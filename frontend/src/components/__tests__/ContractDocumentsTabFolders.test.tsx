/**
 * 0494: foldery w zakładce Dokumenty kontraktu — „Aktualna umowa” na górze,
 * foldery pod spodem, pasek po zaznaczeniu, automatyczny folder „Zamówienia”
 * (bez „Usuń”, z plikami z zakładki Zamówienia) i podpowiedź „Poprzednia umowa”.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContractDocumentsTab } from "@/components/ContractDocumentsTab";

const api = vi.hoisted(() => ({
  documents: vi.fn(),
  documentFolders: vi.fn(),
  moveDocuments: vi.fn(),
  createDocumentFolder: vi.fn(),
  orderFiles: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  contractsApi: {
    documents: (...a: unknown[]) => api.documents(...a),
    documentFolders: (...a: unknown[]) => api.documentFolders(...a),
    moveDocuments: (...a: unknown[]) => api.moveDocuments(...a),
    createDocumentFolder: (...a: unknown[]) => api.createDocumentFolder(...a),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
    renameDocumentFolder: vi.fn(),
    renameOrdersFolder: vi.fn(),
    deleteDocumentFolder: vi.fn(),
  },
}));
vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: { listContractOrderDocuments: (...a: unknown[]) => api.orderFiles(...a) },
}));

function doc(id: number, filename: string, doc_type: string, folder_id: number | null = null) {
  return {
    id,
    contract_id: 3,
    filename,
    doc_type,
    content_type: "application/pdf",
    size_bytes: 1024 * id,
    expiry_date: null,
    uploaded_by: 1,
    uploaded_by_email: null,
    created_at: `2026-10-${String(id).padStart(2, "0")}T10:00:00Z`,
    folder_id,
  };
}

function renderTab(readOnly = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ContractDocumentsTab contractId={3} readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.documents.mockResolvedValue({
    data: [
      doc(1, "Umowa B2B nr 518-2026.pdf", "contract"),
      doc(2, "Umowa nr 361-2019.pdf", "contract"),
      doc(3, "Aneks do umowy 361-2019.pdf", "annex"),
      doc(4, "Zamówienie wrzesień.pdf", "order"),
      doc(5, "Stara polisa.pdf", "oc_policy", 20),
    ],
  });
  api.documentFolders.mockResolvedValue({
    data: {
      folders: [{ id: 20, name: "Archiwum", created_at: "2026-10-20T10:00:00Z" }],
      orders_folder_name: "Zamówienia",
      current_contract_number: "518-2026",
      suggestions: [
        {
          number: "361-2019",
          folder_name: "Poprzednia umowa – nr 361-2019",
          folder_id: null,
          document_ids: [2, 3],
        },
      ],
    },
  });
  api.orderFiles.mockResolvedValue({
    data: {
      documents: [
        {
          order_id: 77,
          client_id: 9,
          contract_id: 3,
          title: "ZAM-2026-0930",
          filename: "zam.pdf",
          content_type: "application/pdf",
          size_bytes: 2048,
          created_at: "2026-09-30T10:00:00Z",
          order_status: "active",
          uploaded_by_email: null,
          uploaded_at: null,
        },
      ],
    },
  });
  api.moveDocuments.mockResolvedValue({ data: { moved: 1 } });
  api.createDocumentFolder.mockResolvedValue({
    data: { folder: { id: 21, name: "Poprzednia umowa – nr 361-2019", created_at: "x" }, moved: 2 },
  });
});

describe("ContractDocumentsTab — foldery", () => {
  it("lists loose files on top and folders below, collapsed", async () => {
    renderTab();
    expect(await screen.findByText("Umowa B2B nr 518-2026.pdf")).toBeInTheDocument();
    expect(screen.getByText("Aktualna umowa")).toBeInTheDocument();
    expect(screen.getByText("Foldery")).toBeInTheDocument();
    // Zamówienie i plik z folderu nie leżą w „Aktualnej umowie”, dopóki folder zwinięty.
    expect(screen.queryByText("Zamówienie wrzesień.pdf")).not.toBeInTheDocument();
    expect(screen.queryByText("Stara polisa.pdf")).not.toBeInTheDocument();

    const orders = screen.getByRole("button", { name: "Rozwiń folder Zamówienia" });
    expect(screen.getByText("automatyczny")).toBeInTheDocument();
    // „Zamówień” nie da się usunąć, zwykły folder — tak.
    expect(screen.queryByRole("button", { name: "Usuń folder Zamówienia" })).toBeNull();
    expect(screen.getByRole("button", { name: "Usuń folder Archiwum" })).toBeInTheDocument();

    fireEvent.click(orders);
    expect(screen.getByText("Zamówienie wrzesień.pdf")).toBeInTheDocument();
    // PDF z zakładki Zamówienia: bez checkboxa i bez „Usuń”.
    expect(screen.getByText("ZAM-2026-0930")).toBeInTheDocument();
    expect(screen.getByText("z zakładki Zamówienia")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Usuń ZAM-2026-0930" })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Zaznacz Zamówienie wrzesień.pdf" })).toBeNull();
  });

  it("shows the selection bar and moves the selected files", async () => {
    renderTab();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Zaznacz Umowa nr 361-2019.pdf" }));
    const bar = screen.getByRole("region", { name: "Akcje dla zaznaczonych plików" });
    expect(within(bar).getByText("Zaznaczono 1 plik")).toBeInTheDocument();

    fireEvent.change(within(bar).getByLabelText("Przenieś do"), { target: { value: "20" } });
    fireEvent.click(within(bar).getByRole("button", { name: "Przenieś" }));
    await waitFor(() =>
      expect(api.moveDocuments).toHaveBeenCalledWith(3, { document_ids: [2], folder_id: 20 }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Akcje dla zaznaczonych plików" })).toBeNull(),
    );
  });

  it("applies the previous-contract suggestion as a new folder", async () => {
    renderTab();
    expect(
      await screen.findByText(/2 pliki wyglądają na poprzednią umowę nr 361-2019/),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Przenieś do folderu „Poprzednia umowa – nr 361-2019”",
      }),
    );
    await waitFor(() =>
      expect(api.createDocumentFolder).toHaveBeenCalledWith(3, {
        name: "Poprzednia umowa – nr 361-2019",
        document_ids: [2, 3],
      }),
    );
  });

  it("read-only mode has no checkboxes, folder actions or suggestion buttons", async () => {
    renderTab(true);
    expect(await screen.findByText("Umowa B2B nr 518-2026.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByText("Nowy folder")).toBeNull();
    expect(screen.queryByRole("button", { name: /Usuń folder/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Przenieś do folderu/ })).toBeNull();
  });

  it("a folder failure does not hide the files", async () => {
    api.documentFolders.mockRejectedValue(new Error("boom"));
    renderTab();
    expect(await screen.findByText("Stara polisa.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Nie udało się wczytać folderów/)).toBeInTheDocument();
  });
});
