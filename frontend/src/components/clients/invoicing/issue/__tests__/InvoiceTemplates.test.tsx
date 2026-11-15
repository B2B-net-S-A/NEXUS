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
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));
const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

import { BatchSendBar } from "@/components/clients/invoicing/issue/BatchSendBar";
import { ImportTemplatesDialog } from "@/components/clients/invoicing/issue/ImportTemplatesDialog";
import { ManualInvoiceDialog } from "@/components/clients/invoicing/issue/ManualInvoiceDialog";
import { TemplatesPanel } from "@/components/clients/invoicing/issue/TemplatesPanel";
import type { InvoiceTemplate, TemplateSuggestion } from "@/lib/api/issued-invoices";

const BUYER = { name: "Jan Testowy Usługi IT", number: "3333333333", address_l1: "ul. Kontraktowa 3", address_l2: "00-950 Warszawa", country: "PL" };
const LINE = {
  name: "Refaktura kosztów pakietu sportowego",
  consultant: null,
  quantity: "1",
  unit: "szt.",
  unit_price: "65.74",
  vat_rate: "8",
  net: "65.74",
  order_id: null,
};

function template(id: number, patch: Partial<InvoiceTemplate> = {}): InvoiceTemplate {
  return {
    id,
    kind: "benefit",
    kind_label: "refaktura benefitu",
    benefit: "sport",
    benefit_label: "pakiet sportowy",
    name: `Kontraktor ${id}`,
    active: true,
    client_id: null,
    buyer: BUYER,
    currency: "PLN",
    series_code: "PL",
    lines: [LINE],
    net: "65.74",
    payment_days: null,
    notes: null,
    valid_from: null,
    valid_to: null,
    source: "ksef",
    source_ref: null,
    in_month: true,
    problem: null,
    address_missing: false,
    issued: null,
    invoiced_in_ksef: [],
    selectable: true,
    ...patch,
  };
}

const TEMPLATES = [
  template(1),
  template(2),
  template(3, {
    selectable: false,
    issued: { id: 40, invoice_number: null, status: "draft", status_label: "Szkic" },
  }),
  template(4, { active: false, selectable: false }),
  template(5, { selectable: false, invoiced_in_ksef: ["5/10/2026"] }),
];

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
  push.mockReset();
});

describe("TemplatesPanel", () => {
  it("creates drafts only from templates that can be issued this month", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: { year: 2026, month: 11, templates: TEMPLATES } });
    post.mockResolvedValue({ data: { created: [41, 42] } });
    const onCreated = vi.fn();
    wrap(<TemplatesPanel period="2026-11" onCreated={onCreated} />);

    expect(await screen.findByText("Kontraktor 1")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Zaznacz szablon Kontraktor 3" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Zaznacz szablon Kontraktor 4" })).toBeDisabled();
    expect(within(screen.getByTestId("template-3")).getByRole("link", { name: "Szkic" })).toHaveAttribute(
      "href",
      "/finance/faktury/40",
    );
    expect(within(screen.getByTestId("template-4")).getByText("wyłączony")).toBeInTheDocument();
    expect(within(screen.getByTestId("template-5")).getByText("zafakturowane w KSeF")).toBeInTheDocument();
    expect(within(screen.getByTestId("template-5")).getByText("5/10/2026")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Zaznacz wszystkie do wystawienia" }));
    await user.click(screen.getByRole("button", { name: "Utwórz szkice (2)" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/issued-invoices/templates/run", {
        year: 2026,
        month: 11,
        template_ids: [1, 2],
      }),
    );
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith([41, 42]));
  });

  it("does not pretend an outage is an empty list", async () => {
    get.mockRejectedValue(new Error("500"));
    wrap(<TemplatesPanel period="2026-11" onCreated={vi.fn()} />);
    await waitFor(() => expect(screen.queryByText("Wczytywanie szablonów…")).not.toBeInTheDocument());
    expect(screen.queryByText(/Nie ma jeszcze szablonów/)).not.toBeInTheDocument();
  });

  it("filters by kind through the API", async () => {
    const user = userEvent.setup();
    get.mockResolvedValue({ data: { year: 2026, month: 11, templates: TEMPLATES } });
    wrap(<TemplatesPanel period="2026-11" onCreated={vi.fn()} />);
    await screen.findByText("Kontraktor 1");
    await user.click(screen.getByRole("button", { name: "Refaktury benefitów" }));
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/finance/issued-invoices/templates", {
        params: { year: 2026, month: 11, kind: "benefit" },
      }),
    );
  });
});

