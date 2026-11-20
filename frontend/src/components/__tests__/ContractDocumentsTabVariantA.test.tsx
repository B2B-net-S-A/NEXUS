/**
 * Wariant A zakładki „Dokumenty” (decyzja Artura 19.11.2026): „Obowiązuje
 * teraz”, wyszukiwarka, długie grupy z „Pokaż starsze”, kolumny „Dodano”
 * i „Ważny do” tylko wtedy, gdy coś w nich jest, import z SharePointa opisany
 * raz nad tabelą, stan kopii w SharePoincie w wierszu, awaria ≠ pustka.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContractDocumentsTab } from "@/components/ContractDocumentsTab";
import type { ContractDocument } from "@/lib/contract-document-folders";

const api = vi.hoisted(() => ({
  documents: vi.fn(),
  documentFolders: vi.fn(),
  orderFiles: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  contractsApi: {
    documents: (...a: unknown[]) => api.documents(...a),
    documentFolders: (...a: unknown[]) => api.documentFolders(...a),
    moveDocuments: vi.fn(),
    createDocumentFolder: vi.fn(),
    uploadDocument: vi.fn(),
    deleteDocument: vi.fn(),
    renameDocumentFolder: vi.fn(),
    renameOrdersFolder: vi.fn(),
    deleteDocumentFolder: vi.fn(),
  },
  CONTRACT_FIELD_LABELS: {},
  CONTRACT_TERMINATION_REASONS: [],
}));
vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: { listContractOrderDocuments: (...a: unknown[]) => api.orderFiles(...a) },
}));

function doc(id: number, filename: string, doc_type: string, extra: Partial<ContractDocument> = {}): ContractDocument {
  return {
    id,
    contract_id: 3,
    filename,
    doc_type,
    content_type: "application/pdf",
    size_bytes: 200_000 + id,
    expiry_date: null,
    uploaded_by: 1,
    uploaded_by_email: "anna.przykladowa@example.com",
    created_at: "2026-10-01T10:00:00Z",
    folder_id: null,
    ...extra,
  };
}

const imported = (id: number, filename: string, doc_type = "other") =>
  doc(id, filename, doc_type, {
    source: "sharepoint_import",
    uploaded_by_email: "jan.testowy@example.com",
    created_at: "2026-09-29T16:50:00Z",
    sharepoint_item_id: `sp-${id}`,
    sharepoint_push_status: "done",
  });

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

function card(label: RegExp): HTMLElement {
  return screen.getByRole("heading", { level: 3, name: label }).closest("section") as HTMLElement;
}

/** Nagłówki kolumn z `thead` — nagłówki grup (`th scope="colgroup"`) też są „columnheader”. */
const columnHeaders = (table: HTMLElement) =>
  within(table.querySelector("thead") as HTMLElement)
    .getAllByRole("columnheader")
    .map((th) => th.textContent?.trim());

beforeEach(() => {
  vi.clearAllMocks();
  api.documentFolders.mockResolvedValue({
    data: { folders: [], orders_folder_name: "Zamówienia", current_contract_number: "340-2019", suggestions: [] },
  });
  api.orderFiles.mockResolvedValue({ data: { documents: [] } });
});

