import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: vi.fn(),
    patch: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { PaymentsTab } from "@/components/finance/ledger/PaymentsTab";
import type { PaymentPlan, PlanItem } from "@/lib/api/finance-payments";

function item(id: number, patch: Partial<PlanItem> = {}): PlanItem {
  return {
    entry_id: id,
    invoice_number: `FV/${id}/11/2026`,
    ksef_number: null,
    seller_name: `Dostawca ${id}`,
    seller_nip: "1234563218",
    category: "office",
    due_date: "2026-11-12",
    currency: "PLN",
    gross_amount: "100.00",
    vat_amount: "18.70",
    to_pay: "100.00",
    amount_note: null,
    account_note: null,
    mode: "standard",
    mode_label: "Zwykły",
    mode_suggested: false,
    account: "90109000000000000000004242",
    account_source: "manual",
    account_source_label: "wpisany na karcie",
    title: `FV/${id}/11/2026`,
    white_list: { state: "listed", label: "W wykazie VAT", request_id: "r-1" },
    selectable: true,
    block: null,
    block_label: null,
    acks: [],
    hints: [],
    batch_id: null,
    preselect: true,
    ...patch,
  };
}

const PLAN: PaymentPlan = {
  until: "2026-11-13",
  items: [
    item(1),
    item(2, {
      to_pay: "20000.00",
      mode: "mpp",
      mode_label: "MPP",
      white_list: { state: "off", label: "Nie sprawdzono (sprawdzanie wyłączone)" },
      acks: [{ code: "white_list", label: "Rachunek niepotwierdzony w wykazie VAT" }],
      preselect: false,
    }),
    item(3, {
      selectable: false,
      block: "payroll_path",
      block_label: "Faktura osoby zespołu — zapłatę prowadzą Płace (rozliczenie miesiąca).",
      preselect: false,
    }),
  ],
  count: 3,
  selectable: 2,
  blocked: 1,
  totals: { PLN: "20100.00" },
};

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PaymentsTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
  get.mockImplementation(async (url: string) => {
    if (url.endsWith("/settings")) {
      return { data: { sender_name: "Spółka Przykładowa", sender_account: "90109000000000000000004242" } };
    }
    if (url.endsWith("/batches")) return { data: { items: [] } };
    if (url.endsWith("/statements")) return { data: { unmatched: [], recent: [] } };
    throw new Error(`nieoczekiwany GET ${url}`);
  });
  post.mockImplementation(async (url: string) => {
    if (url.endsWith("/plan")) return { data: PLAN };
    if (url.endsWith("/batches")) {
      return { data: { id: 7, count: 2, total: "20100.00", currency: "PLN", items: [] } };
    }
    throw new Error(`nieoczekiwany POST ${url}`);
  });
});

describe("PaymentsTab", () => {
  it("faktura z ostrzeżeniem wchodzi do paczki dopiero po odhaczeniu", async () => {
    const user = userEvent.setup();
    renderTab();
    const first = await screen.findByRole("checkbox", { name: "Zaznacz FV/1/11/2026" });
    expect(first).toBeChecked();
    const second = screen.getByRole("checkbox", { name: "Zaznacz FV/2/11/2026" });
    expect(second).not.toBeChecked();
    // Faktura osoby zespołu: widoczna dla Płac, ale nie do zaznaczenia.
    expect(screen.getByRole("checkbox", { name: "Zaznacz FV/3/11/2026" })).toBeDisabled();
    expect(screen.getByText(/zapłatę prowadzą Płace/)).toBeInTheDocument();

    const create = screen.getByRole("button", { name: "Utwórz paczkę" });
    expect(create).toBeEnabled();
    await user.click(second);
    expect(create).toBeDisabled();
    expect(screen.getByText("Odhacz ostrzeżenia przy 1 fakturze.")).toBeInTheDocument();

    await user.click(
      screen.getByRole("checkbox", { name: /Sprawdzone: Rachunek niepotwierdzony/ }),
    );
    expect(create).toBeEnabled();
    await user.click(create);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/finance/payments/batches",
        expect.objectContaining({ entry_ids: [1, 2], acknowledged: [2], format: "elixir" }),
      ),
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(expect.stringContaining("Paczka #7"), "success"),
    );
  });

  it("podgląd jako inna osoba — bez zaznaczania i bez przycisku paczki", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <PaymentsTab canWrite={false} />
      </QueryClientProvider>,
    );
    const first = await screen.findByRole("checkbox", { name: "Zaznacz FV/1/11/2026" });
    expect(first).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Utwórz paczkę" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wgraj wyciąg" })).not.toBeInTheDocument();
  });

  it("awaria planu nie wygląda jak pusta lista", async () => {
    post.mockRejectedValueOnce(new Error("500"));
    renderTab();
    const notice = await screen.findByRole("button", { name: /Spróbuj ponownie/ });
    expect(notice).toBeInTheDocument();
    expect(screen.queryByText(/Nie ma faktur z terminem/)).not.toBeInTheDocument();
    expect(within(document.body).queryByRole("button", { name: "Utwórz paczkę" })).toBeNull();
  });
});

describe("PaymentsTab — paczka czekająca na bank", () => {
  it("nieaktualny plik widać na liście, a „Zdejmij z paczki” zdejmuje fakturę", async () => {
    const user = userEvent.setup();
    get.mockImplementation(async (url: string) => {
      if (url.endsWith("/settings")) return { data: { sender_name: null, sender_account: null } };
      if (url.endsWith("/statements")) return { data: { unmatched: [], recent: [] } };
      if (url.endsWith("/batches")) {
        return {
          data: {
            items: [
              {
                id: 5,
                currency: "PLN",
                format: "elixir",
                execution_date: "2026-11-13",
                created_at: null,
                created_by_name: null,
                count: 2,
                total: "300.00",
                status: "active",
                status_label: "Czeka na bank",
                file_sha256: "abcdef123456",
                downloaded_at: "2026-11-13T09:00:00+00:00",
                changed_at: "2026-11-13T10:00:00+00:00",
                file_stale: true,
              },
            ],
          },
        };
      }
      if (url.endsWith("/batches/5")) {
        return {
          data: {
            id: 5,
            items: [
              {
                entry_id: 1,
                invoice_number: "FV/1/11/2026",
                recipient_name: "Dostawca 1",
                account: "90109000000000000000004242",
                account_source: "ksef_factor",
                account_source_label: "faktor",
                amount: "100.00",
                currency: "PLN",
                mode: "standard",
                mode_label: "Zwykły",
                title: "FV/1/11/2026",
                white_list: { state: "listed", label: "W wykazie VAT" },
                acknowledged: false,
                status: "active",
              },
            ],
          },
        };
      }
      throw new Error(`nieoczekiwany GET ${url}`);
    });
    post.mockImplementation(async (url: string) => {
      if (url.endsWith("/plan")) return { data: { ...PLAN, items: [] } };
      if (url.endsWith("/release")) {
        return { data: { released: 1, batch_cancelled: false, file_stale: true } };
      }
      throw new Error(`nieoczekiwany POST ${url}`);
    });
    renderTab();
    expect(await screen.findByText("Plik nieaktualny — pobierz ponownie")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pozycje" }));
    expect(await screen.findByText("faktor")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zdejmij z paczki" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Zdejmij z paczki" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/payments/batches/5/items/1/release"),
    );
  });
});
