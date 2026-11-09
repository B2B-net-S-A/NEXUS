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
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));

const showToast = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));

vi.mock("@/components/clients/ClientSinglePicker", () => ({
  ClientSinglePicker: ({ onChange }: { onChange: (client: { id: number; name: string }) => void }) => (
    <button type="button" onClick={() => onChange({ id: 7, name: "Klient Fikcyjny" })}>
      Wybierz klienta
    </button>
  ),
}));

import { AssignInvoiceDialog } from "@/components/clients/invoicing/SalesInvoiceDialogs";
import type { BuyerNumberCheck, SalesInvoice } from "@/lib/api/client-invoicing";

import { CLIENT_MONTH } from "@/app/preview/client-invoicing/fixtures";

const UNKNOWN: SalesInvoice = {
  ...CLIENT_MONTH.invoices[3],
  client_id: null,
  client_name: null,
  buyer_name: "Nabywca Fikcyjny",
  buyer_nip: "3333333333",
  buyer_foreign_id: null,
  period: "2026-10",
};

const ORDER = {
  group_id: null,
  order_id: 11,
  label: "ZAM/FIKCYJNE/1",
  kind: "periodic",
  expected_net: "1000.00",
  currency: "PLN",
};

const check = (overrides: Partial<BuyerNumberCheck>): BuyerNumberCheck => ({
  state: "add",
  number: "3333333333",
  kind: "nip",
  client_name: "Klient Fikcyjny",
  existing: null,
  owner_name: null,
  other_waiting: 2,
  ...overrides,
});

function mockOptions(buyerNumber: BuyerNumberCheck) {
  get.mockImplementation(async (_url: string, config?: { params?: { client_id?: number } }) => ({
    data: config?.params?.client_id
      ? { client_id: config.params.client_id, options: [ORDER], buyer_number: buyerNumber }
      : { client_id: null, options: [] },
  }));
}

async function openAndPick(invoice: SalesInvoice = UNKNOWN) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <AssignInvoiceDialog invoice={invoice} fallbackPeriod="2026-10" onClose={onClose} />
    </QueryClientProvider>,
  );
  const dialog = await screen.findByRole("dialog");
  if (!invoice.client_id) {
    await userEvent.click(within(dialog).getByRole("button", { name: "Wybierz klienta" }));
  }
  await userEvent.click(await within(dialog).findByRole("checkbox"));
  return { dialog, onClose };
}

const assigned = (save: boolean) => ({
  targets: [{ order_id: 11 }],
  year: 2026,
  month: 10,
  save_buyer_number: save,
});

