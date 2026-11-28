import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
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

import { IssueMonthPanel } from "@/components/clients/invoicing/issue/IssueMonthPanel";
import { IssuedInvoiceCardView } from "@/components/clients/invoicing/issue/IssuedInvoiceCardView";
import { invoiceSteps, previewNet, sendDisabledReason } from "@/components/clients/invoicing/issue/issue-format";
import type { IssuedInvoiceCard, ToIssueClient } from "@/lib/api/issued-invoices";

const TO_ISSUE: ToIssueClient[] = [
  {
    client_id: 7,
    client_name: "Bank Testowy S.A.",
    rows: [
      {
        key: "g118",
        kind: "md",
        order_number: "ZAM/2026/118",
        currency: "PLN",
        expected_net: "25200.00",
        people: 1,
        blocked: null,
        needs_amount: false,
        invoiced_in_ksef: [],
        issued: [],
      },
      {
        key: "g140",
        kind: "md",
        order_number: "ZAM/2026/140",
        currency: "PLN",
        expected_net: null,
        people: 1,
        blocked: "Brak kwoty pozycji (czeka na zużycie MD albo stawkę): Ola Przykładowa.",
        needs_amount: false,
        invoiced_in_ksef: [],
        issued: [],
      },
      {
        key: "g124",
        kind: "md",
        order_number: "ZAM/2026/124",
        currency: "PLN",
        expected_net: "22425.00",
        people: 1,
        blocked: null,
        needs_amount: false,
        invoiced_in_ksef: [],
        issued: [{ id: 3, status: "draft", status_label: "Szkic", invoice_number: null }],
      },
      {
        key: "g131",
        kind: "md",
        order_number: "ZAM/2026/131",
        currency: "PLN",
        expected_net: "18900.00",
        people: 1,
        blocked: null,
        needs_amount: false,
        invoiced_in_ksef: ["77/10/2026"],
        issued: [],
      },
    ],
  },
];

const CARD: IssuedInvoiceCard = {
  id: 5,
  status: "draft",
  status_label: "Szkic",
  invoice_type: "VAT",
  type_label: "Faktura",
  series_code: "PL",
  invoice_number: null,
  client_id: 7,
  client_name: "Bank Testowy S.A.",
  template_id: null,
  buyer: {
    name: "Bank Testowy S.A.",
    number: "1111111111",
    address_l1: "ul. Przykładowa 5",
    address_l2: "",
    country: "PL",
  },
  buyer_kind: "nip",
  order_group_id: 118,
  order_id: null,
  client_order_number: "ZAM/2026/118",
  period: "2026-10",
  currency: "PLN",
  issue_date: "2026-11-20",
  sale_date: "2026-10-31",
  period_from: "2026-10-01",
  period_to: "2026-10-31",
  due_date: "2026-12-04",
  net: "25200.00",
  vat: "5796.00",
  gross: "30996.00",
  ksef_number: null,
  ksef_status_text: null,
  sent_at: null,
  accepted_at: null,
  payment: { status: "none", paid: null },
  lines: [
    {
      name: "Usługi informatyczne — Jan Przykładowy — październik 2026",
      consultant: "Jan Przykładowy",
      quantity: "21",
      unit: "MD",
      unit_price: "1200",
      vat_rate: "23",
      net: "25200.00",
      order_id: 11,
    },
  ],
  lines_before: [],
  warnings: [],
  checks: [],
  order_numbers: ["ZAM/2026/118"],
  contract_number: null,
  contract_date: null,
  contract_rule: null,
  requirements: [],
  mail: null,
  buyer_options: [],
  rates: [{ code: "23", label: "23%", net: "25200.00", vat: "5796.00" }],
  fx: null,
  notes: null,
  correction_reason: null,
  corrects: null,
  collective: null,
  ksef_status_code: null,
  ksef_environment: null,
  has_upo: false,
  has_xml: false,
  sales_invoice_id: null,
  problems: [],
  editable: true,
  can_send: true,
  can_check: false,
  can_correct: false,
  history: [],
  rebate: null,
};

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function mockCard(card: IssuedInvoiceCard, ksefReason: string | null = null) {
  get.mockImplementation((url: string) => {
    if (url === "/api/finance/issued-invoices/5") return Promise.resolve({ data: card });
    if (url === "/api/finance/issued-invoices/settings") {
      return Promise.resolve({
        data: {
          vat_rates: [
            { code: "23", label: "23%" },
            { code: "np II", label: "np. — usługi w UE, odwrotne obciążenie" },
          ],
          ksef: { mode: ksefReason ? "off" : "test", mode_label: "", enabled: !ksefReason, disabled_reason: ksefReason },
        },
      });
    }
    return Promise.reject(new Error(`unexpected ${url}`));
  });
}

