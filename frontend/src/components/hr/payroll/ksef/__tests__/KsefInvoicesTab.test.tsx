import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

import { KsefInvoicesTab } from "@/components/hr/payroll/ksef/KsefInvoicesTab";
import { KsefStatusCard } from "@/components/hr/payroll/ksef/KsefStatusCard";
import type { KsefInvoiceList, KsefStatus } from "@/lib/api/hr-ksef";

import { STATUS, invoice } from "./ksef-fixtures";

const LIST: KsefInvoiceList = {
  invoices: [
    invoice(),
    invoice({
      id: 2,
      ksef_number: "1234563218-20261104-5F2A9C0D71B3-4E",
      seller_nip: "1234563218",
      seller_name: "Nowak Recruitment Ola Nowak",
      user: { id: 8, name: "Ola Nowak" },
      invoice_number: "FV 10/2026",
      settlement: { id: 4, status: "ready", expected_amount: "17160.00", year: 2026, month: 10 },
    }),
    invoice({
      id: 3,
      source: "manual_pdf",
      ksef_number: null,
      seller_nip: "5555555555",
      seller_name: null,
      user: { id: 9, name: "Kamil Wzorcowy" },
      invoice_number: "1/11/2026",
      match_status: "unmatched",
      settlement: null,
      period: null,
      has_pdf: true,
    }),
  ],
  counts: { total: 3, matched: 2, unmatched: 1, ignored: 0 },
};