describe("AssignInvoiceDialog", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    showToast.mockReset();
    post.mockResolvedValue({ data: UNKNOWN });
  });

  it("lets Finance pick the client of an unknown buyer and add the number on a decision", async () => {
    mockOptions(check({}));
    post.mockResolvedValue({
      data: { ...UNKNOWN, buyer_number: { saved: true, retried: 2, matched: 1 } },
    });
    const { dialog, onClose } = await openAndPick();

    expect(within(dialog).getByText(/Nabywca Fikcyjny · NIP 3333333333/)).toBeInTheDocument();
    expect(within(dialog).getByText(/teraz czeka jeszcze: 2/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Przypisz i dopisz NIP" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(`/api/finance/sales-invoices/${UNKNOWN.id}/assign`, assigned(true)),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(showToast).toHaveBeenCalledWith(
      "Faktura przypisana, numer dopisany do klienta. Faktury tego nabywcy (2) są już u tego klienta, z zamówieniem: 1.",
      "success",
    );
  });

  it("assigns without touching the client on „Tylko przypisz”", async () => {
    mockOptions(check({}));
    const { dialog } = await openAndPick();

    await userEvent.click(within(dialog).getByRole("button", { name: "Tylko przypisz" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(`/api/finance/sales-invoices/${UNKNOWN.id}/assign`, assigned(false)),
    );
    expect(showToast).toHaveBeenCalledWith("Faktura przypisana", "success");
  });

  it("names EU VAT on the button for a foreign buyer", async () => {
    mockOptions(check({ kind: "vat_ue", number: "FI12345678" }));
    const { dialog } = await openAndPick({ ...UNKNOWN, buyer_nip: null, buyer_foreign_id: "FI12345678" });

    expect(within(dialog).getByRole("button", { name: "Przypisz i dopisz VAT UE" })).toBeInTheDocument();
    expect(within(dialog).getByText(/Nabywca Fikcyjny · VAT UE FI12345678/)).toBeInTheDocument();
  });

  it("does not offer the number when the client already has another one", async () => {
    mockOptions(check({ state: "differs", existing: "2222222222" }));
    const { dialog } = await openAndPick();

    expect(within(dialog).getByText(/Klient ma już inny numer \(2222222222\)/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /dopisz/ })).not.toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Przypisz" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(`/api/finance/sales-invoices/${UNKNOWN.id}/assign`, assigned(false)),
    );
  });

  it("does not offer a number that belongs to another client", async () => {
    mockOptions(check({ state: "taken", owner_name: "Inny Klient" }));
    const { dialog } = await openAndPick();

    expect(within(dialog).getByText(/ma już klient Inny Klient/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /dopisz/ })).not.toBeInTheDocument();
  });

  it("adds the number without assigning when the client has no orders that month", async () => {
    get.mockImplementation(async (_url: string, config?: { params?: { client_id?: number } }) => ({
      data: config?.params?.client_id
        ? { client_id: 7, options: [], buyer_number: check({}) }
        : { client_id: null, options: [] },
    }));
    post.mockResolvedValue({ data: { ...UNKNOWN, buyer_number: { saved: true, retried: 3, matched: 0 } } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={client}>
        <AssignInvoiceDialog invoice={UNKNOWN} fallbackPeriod="2026-10" onClose={onClose} />
      </QueryClientProvider>,
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Wybierz klienta" }));

    expect(await within(dialog).findByText("Klient nie ma zamówień w tym miesiącu.")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Dopisz NIP bez przypisywania" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(`/api/finance/sales-invoices/${UNKNOWN.id}/buyer-number`, {
        client_id: 7,
      }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(showToast).toHaveBeenCalledWith(
      "Numer dopisany do klienta. Faktury tego nabywcy (3) są już u tego klienta, z zamówieniem: 0.",
      "success",
    );
  });

  it("does not offer adding the number without assigning when the client has another one", async () => {
    get.mockImplementation(async (_url: string, config?: { params?: { client_id?: number } }) => ({
      data: config?.params?.client_id
        ? { client_id: 7, options: [], buyer_number: check({ state: "differs", existing: "2222222222" }) }
        : { client_id: null, options: [] },
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AssignInvoiceDialog invoice={UNKNOWN} fallbackPeriod="2026-10" onClose={vi.fn()} />
      </QueryClientProvider>,
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Wybierz klienta" }));

    expect(await within(dialog).findByText("Klient nie ma zamówień w tym miesiącu.")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /Dopisz/ })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Przypisz" })).toBeDisabled();
  });

  it("does not ask for a client when the invoice already has one", async () => {
    mockOptions(check({ state: "same" }));
    const { dialog } = await openAndPick({ ...UNKNOWN, client_id: 7, client_name: "Klient Fikcyjny" });

    expect(within(dialog).queryByRole("button", { name: "Wybierz klienta" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Przypisz" })).toBeInTheDocument();
  });

  it("shows a failed order fetch as an error, not as a client without orders", async () => {
    get.mockRejectedValue(new Error("boom"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <AssignInvoiceDialog invoice={UNKNOWN} fallbackPeriod="2026-10" onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Nie udało się wczytać zamówień.")).toBeInTheDocument();
    expect(screen.queryByText(/nie ma zamówień/)).not.toBeInTheDocument();
  });
});
