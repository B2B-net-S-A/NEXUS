import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showToast = vi.fn();
const download = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    patch: vi.fn(),
    put: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));
vi.mock("@/lib/authenticated-files", () => ({
  fetchAuthenticatedDownload: (...a: unknown[]) => download(...a),
  downloadBlob: vi.fn(),
}));

import { BookingTab } from "@/components/finance/ledger/BookingTab";
import type { ExportPreview } from "@/lib/api/finance-posting";

const REASON = "Kwoty faktury zmieniły się po dekrecie — Cofnij i przelicz.";

const PREVIEW: ExportPreview = {
  month: "2026-10",
  registers: [
    {
      register: "purchase",
      label: "Zakup",
      entries: [
        {
          id: 1,
          invoice_number: "FV/1/10",
          seller_name: "Dostawca Testowy",
          seller_nip: "1234563218",
          issue_date: "2026-10-03",
          doc_type: "FVZ",
          description: "Usługi IT 10/2026",
          manual: false,
          exportable: true,
          debit_total: "123.00",
          credit_total: "123.00",
          issues: [],
        },
        {
          id: 2,
          invoice_number: "FV/2/10",
          seller_name: "Dostawca Testowy",
          seller_nip: "1234563218",
          issue_date: "2026-10-04",
          doc_type: "FVZ",
          description: "Usługi IT 10/2026",
          manual: false,
          exportable: false,
          debit_total: "123.00",
          credit_total: "123.00",
          issues: [REASON],
        },
      ],
      debit_total: "123.00",
      credit_total: "123.00",
      balanced: true,
    },
  ],
  count: 2,
  blocked: 1,
  skipped: [{ id: 2, invoice_number: "FV/2/10", seller_name: "Dostawca Testowy", issues: [REASON] }],
  can_export: true,
  formats: [{ key: "neutral_xlsx", label: "Arkusz XLSX (format neutralny)", extension: "xlsx" }],
  default_format: "neutral_xlsx",
  batches: [],
};

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BookingTab />
    </QueryClientProvider>,
  );
}

describe("BookingTab", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    showToast.mockReset();
    download.mockReset();
    get.mockResolvedValue({ data: PREVIEW });
  });

  it("faktura z wadą jest na liście pominiętych z powodem, a plik da się pobrać", async () => {
    renderTab();
    const skipped = await screen.findByRole("list", { name: "Pominięte w paczce" });
    expect(skipped).toHaveTextContent("FV/2/10");
    expect(skipped).toHaveTextContent(REASON);
    expect(screen.getByRole("button", { name: "Pobierz plik" })).toBeEnabled();
  });

  it("same faktury z wadą — „Pobierz plik” wyłączone", async () => {
    get.mockResolvedValue({ data: { ...PREVIEW, can_export: false } });
    renderTab();
    await screen.findByRole("list", { name: "Pominięte w paczce" });
    expect(screen.getByRole("button", { name: "Pobierz plik" })).toBeDisabled();
  });

  it("po paczce komunikat mówi, ile faktur pominięto", async () => {
    post.mockResolvedValue({
      data: {
        id: 9,
        number: "2026-10/1",
        file_name: "symfonia-2026-10-1.xlsx",
        skipped: PREVIEW.skipped,
      },
    });
    download.mockResolvedValue({ blob: new Blob(["x"]), filename: "symfonia-2026-10-1.xlsx" });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Pobierz plik" }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        "Paczka 2026-10/1 gotowa — pobieram plik. Pominięto 1 fakturę z wadą dekretu.",
        "success",
      ),
    );
  });
});
