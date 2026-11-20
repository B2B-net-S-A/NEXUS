/**
 * 0494 w wariancie A (19.11.2026): pliki poza folderami w grupach po rodzaju,
 * foldery pod spodem (zwinięte), pasek po zaznaczeniu, automatyczna grupa
 * zamówień (bez „Usuń”, z plikami z zakładki Zamówienia), podpowiedź
 * „Poprzednia umowa”, przeniesienie i usunięcie z menu „⋯” przy pliku.
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
  deleteDocument: vi.fn(),
  deleteDocumentFolder: vi.fn(),
  renameDocumentFolder: vi.fn(),
  renameOrdersFolder: vi.fn(),
  orderFiles: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  contractsApi: {
    documents: (...a: unknown[]) => api.documents(...a),
    documentFolders: (...a: unknown[]) => api.documentFolders(...a),
    moveDocuments: (...a: unknown[]) => api.moveDocuments(...a),
    createDocumentFolder: (...a: unknown[]) => api.createDocumentFolder(...a),
    uploadDocument: vi.fn(),
    deleteDocument: (...a: unknown[]) => api.deleteDocument(...a),
    renameDocumentFolder: (...a: unknown[]) => api.renameDocumentFolder(...a),
    renameOrdersFolder: (...a: unknown[]) => api.renameOrdersFolder(...a),
    deleteDocumentFolder: (...a: unknown[]) => api.deleteDocumentFolder(...a),
  },
  // Etykiety historii kontraktu (`personFromEmail` z `lib/contract-history`).
  CONTRACT_FIELD_LABELS: {},
  CONTRACT_TERMINATION_REASONS: [],
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

/** Radix otwiera menu na `pointerdown` lewym przyciskiem. */
function openMenu(trigger: HTMLElement) {
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
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
  api.deleteDocument.mockResolvedValue({ data: {} });
  api.deleteDocumentFolder.mockResolvedValue({ data: { released: 1 } });
  api.renameDocumentFolder.mockResolvedValue({ data: { id: 20, name: "Stare dokumenty", created_at: "x" } });
  api.renameOrdersFolder.mockResolvedValue({ data: { orders_folder_name: "Zamówienia banku" } });
});

