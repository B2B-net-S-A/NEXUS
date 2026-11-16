import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({ __esModule: true, api: { get: (...a: unknown[]) => get(...a) } }));
const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast }) }));
const openFile = vi.fn();
const downloadFile = vi.fn();
vi.mock("@/lib/authenticated-files", () => ({
  openAuthenticatedFile: (...a: unknown[]) => openFile(...a),
  downloadAuthenticatedFile: (...a: unknown[]) => downloadFile(...a),
}));
vi.mock("@/lib/use-debounced-value", () => ({ useDebouncedValue: <T,>(v: T) => v }));

import { Ebi24ArchiveTab } from "@/components/finance/ledger/Ebi24ArchiveTab";
import type { ArchiveDocument } from "@/lib/api/finance-archive";

function doc(id: number, patch: Partial<ArchiveDocument> = {}): ArchiveDocument {
  return {
    id,
    source_id: `src${id}`,
    kind: "cost",
    kind_label: "koszt",
    schema_name: "COST_INVOICE",
    invoice_number: `FV/${id}/2025`,
    issue_date: "2025-03-14",
    due_date: null,
    partner_name: "Dostawca Testowy",
    partner_id: "3333333333",
    currency: "PLN",
    net: "56.91",
    gross: "70.00",
    gross_pln: "70.00",
    paid: true,
    ksef_number: null,
    folder: null,
    file_type: "pdf",
    file_name: "faktura.pdf",
    file_size: 1000,
    ...patch,
  };
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const SUMMARY = { total: 3, years: [{ year: "2025", sale: 1, cost: 1, other: 1 }], last_import_at: null };

beforeEach(() => {
  get.mockReset();
  openFile.mockReset();
  downloadFile.mockReset();
});

function mockApi(documents: ArchiveDocument[]) {
  get.mockImplementation((url: string) =>
    Promise.resolve({ data: url.endsWith("/summary") ? SUMMARY : { total: documents.length, documents } }),
  );
}

describe("Ebi24ArchiveTab", () => {
  it("opens a PDF, previews an eBI24 invoice and only downloads foreign HTML", async () => {
    const user = userEvent.setup();
    mockApi([
      doc(1),
      doc(2, { kind: "sale", kind_label: "sprzedaż", file_type: "ebi", ksef_number: "123-20250314-AB-01" }),
      doc(3, { file_type: "html" }),
    ]);
    wrap(<Ebi24ArchiveTab />);
    expect(await screen.findByText("FV/1/2025")).toBeInTheDocument();
    expect(screen.getByText("KSeF 123-20250314-AB-01")).toBeInTheDocument();
    expect(screen.getByText(/3 dokumenty z eBI24/)).toBeInTheDocument();

    await user.click(within(screen.getByTestId("archive-1")).getByRole("button"));
    expect(openFile).toHaveBeenCalledWith("/api/finance/archive-ebi24/1/file", "application/pdf", "ebi24-src1.pdf");
    await user.click(within(screen.getByTestId("archive-2")).getByRole("button"));
    expect(openFile).toHaveBeenLastCalledWith("/api/finance/archive-ebi24/2/file", "text/html", "ebi24-src2.html");
    await user.click(within(screen.getByTestId("archive-3")).getByRole("button"));
    expect(downloadFile).toHaveBeenCalledWith("/api/finance/archive-ebi24/3/file", "ebi24-src3.html");
    expect(openFile).toHaveBeenCalledTimes(2);
  });

  it("sends search and filters to the API", async () => {
    const user = userEvent.setup();
    mockApi([doc(1)]);
    wrap(<Ebi24ArchiveTab />);
    await screen.findByText("FV/1/2025");
    await user.selectOptions(screen.getByLabelText("Rodzaj dokumentu"), "sale");
    await user.selectOptions(screen.getByLabelText("Rok"), "2025");
    await user.type(screen.getByLabelText("Szukaj w archiwum"), "Dostawca");
    await waitFor(() =>
      expect(get).toHaveBeenLastCalledWith("/api/finance/archive-ebi24", {
        params: { q: "Dostawca", kind: "sale", year: 2025, limit: 50, offset: 0 },
      }),
    );
  });

  it("does not pretend an outage is an empty archive", async () => {
    get.mockImplementation((url: string) =>
      url.endsWith("/summary") ? Promise.resolve({ data: SUMMARY }) : Promise.reject(new Error("500")),
    );
    wrap(<Ebi24ArchiveTab />);
    await waitFor(() => expect(screen.queryByText("Wczytywanie dokumentów…")).not.toBeInTheDocument());
    expect(screen.queryByText(/nie jest jeszcze wgrane/)).not.toBeInTheDocument();
  });
});