describe("issue-format", () => {
  it("walks the steps from draft to paid", () => {
    expect(invoiceSteps(CARD).map((step) => step.state)).toEqual(["current", "current", "todo", "todo", "todo"]);
    const accepted = invoiceSteps({
      ...CARD,
      status: "accepted",
      invoice_number: "1/11/2026",
      ksef_number: "9876543210-20261120-E40000000001-1A",
      has_upo: true,
      can_send: false,
      editable: false,
      payment: { status: "paid", paid: "30996.00" },
    });
    expect(accepted.map((step) => step.state)).toEqual(["done", "done", "done", "done", "done"]);
    expect(accepted[2].detail).toBe("9876543210-20261120-E40000000001-1A");
    const rejected = invoiceSteps({ ...CARD, status: "rejected", invoice_number: "1/11/2026", can_send: false });
    expect(rejected[1]).toMatchObject({ state: "failed", detail: "odrzucona" });
  });

  it("previews line net and explains a blocked send", () => {
    expect(previewNet({ quantity: "19,5", unit_price: "1150" })).toBe("22425.00");
    expect(previewNet({ quantity: "1", unit_price: null })).toBeNull();
    const blocked = { ...CARD, can_send: false, problems: ["Brak rachunku PLN w ustawieniach wystawiania."] };
    expect(sendDisabledReason(blocked, null)).toContain("Brak rachunku PLN");
    expect(sendDisabledReason(blocked, "Wysyłka faktur do KSeF jest wyłączona (KSEF_SALES_ISSUE_MODE=off).")).toContain(
      "KSEF_SALES_ISSUE_MODE=off",
    );
  });
});

describe("IssueMonthPanel", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    showToast.mockReset();
    get.mockResolvedValue({ data: { period: "2026-10", clients: TO_ISSUE } });
  });

  it("creates drafts only from rows that can be issued", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    post.mockResolvedValue({ data: { created: [9] } });
    wrap(<IssueMonthPanel period="2026-10" onCreated={onCreated} />);

    const blocked = await screen.findByTestId("to-issue-g140");
    expect(within(blocked).getByRole("checkbox")).toBeDisabled();
    expect(blocked).toHaveTextContent("czeka na zużycie MD");
    expect(within(screen.getByTestId("to-issue-g124")).getByRole("checkbox")).toBeDisabled();
    // Zamówienie zafakturowane już w KSeF poza NEXUSEM (np. w eBI24) — bez drugiego szkicu.
    const elsewhere = screen.getByTestId("to-issue-g131");
    expect(within(elsewhere).getByRole("checkbox")).toBeDisabled();
    expect(within(elsewhere).getByText("zafakturowane w KSeF")).toBeInTheDocument();

    await user.click(within(screen.getByTestId("to-issue-g118")).getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Utwórz szkice (1)" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/issued-invoices/drafts", {
        year: 2026,
        month: 10,
        keys: ["g118"],
        split: "order",
      }),
    );
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith([9]));
  });

  it("z linku „Wystaw” pokazuje jednego klienta z zaznaczonymi zamówieniami", async () => {
    const user = userEvent.setup();
    const other: ToIssueClient = {
      ...TO_ISSUE[0],
      client_id: 8,
      client_name: "Inny klient",
      rows: [{ ...TO_ISSUE[0].rows.find((r) => r.key === "g118")!, key: "g900", order_number: "ZAM-INNE" }],
    };
    get.mockResolvedValue({ data: { period: "2026-10", clients: [...TO_ISSUE, other] } });
    post.mockResolvedValue({ data: { created: [9] } });
    wrap(<IssueMonthPanel period="2026-10" clientId={7} onCreated={vi.fn()} />);

    expect(await screen.findByText(/zaznaczono zamówienia do wystawienia/)).toBeInTheDocument();
    expect(screen.queryByTestId("to-issue-g900")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("to-issue-g118")).getByRole("checkbox")).toBeChecked();
    expect(within(screen.getByTestId("to-issue-g140")).getByRole("checkbox")).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Utwórz szkice (1)" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/issued-invoices/drafts", {
        year: 2026,
        month: 10,
        keys: ["g118"],
        split: "order",
      }),
    );
  });

  it("„Pokaż wszystkich klientów” zdejmuje filtr i zaznaczenie", async () => {
    const user = userEvent.setup();
    const other: ToIssueClient = { ...TO_ISSUE[0], client_id: 8, client_name: "Inny klient", rows: [] };
    get.mockResolvedValue({ data: { period: "2026-10", clients: [...TO_ISSUE, other] } });
    wrap(<IssueMonthPanel period="2026-10" clientId={7} onCreated={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "Pokaż wszystkich klientów" }));
    expect(screen.getByText("Inny klient")).toBeInTheDocument();
    expect(within(screen.getByTestId("to-issue-g118")).getByRole("checkbox")).not.toBeChecked();
  });

  it("klient spoza listy do wystawienia nie chowa reszty", async () => {
    wrap(<IssueMonthPanel period="2026-10" clientId={999} onCreated={vi.fn()} />);
    expect(await screen.findByTestId("to-issue-g118")).toBeInTheDocument();
    expect(screen.queryByText(/zaznaczono zamówienia do wystawienia/)).not.toBeInTheDocument();
    expect(within(screen.getByTestId("to-issue-g118")).getByRole("checkbox")).not.toBeChecked();
  });

  it("shows an empty month only after a successful load", async () => {
    get.mockResolvedValue({ data: { period: "2026-10", clients: [] } });
    wrap(<IssueMonthPanel period="2026-10" onCreated={vi.fn()} />);
    expect(await screen.findByText(/nie ma zamówień do zafakturowania/)).toBeInTheDocument();
  });

  it("does not pretend an outage is an empty month", async () => {
    get.mockRejectedValue(new Error("awaria"));
    wrap(<IssueMonthPanel period="2026-10" onCreated={vi.fn()} />);
    await waitFor(() => expect(screen.queryByText(/nie ma zamówień do zafakturowania/)).not.toBeInTheDocument());
    expect(await screen.findByRole("button", { name: /ponów|spróbuj/i })).toBeInTheDocument();
  });
});