describe("ContractDocumentsTab — foldery", () => {
  it("groups loose files by type, keeps orders in their group and folders below, collapsed", async () => {
    renderTab();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Umowa B2B nr 518-2026.pdf")).toBeInTheDocument();
    for (const group of ["Umowy", "Aneksy", "Zamówienia klienta"]) {
      expect(within(table).getByRole("button", { name: `Zwiń grupę ${group}` })).toBeInTheDocument();
    }
    // Zamówienie (typ i PDF z zakładki Zamówienia) leży w grupie zamówień — bez pola wyboru.
    expect(within(table).getByText("Zamówienie wrzesień.pdf")).toBeInTheDocument();
    expect(within(table).getByText("zam.pdf")).toBeInTheDocument();
    expect(
      within(table).getByText("z zakładki Zamówienia · zamówienie „ZAM-2026-0930” · aktywne"),
    ).toBeInTheDocument();
    expect(within(table).getByText(/automatyczny folder/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Zaznacz Zamówienie wrzesień.pdf" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Więcej akcji: zam.pdf" })).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Zaznacz Umowa nr 361-2019.pdf" })).toBeInTheDocument();

    // Folder to archiwum: zwinięty, plik widać po rozwinięciu.
    expect(screen.queryByText("Stara polisa.pdf")).not.toBeInTheDocument();
    expect(within(table).getByText(/archiwum · pliki nie zapalają alarmu wygasania · 5 KB · założony 20\.10\.2026/)).toBeInTheDocument();
    fireEvent.click(within(table).getByRole("button", { name: "Rozwiń folder Archiwum" }));
    expect(screen.getByText("Stara polisa.pdf")).toBeInTheDocument();
  });

  it("deletes a folder only after ConfirmV2, never the orders group", async () => {
    renderTab();
    const table = await screen.findByRole("table");
    openMenu(within(table).getByRole("button", { name: "Akcje grupy Zamówienia klienta" }));
    expect(await screen.findByRole("menuitem", { name: "Zmień nazwę" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Usuń folder…" })).toBeNull();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });

    openMenu(within(table).getByRole("button", { name: "Akcje folderu Archiwum" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń folder…" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/1 plik zostaje i wraca do „Aktualnej umowy” — to pliki poza folderami/)).toBeInTheDocument();
    expect(api.deleteDocumentFolder).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Usuń folder" }));
    await waitFor(() => expect(api.deleteDocumentFolder).toHaveBeenCalledWith(3, 20));
  });

  it("renames a folder in place and the orders group through its own route", async () => {
    renderTab();
    const table = await screen.findByRole("table");
    openMenu(within(table).getByRole("button", { name: "Akcje folderu Archiwum" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Zmień nazwę" }));
    const input = await screen.findByLabelText("Nowa nazwa folderu");
    fireEvent.change(input, { target: { value: "Stare dokumenty" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(api.renameDocumentFolder).toHaveBeenCalledWith(3, 20, "Stare dokumenty"));

    openMenu(within(table).getByRole("button", { name: "Akcje grupy Zamówienia klienta" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Zmień nazwę" }));
    const ordersInput = await screen.findByLabelText("Nowa nazwa folderu");
    expect(ordersInput).toHaveValue("Zamówienia klienta");
    fireEvent.change(ordersInput, { target: { value: "Zamówienia banku" } });
    fireEvent.submit(ordersInput.closest("form")!);
    await waitFor(() => expect(api.renameOrdersFolder).toHaveBeenCalledWith(3, "Zamówienia banku"));
  });

  it("shows the selection bar and moves the selected files without a native select", async () => {
    renderTab();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Zaznacz Umowa nr 361-2019.pdf" }));
    const bar = screen.getByRole("region", { name: "Akcje dla zaznaczonych plików" });
    expect(within(bar).getByText("Zaznaczono 1 plik")).toBeInTheDocument();
    expect(within(bar).getByRole("button", { name: "Nowy folder z zaznaczonych" })).toBeInTheDocument();
    expect(bar.querySelector("select")).toBeNull();

    openMenu(within(bar).getByRole("button", { name: "Przenieś do" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Archiwum" }));
    await waitFor(() =>
      expect(api.moveDocuments).toHaveBeenCalledWith(3, { document_ids: [2], folder_id: 20 }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Akcje dla zaznaczonych plików" })).toBeNull(),
    );
    // Folder, do którego trafiły pliki, rozwija się sam.
    expect(screen.getByRole("button", { name: "Zwiń folder Archiwum" })).toBeInTheDocument();
  });

  it("moves one file from its „⋯” menu and deletes it after ConfirmV2", async () => {
    renderTab();
    const table = await screen.findByRole("table");
    openMenu(within(table).getByRole("button", { name: "Więcej akcji: Umowa B2B nr 518-2026.pdf" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Przenieś do folderu" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Archiwum" }));
    await waitFor(() =>
      expect(api.moveDocuments).toHaveBeenCalledWith(3, { document_ids: [1], folder_id: 20 }),
    );

    openMenu(within(table).getByRole("button", { name: "Więcej akcji: Aneks do umowy 361-2019.pdf" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń plik…" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Usunąć plik „Aneks do umowy 361-2019.pdf”?")).toBeInTheDocument();
    expect(api.deleteDocument).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Usuń plik" }));
    await waitFor(() => expect(api.deleteDocument).toHaveBeenCalledWith(3, 3));
  });

  it("an order file cannot be moved — the menu says why", async () => {
    renderTab();
    const table = await screen.findByRole("table");
    openMenu(within(table).getByRole("button", { name: "Więcej akcji: Zamówienie wrzesień.pdf" }));
    const item = await screen.findByRole("menuitem", { name: "Zamówienie zostaje w grupie zamówień" });
    expect(item).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("menuitem", { name: "Przenieś do folderu" })).toBeNull();
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

  it("„Zaznacz te pliki” selects the suggested files", async () => {
    renderTab();
    fireEvent.click(await screen.findByRole("button", { name: "Zaznacz te pliki" }));
    const bar = screen.getByRole("region", { name: "Akcje dla zaznaczonych plików" });
    expect(within(bar).getByText("Zaznaczono 2 pliki")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Zaznacz Umowa nr 361-2019.pdf" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Zaznacz Aneks do umowy 361-2019.pdf" })).toBeChecked();
  });

  it("read-only mode has no checkboxes, file or folder menus and no suggestion buttons", async () => {
    renderTab(true);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Umowa B2B nr 518-2026.pdf")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByText("Nowy folder")).toBeNull();
    expect(screen.queryByRole("button", { name: /Akcje folderu|Akcje grupy/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Więcej akcji/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Przenieś do folderu/ })).toBeNull();
    expect(within(table).getAllByTitle("Pobierz").length).toBeGreaterThan(0);
  });

  it("a folder failure does not hide the files", async () => {
    api.documentFolders.mockRejectedValue(new Error("boom"));
    renderTab();
    expect(await screen.findByText("Stara polisa.pdf")).toBeInTheDocument();
    expect(screen.getByText(/Nie udało się wczytać folderów/)).toBeInTheDocument();
  });
});
