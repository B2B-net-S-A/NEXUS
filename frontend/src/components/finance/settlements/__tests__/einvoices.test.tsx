import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EinvoiceList, EinvoiceRow } from "@/lib/api/client-einvoices";

import { EinvoicesView } from "../EinvoicesView";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  download: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, put: vi.fn() } }));
vi.mock("@/lib/authenticated-files", () => ({ downloadBlob: mocks.download }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: mocks.success, showError: mocks.error }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, askReason: vi.fn(), confirmDialog: null }),
}));

function row(id: number, patch: Partial<EinvoiceRow>): EinvoiceRow {
  return {
    id,
    invoice_id: id,
    invoice_number: `${id}/11/2026/UE`,
    ksef_number: "9876543210-20261106-0A0B0C0D0E0F-11",
    kind: "original",
    issue_date: "2026-11-06",
    period: "2026-10",
    buyer_name: "Nordea Bank Abp",
    receiver_name: "Nordea Bank Abp",
    currency: "PLN",
    gross_amount: "36679.50",
    status: "ready",
    status_label: "Do wysłania",
    document_type: "invoice",
    problems: [],
    delivery_detail: null,
    target: null,
    recipient: null,
    sent_at: null,
    delivered_at: null,
    tested_at: null,
    history: [],
    ...patch,
  };
}

const base: EinvoiceList = {
  mode: "test",
  auto_send: false,
  provider: "simulate",
  provider_ready: true,
  provider_detail: null,
  counts: { ready: 2, invalid: 1, delivered: 1 },
  rows: [
    row(1, {}),
    row(2, { currency: "EUR", gross_amount: "5674.50" }),
    row(3, {
      status: "invalid",
      status_label: "Błąd walidacji",
      problems: [{ rule: "BR-AE-10", flag: "fatal", text: "Brak kodu zwolnienia", location: "/Invoice" }],
    }),
    row(4, {
      status: "delivered",
      status_label: "Doręczona",
      target: "test",
      recipient: "0088:7332545042126",
      sent_at: "2026-11-13T10:00:00Z",
    }),
  ],
};

function renderView(data: EinvoiceList, canWrite = true) {
  mocks.get.mockResolvedValue({ data });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EinvoicesView clientId={7} month="2026-10" canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

describe("E-faktury Peppol (Nordea N2)", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
  });

  it("pokazuje stan, powód błędu walidacji i adres wysyłki testowej", async () => {
    renderView(base);

    expect(await screen.findByText("Tryb testowy")).toBeInTheDocument();
    expect(screen.getByText(/BR-AE-10: Brak kodu zwolnienia/)).toBeInTheDocument();
    expect(screen.getByText("0088:7332545042126")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Wyślij" })).toHaveLength(2);
    expect(screen.queryByLabelText("Zaznacz 3/11/2026/UE")).not.toBeInTheDocument();
  });

  it("„Zaznacz wszystkie” bierze tylko faktury do wysłania i wysyła je po potwierdzeniu", async () => {
    mocks.confirm.mockResolvedValue(true);
    mocks.post.mockResolvedValue({ data: { sent: 2, failed: [], mode: "test" } });
    renderView(base);

    fireEvent.click(await screen.findByLabelText("Zaznacz wszystkie do wysłania"));
    fireEvent.click(screen.getByRole("button", { name: /Wyślij zaznaczone \(2\)/ }));

    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/einvoices/send", { ids: [1, 2] }));
    expect(mocks.confirm.mock.calls[0][0].description).toMatch(/adres testowy/);
    await waitFor(() => expect(mocks.success).toHaveBeenCalledWith("Wysłano 2 e-faktur na adres testowy."));
  });

  it("produkcja pyta mocniej, a anulowanie nic nie wysyła", async () => {
    mocks.confirm.mockResolvedValue(false);
    renderView({ ...base, mode: "production" });

    const first = (await screen.findByText("1/11/2026/UE")).closest("tr") as HTMLElement;
    fireEvent.click(within(first).getByRole("button", { name: "Wyślij" }));

    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    expect(mocks.confirm.mock.calls[0][0].variant).toBe("destructive");
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("bez dostawcy przyciski wysyłki są wyłączone i widać powód", async () => {
    renderView({ ...base, provider: "off", provider_ready: false, provider_detail: "Wysyłka e-faktur jest wyłączona (brak dostawcy Peppol)." });

    expect(await screen.findByText(/brak dostawcy Peppol/)).toBeInTheDocument();
    screen.getAllByRole("button", { name: "Wyślij" }).forEach((button) => expect(button).toBeDisabled());
  });

  it("bez prawa zapisu nie ma wysyłki ani ustawień", async () => {
    renderView(base, false);

    expect(await screen.findByText("1/11/2026/UE")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wyślij" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ustawienia/ })).not.toBeInTheDocument();
  });

  it("awaria zapytania nie wygląda jak pusta lista", async () => {
    mocks.get.mockRejectedValue(new Error("500"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <EinvoicesView clientId={7} month="2026-10" canWrite />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/Nie udało się pobrać e-faktur/)).toBeInTheDocument();
    expect(screen.queryByText(/nie ma faktur do odbiorców/)).not.toBeInTheDocument();
  });
});

describe("Filtr stanu", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
  });

  it("licznik filtruje wiersze, a aktywny filtr da się zdjąć, nawet gdy stan zniknie", async () => {
    mocks.get.mockResolvedValue({ data: base });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <EinvoicesView clientId={7} month="2026-10" canWrite />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /Doręczona: 1/ }));
    expect(screen.queryByText("1/11/2026/UE")).not.toBeInTheDocument();
    expect(screen.getByText("4/11/2026/UE")).toBeInTheDocument();

    // Po przełączeniu na produkcję wysłane testowo wracają do „Do wysłania”.
    mocks.get.mockResolvedValue({
      data: { ...base, counts: { ready: 3, invalid: 1 }, rows: base.rows.map((r) => (r.id === 4 ? { ...r, status: "ready" } : r)) },
    });
    await client.invalidateQueries();
    const chip = await screen.findByRole("button", { name: /Doręczona: 0/ });
    expect(chip).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(chip);
    expect(await screen.findByText("1/11/2026/UE")).toBeInTheDocument();
  });

  it("niepewna wysyłka pokazuje powód i ostrzega przy ponownym wysłaniu", async () => {
    mocks.confirm.mockResolvedValue(false);
    renderView({
      ...base,
      counts: { sending: 1 },
      rows: [
        row(9, {
          status: "sending",
          status_label: "Wysyłka niepewna",
          delivery_detail: "Brak odpowiedzi dostawcy Peppol. Sprawdź w panelu dostawcy, czy dokument wyszedł, przed ponowną wysyłką.",
        }),
      ],
    });

    expect(await screen.findByText(/Sprawdź w panelu dostawcy/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Wyślij" }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    expect(mocks.confirm.mock.calls[0][0].description).toMatch(/niepewną poprzednią wysyłkę/);
  });
});