function mockApi({
  status = STATUS,
  list = LIST,
  listFails = false,
}: { status?: KsefStatus; list?: KsefInvoiceList; listFails?: boolean } = {}) {
  get.mockImplementation((url: string) => {
    if (url === "/api/hr/ksef/status") return Promise.resolve({ data: status });
    if (url === "/api/hr/ksef/invoices") {
      if (listFails) return Promise.reject({ response: { status: 500, data: { detail: "Błąd" } } });
      return Promise.resolve({ data: list });
    }
    if (url === "/api/hr/payroll/months/2026/10") {
      return Promise.resolve({
        data: {
          people: [
            { user_id: 8, name: "Ola Nowak", employment_type: "b2b" },
            { user_id: 10, name: "Ewa Kadrowa", employment_type: "uop" },
          ],
        },
      });
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

function renderWithClient(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
});

describe("KsefInvoicesTab", () => {
  it("lists team invoices with their match state and asks to assign the rest", async () => {
    mockApi();
    renderWithClient(<KsefInvoicesTab year={2026} month={10} />);

    const anna = await screen.findByTestId("ksef-invoice-1");
    expect(within(anna).getByText("…-20261105-0B91E4C2A7D8-1F")).toBeInTheDocument();
    expect(within(anna).getByText("Anna Przykładowa Consulting")).toBeInTheDocument();
    expect(within(anna).getByText("NIP 777…7777")).toBeInTheDocument();
    expect(within(anna).getByText("Anna P. · październik")).toBeInTheDocument();
    expect(within(anna).getByText("rozbieżność")).toBeInTheDocument();
    expect(within(anna).queryByRole("button", { name: "Przypisz" })).not.toBeInTheDocument();

    expect(within(screen.getByTestId("ksef-invoice-2")).getByText("zgodna")).toBeInTheDocument();

    const manual = screen.getByTestId("ksef-invoice-3");
    expect(within(manual).getByText("spoza KSeF (PDF)")).toBeInTheDocument();
    expect(within(manual).getByText("do przypisania")).toBeInTheDocument();
    expect(within(manual).getByRole("button", { name: "Przypisz" })).toBeInTheDocument();
    expect(within(manual).getByRole("button", { name: "PDF faktury 1/11/2026" })).toBeInTheDocument();

    expect(screen.getByText(/Ostatnie pobranie: 17\.11\.2026, 14:00/)).toBeInTheDocument();
    expect(screen.getByText(/w ostatnim pobraniu: 4/)).toBeInTheDocument();
  });

  it("shows a failed list as an error, never as an empty month", async () => {
    mockApi({ listFails: true });
    renderWithClient(<KsefInvoicesTab year={2026} month={10} />);
    expect(await screen.findByText("Nie udało się pobrać danych")).toBeInTheDocument();
    expect(screen.queryByText(/nie ma jeszcze faktur/)).not.toBeInTheDocument();
  });

  it("explains the switched-off integration and hides fetching", async () => {
    mockApi({
      status: {
        ...STATUS,
        mode: "off",
        mode_label: "wyłączone",
        enabled: false,
        health: "disabled",
        disabled_text: "Pobieranie z KSeF jest wyłączone (KSEF_MODE=off).",
      },
      list: { invoices: [], counts: { total: 0, matched: 0, unmatched: 0, ignored: 0 } },
    });
    renderWithClient(<KsefInvoicesTab year={2026} month={10} />);
    expect(await screen.findByText("KSeF: wyłączone")).toBeInTheDocument();
    expect(screen.getByText(/KSEF_MODE=off/)).toBeInTheDocument();
    expect(await screen.findByText("Za październik 2026 nie ma jeszcze faktur od zespołu.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pobierz teraz/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Faktura spoza KSeF/ })).toBeInTheDocument();
  });

  it("fetches now and tells what came in", async () => {
    mockApi();
    post.mockResolvedValue({ data: { status: "ok", saved: 2, matched: 2, skipped: 1 } });
    renderWithClient(<KsefInvoicesTab year={2026} month={10} />);
    await userEvent.click(await screen.findByRole("button", { name: /Pobierz teraz/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/hr/ksef/fetch"));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        "Nowe faktury od zespołu: 2 · dopasowane: 2 · 1 faktura dostawców pominięte.",
        "success",
      ),
    );
  });

  it("disables fetching while KSeF pauses requests", async () => {
    mockApi({ status: { ...STATUS, blocked_until: "2026-11-17T13:15:00.000+00:00" } });
    renderWithClient(<KsefInvoicesTab year={2026} month={10} />);
    expect(await screen.findByRole("button", { name: /Pobierz teraz/ })).toBeDisabled();
    expect(screen.getByText(/kolejne pobranie po 17\.11\.2026, 14:15/)).toBeInTheDocument();
  });

  it("skips an invoice only with a reason", async () => {
    mockApi();
    post.mockResolvedValue({ data: invoice({ id: 3, match_status: "ignored", settlement: null }) });
    renderWithClient(<KsefInvoicesTab year={2026} month={10} />);
    const manual = await screen.findByTestId("ksef-invoice-3");
    await userEvent.click(within(manual).getByRole("button", { name: "Pomiń" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Pomiń" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Napisz, dlaczego faktura nie jest rozliczeniem.",
    );
    expect(post).not.toHaveBeenCalled();
    await userEvent.type(within(dialog).getByLabelText("Powód"), "Zwrot kosztów sprzętu");
    await userEvent.click(within(dialog).getByRole("button", { name: "Pomiń" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/hr/ksef/invoices/3/ignore", {
        ignored: true,
        reason: "Zwrot kosztów sprzętu",
      }),
    );
  });

  it("shows server refusal in the manual invoice dialog", async () => {
    mockApi();
    renderWithClient(<KsefInvoicesTab year={2026} month={10} />);
    await userEvent.click(await screen.findByRole("button", { name: /Faktura spoza KSeF/ }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Dodaj fakturę" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Wybierz osobę.");
    expect(post).not.toHaveBeenCalled();
  });
});

describe("KsefStatusCard", () => {
  it("shows environment, last fetch, white list usage and problems read-only", async () => {
    mockApi({
      status: {
        ...STATUS,
        last_error: "auth_failed (450)",
        last_error_text: "KSeF odrzucił uwierzytelnienie tokenem spółki: nieprawidłowy, nieaktywny albo unieważniony token.",
        last_error_at: "2026-11-17T13:00:00.000+00:00",
        health: "degraded",
        problems: [
          {
            ksef_number: "1234563218-20261104-5F2A9C0D71B3-4E",
            reason: "parse:missing_amounts",
            text: "Pliku faktury nie da się odczytać — sprawdź go z osobą w KSeF.",
            at: "2026-11-17T13:00:00.000+00:00",
          },
        ],
      },
    });
    renderWithClient(<KsefStatusCard />);
    expect(await screen.findByText("testowe MF")).toBeInTheDocument();
    expect(screen.getByText("987-654-32-10")).toBeInTheDocument();
    expect(screen.getByText("Ustawiony")).toBeInTheDocument();
    expect(screen.getByText(/nieprawidłowy, nieaktywny albo unieważniony token/)).toBeInTheDocument();
    expect(screen.getByText(/2\/100 wyszukań/)).toBeInTheDocument();
    expect(screen.getByText("1234563218-20261104-5F2A9C0D71B3-4E")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