describe("IssuedInvoiceCardView", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    put.mockReset();
    showToast.mockReset();
  });

  it("sends to KSeF only after confirmation", async () => {
    const user = userEvent.setup();
    mockCard(CARD);
    post.mockResolvedValue({
      data: { ...CARD, status: "accepted", status_label: "Przyjęta w KSeF", invoice_number: "1/11/2026" },
    });
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    await user.click(await screen.findByRole("button", { name: "Wyślij do KSeF" }));
    expect(post).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("alertdialog").catch(() => screen.findByRole("dialog"));
    expect(dialog).toHaveTextContent("kolejny numer z serii");
    await user.click(within(dialog).getByRole("button", { name: "Wyślij do KSeF" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/finance/issued-invoices/5/send"));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Przyjęta w KSeF: 1/11/2026", "success"));
  });

  it("asks for a reason when the pre-send check has remarks", async () => {
    const user = userEvent.setup();
    const remark = "Data sprzedaży 14.11.2026 poza okresem usługi (październik 2026).";
    mockCard({ ...CARD, checks: [remark] });
    post.mockResolvedValue({
      data: { ...CARD, status: "accepted", status_label: "Przyjęta w KSeF", invoice_number: "1/11/2026" },
    });
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    const box = await screen.findByRole("region", { name: "Kontrola przed wysyłką" });
    expect(box).toHaveTextContent(remark);
    await user.click(screen.getByRole("button", { name: "Wyślij do KSeF" }));
    const dialog = await screen.findByRole("alertdialog").catch(() => screen.findByRole("dialog"));
    const confirm = within(dialog).getByRole("button", { name: "Wyślij mimo uwag" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByRole("textbox"), "Klient chce datę z protokołu");
    await user.click(confirm);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/issued-invoices/5/send", {
        checks_reason: "Klient chce datę z protokołu",
      }),
    );
  });

  it("keeps send disabled with the reason when issuing is off", async () => {
    mockCard({ ...CARD, can_send: false }, "Wysyłka faktur do KSeF jest wyłączona (KSEF_SALES_ISSUE_MODE=off).");
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    const button = await screen.findByRole("button", { name: "Wyślij do KSeF" });
    expect(button).toBeDisabled();
    expect(await screen.findByText(/KSEF_SALES_ISSUE_MODE=off/)).toBeInTheDocument();
  });

  it("saves edited lines with decimal points for the API", async () => {
    const user = userEvent.setup();
    mockCard(CARD);
    put.mockResolvedValue({ data: CARD });
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    const quantity = await screen.findByLabelText("Ilość — pozycja 1");
    await user.clear(quantity);
    await user.type(quantity, "19,5");
    expect(screen.getByRole("button", { name: "Wyślij do KSeF" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Zapisz szkic" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    const [url, patch] = put.mock.calls[0];
    expect(url).toBe("/api/finance/issued-invoices/5");
    expect(patch.lines[0]).toMatchObject({ quantity: "19.5", unit_price: "1200", vat_rate: "23" });
    expect(patch.series_code).toBe("PL");
  });
});

describe("IssuedInvoiceCardView — seria Benefit", () => {
  beforeEach(() => {
    get.mockReset();
    put.mockReset();
  });

  it("keeps the benefit series when a draft is saved", async () => {
    const user = userEvent.setup();
    const card = { ...CARD, series_code: "BEN" as const };
    mockCard(card);
    put.mockResolvedValue({ data: card });
    wrap(<IssuedInvoiceCardView invoiceId={5} />);
    const notes = await screen.findByLabelText(/Uwagi/);
    await user.type(notes, "x");
    await user.click(screen.getByRole("button", { name: /Zapisz/ }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put.mock.calls[0][1]).toMatchObject({ series_code: "BEN" });
  });
});