describe("ContractDocumentsTab — wariant A", () => {
  it("shows what is in force now: contract, last annex and newest order with the date from the name", async () => {
    api.documents.mockResolvedValue({
      data: [
        imported(1, "umowa o współpracę.pdf"),
        imported(2, "Aneks stawka 31.10.2022.pdf", "annex"),
        imported(3, "aneks B2B nr 340_2019_01.05.2024_podpis.pdf", "annex"),
        imported(4, "Zamówienie nr 16 do 30.06.2024.pdf"),
        doc(5, "0087020757.pdf", "order", { created_at: "2026-11-02T10:45:00Z" }),
      ],
    });
    renderTab();
    await screen.findByRole("table");

    const contract = card(/^Umowa/);
    expect(within(contract).getByText("nr 340-2019")).toBeInTheDocument();
    expect(within(contract).getByText("umowa o współpracę.pdf")).toBeInTheDocument();
    expect(within(contract).getByText("bez daty w nazwie · import 29.09.2026")).toBeInTheDocument();

    const annex = card(/^Ostatni aneks/);
    expect(within(annex).getByText("aneks B2B nr 340_2019_01.05.2024_podpis.pdf")).toBeInTheDocument();
    expect(within(annex).getByText("z 01.05.2024")).toBeInTheDocument();

    const order = card(/^Najnowsze zamówienie/);
    expect(within(order).getByText("0087020757.pdf")).toBeInTheDocument();
    expect(within(order).getByText("dodano 02.11.2026 · Anna Przykladowa")).toBeInTheDocument();
    expect(within(order).getByRole("button", { name: "Pobierz najnowsze zamówienie: 0087020757.pdf" })).toBeInTheDocument();
  });

  it("says what is missing when a card has no file", async () => {
    api.documents.mockResolvedValue({ data: [doc(1, "Polisa OC.pdf", "oc_policy")] });
    renderTab();
    await screen.findByRole("table");
    expect(within(card(/^Umowa/)).getByText("Brak pliku umowy")).toBeInTheDocument();
    expect(within(card(/^Ostatni aneks/)).getByText("Aneksy zapisane w kontrakcie są w zakładce Aneksy.")).toBeInTheDocument();
    expect(within(card(/^Najnowsze zamówienie/)).getByText("Dodaj PDF zamówienia klienta.")).toBeInTheDocument();
  });

  it("describes a SharePoint import once and drops the „Dodano” column when every file came with it", async () => {
    api.documents.mockResolvedValue({
      data: [imported(1, "a.pdf"), imported(2, "Aneks 01.02.2021.pdf", "annex"), imported(3, "c.pdf")],
    });
    renderTab();
    const table = await screen.findByRole("table");
    expect(
      screen.getByText("Wszystkie pliki (3) z importu z SharePointa 29.09.2026 · Jan Testowy."),
    ).toBeInTheDocument();
    expect(columnHeaders(table)).toEqual(["Nazwa", "Data dokumentu", "Rozmiar", "Akcje"]);
    expect(screen.queryByText("z SharePointa")).not.toBeInTheDocument();
  });

  it("keeps „Dodano” for the rest and shows „Ważny do” only when a file has an expiry date", async () => {
    api.documents.mockResolvedValue({
      data: [
        imported(1, "a.pdf"),
        imported(2, "b.pdf"),
        imported(3, "c.pdf"),
        doc(4, "Polisa OC 2026.pdf", "oc_policy", { expiry_date: "2020-01-31" }),
      ],
    });
    renderTab();
    const table = await screen.findByRole("table");
    expect(screen.getByText(/3 z 4 plików z importu z SharePointa 29\.09\.2026 · Jan Testowy — w kolumnie „Dodano” są tylko pozostałe\./)).toBeInTheDocument();
    expect(columnHeaders(table)).toEqual(["Nazwa", "Data dokumentu", "Dodano", "Ważny do", "Rozmiar", "Akcje"]);
    // Termin miniony albo bliski — ostrzeżenie kolorem jak dotąd.
    expect(within(table).getByText("31.01.2020")).toHaveClass("text-warning");
    expect(within(table).getByText("Anna Przykladowa")).toBeInTheDocument();
  });

  it("shows the state of the copy NEXUS sent to SharePoint in the row", async () => {
    api.documents.mockResolvedValue({
      data: [
        doc(1, "Aneks skan.pdf", "annex", {
          sharepoint_item_id: "sp-1",
          sharepoint_push_status: "pending",
          sharepoint_push_error: "Folder osoby jest wspólny dla dwóch rekordów.",
        }),
        doc(2, "Umowa.pdf", "contract", { sharepoint_push_status: "failed", sharepoint_push_error: "Brak folderu." }),
        doc(3, "Wypowiedzenie.pdf", "termination_notice", { sharepoint_item_id: "sp-3", sharepoint_push_status: "done" }),
      ],
    });
    renderTab();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("w SharePoincie poprzednia wersja")).toHaveAttribute(
      "title",
      "Folder osoby jest wspólny dla dwóch rekordów.",
    );
    expect(within(table).getByText("nie wysłano do SharePointa")).toHaveAttribute("title", "Brak folderu.");
    // Rodzaj, którego nazwa grupy nie mówi („Wypowiedzenie” w Umowach), i kopia wysłana przez NEXUS.
    expect(within(table).getByText("Wypowiedzenie.pdf").closest("tr")).toHaveTextContent(
      "Wypowiedzenie · w SharePoincie",
    );
  });

  it("folds a long group to the five newest files with „Pokaż starsze”", async () => {
    api.documents.mockResolvedValue({
      data: Array.from({ length: 9 }, (_, i) =>
        doc(i + 1, `Zamówienie nr ${i + 1} do 30.06.20${10 + i}.pdf`, "order"),
      ),
    });
    renderTab();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Zamówienie nr 9 do 30.06.2018.pdf")).toBeInTheDocument();
    expect(within(table).queryByText("Zamówienie nr 1 do 30.06.2010.pdf")).not.toBeInTheDocument();
    fireEvent.click(within(table).getByRole("button", { name: /Pokaż starsze \(4\)/ }));
    expect(within(table).getByText("Zamówienie nr 1 do 30.06.2010.pdf")).toBeInTheDocument();
  });

  it("searches by file name across groups and says when nothing matches", async () => {
    api.documents.mockResolvedValue({
      data: [
        doc(1, "Umowa B2B 340-2019.pdf", "contract"),
        doc(2, "Aneks zmiana stawki 08.06.2021.pdf", "annex"),
        doc(3, "Zamówienie nr 9 do 31.12.2020.pdf", "order"),
      ],
    });
    renderTab();
    const table = await screen.findByRole("table");
    const search = screen.getByRole("searchbox", { name: "Szukaj w dokumentach" });

    fireEvent.change(search, { target: { value: "ZMIANA" } });
    expect(within(table).getByText("Aneks zmiana stawki 08.06.2021.pdf")).toBeInTheDocument();
    expect(within(table).queryByText("Umowa B2B 340-2019.pdf")).not.toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: /grupę Umowy/ })).not.toBeInTheDocument();
    expect(within(table).getByText("1 z 1")).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "faktura" } });
    expect(screen.getByText("Żaden plik nie pasuje do „faktura”.")).toBeInTheDocument();
  });

  it("collapses a type group from its header", async () => {
    api.documents.mockResolvedValue({ data: [doc(1, "Umowa B2B.pdf", "contract")] });
    renderTab();
    const table = await screen.findByRole("table");
    fireEvent.click(within(table).getByRole("button", { name: "Zwiń grupę Umowy" }));
    expect(within(table).queryByText("Umowa B2B.pdf")).not.toBeInTheDocument();
    expect(within(table).getByRole("button", { name: "Rozwiń grupę Umowy" })).toHaveAttribute("aria-expanded", "false");
  });

  it("flags a probable duplicate", async () => {
    api.documents.mockResolvedValue({
      data: [
        doc(1, "0087020757.pdf", "order", { size_bytes: 46909 }),
        doc(2, "PO0087020757.PDF", "order", { size_bytes: 46909 }),
      ],
    });
    renderTab();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("możliwy duplikat „PO0087020757.PDF”")).toBeInTheDocument();
  });

  it("an empty contract shows one sentence, not three empty cards", async () => {
    api.documents.mockResolvedValue({ data: [] });
    renderTab();
    expect(await screen.findByText(/Brak załączonych dokumentów\./)).toBeInTheDocument();
    expect(screen.queryByText("Obowiązuje teraz")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("a failed list is an error with retry, never an empty list", async () => {
    api.documents.mockRejectedValue(new Error("boom"));
    renderTab();
    expect(await screen.findByText("Nie udało się wczytać dokumentów.")).toBeInTheDocument();
    expect(screen.queryByText(/Brak załączonych dokumentów/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Spróbuj ponownie|Ponów/ })).toBeInTheDocument();
  });

  it("a 403 on order PDFs is silent, any other failure is shown", async () => {
    api.documents.mockResolvedValue({ data: [doc(1, "Umowa.pdf", "contract")] });
    api.orderFiles.mockRejectedValue({ response: { status: 403 } });
    const first = renderTab();
    await screen.findByRole("table");
    expect(screen.queryByText(/Nie udało się wczytać plików z zakładki Zamówienia/)).not.toBeInTheDocument();
    first.unmount();

    api.orderFiles.mockRejectedValue({ response: { status: 500 } });
    renderTab();
    expect(await screen.findByText(/Nie udało się wczytać plików z zakładki Zamówienia/)).toBeInTheDocument();
  });
});