describe("ImportTemplatesDialog", () => {
  it("preselects invoices without a template and imports them from the previous month", async () => {
    const user = userEvent.setup();
    const rows: TemplateSuggestion[] = [
      {
        ksef_number: "K-1",
        invoice_number: "1/10/2026",
        buyer_name: "Jan Testowy Usługi IT",
        buyer_number: "3333333333",
        client_id: null,
        kind: "benefit",
        benefit: "sport",
        lines: [LINE],
        net: "65.74",
        currency: "PLN",
        address_missing: false,
        has_template: false,
      },
      {
        ksef_number: "K-2",
        invoice_number: "2/10/2026",
        buyer_name: "Firma Z Szablonem",
        buyer_number: "1111111111",
        client_id: 7,
        kind: "service",
        benefit: null,
        lines: [{ ...LINE, name: "Usługa IT {mm}.{rrrr}" }],
        net: "12000.00",
        currency: "PLN",
        address_missing: false,
        has_template: true,
      },
    ];
    get.mockResolvedValue({ data: { rows, counts: { all: 2, benefit: 1, has_template: 1 } } });
    post.mockResolvedValue({ data: { created: [9] } });
    const onClose = vi.fn();
    wrap(<ImportTemplatesDialog period="2026-11" onClose={onClose} />);

    await screen.findByText("Jan Testowy Usługi IT");
    expect(get).toHaveBeenCalledWith("/api/finance/issued-invoices/templates/suggestions", {
      params: { year: 2026, month: 10 },
    });
    expect(screen.getByRole("checkbox", { name: "Szablon z faktury 2/10/2026" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Utwórz szablony (1)" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/issued-invoices/templates/import", {
        year: 2026,
        month: 10,
        ksef_numbers: ["K-1"],
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe("ManualInvoiceDialog", () => {
  it("creates a draft for a buyer outside the client list and opens it", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({ data: { id: 77 } });
    wrap(<ManualInvoiceDialog onClose={vi.fn()} />);
    await user.click(screen.getByRole("radio", { name: "Inny nabywca" }));
    await user.click(screen.getByRole("button", { name: "Utwórz szkic" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Podaj nazwę albo NIP nabywcy.");
    expect(post).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Nazwa nabywcy"), "Firma Spoza Kartoteki");
    await user.type(screen.getByLabelText("NIP albo VAT UE"), "3333333333");
    await user.click(screen.getByRole("button", { name: "Utwórz szkic" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/issued-invoices/manual", {
        buyer: { name: "Firma Spoza Kartoteki", number: "3333333333", address_l1: "", address_l2: "" },
        currency: "PLN",
      }),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/finance/faktury/77"));
  });
});

describe("BatchSendBar", () => {
  it("sends selected drafts one by one after confirmation and reports what needs fixing", async () => {
    const user = userEvent.setup();
    post.mockImplementation((url: string) =>
      url.endsWith("/41/send")
        ? Promise.resolve({ data: { id: 41, status: "accepted", invoice_number: "1/11/2026" } })
        : Promise.reject(Object.assign(new Error("409"), { response: { status: 409, data: { detail: "Uzupełnij nazwę i adres nabywcy." } } })),
    );
    const onDone = vi.fn();
    wrap(<BatchSendBar ids={[41, 42]} labels={{ 41: "Kontraktor 1", 42: "Kontraktor 2" }} disabledReason={null} onDone={onDone} />);
    await user.click(screen.getByRole("button", { name: "Wyślij zaznaczone do KSeF (2)" }));
    expect(post).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog").catch(() => screen.findByRole("dialog"));
    await user.click(within(dialog).getByRole("button", { name: "Wyślij do KSeF" }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(post.mock.calls.map((call) => call[0])).toEqual([
      "/api/finance/issued-invoices/41/send",
      "/api/finance/issued-invoices/42/send",
    ]);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Przyjęte w KSeF: 1");
    expect(status).toHaveTextContent("do poprawy: 1");
    expect(within(status).getByRole("link", { name: "Kontraktor 2" })).toHaveAttribute("href", "/finance/faktury/42");
  });

  it("stays disabled with the reason when sending is off", () => {
    wrap(<BatchSendBar ids={[41]} labels={{}} disabledReason="Wysyłka wyłączona." onDone={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Wyślij zaznaczone do KSeF (1)" })).toBeDisabled();
  });
});
