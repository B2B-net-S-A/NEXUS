import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const showToast = vi.fn();
const askReason = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    patch: (...a: unknown[]) => patch(...a),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askReason, askConfirm: vi.fn(), confirmDialog: null }),
}));
// Panele obok karty mają własne testy — tu sprawdzamy tylko, co dostają.
vi.mock("@/components/finance/ledger/CostPaymentPanel", () => ({
  CostPaymentPanel: ({ entryId, readOnly }: { entryId: number; readOnly: boolean }) => (
    <div data-testid="payment-panel" data-entry={entryId} data-readonly={String(readOnly)} />
  ),
}));
vi.mock("@/components/finance/ledger/DecreePanel", () => ({
  DecreePanel: ({ readOnly }: { readOnly: boolean }) => (
    <div data-testid="decree-panel" data-readonly={String(readOnly)} />
  ),
}));
vi.mock("@/components/finance/ledger/CostPdfButton", () => ({
  CostPdfButton: () => <button type="button">Pobierz PDF</button>,
}));
vi.mock("@/components/finance/ledger/CostsTab", () => ({
  Concerning: ({ row }: { row: { concerning: { label: string } | null } }) => (
    <span>{row.concerning?.label ?? "—"}</span>
  ),
}));

import { CostCard } from "@/components/finance/ledger/CostCard";
import type { CostCard as CostCardData } from "@/lib/api/finance-ledger";
import { useAuthStore } from "@/store/auth";

function text(el: Element | null): string {
  return (el?.textContent ?? "").replace(/[  ]/g, " ");
}

const CARD: CostCardData = {
  id: 42,
  source_type: "contractor_invoice",
  source_id: 9,
  from_ksef: true,
  stage: "new",
  stage_label: "Do opisu",
  flags: [],
  category: "contractor",
  category_label: "Kontraktorzy",
  journal: "contractors",
  journal_label: "Kontraktorzy",
  received_at: "2026-11-02T23:30:00Z",
  seller_name: "Firma Testowa sp. z o.o.",
  seller_nip: "0000000000",
  invoice_number: "FV/11/2026/1",
  ksef_number: "KSEF-TEST-1",
  issue_date: "2026-11-01",
  currency: "PLN",
  net_amount: "10000.00",
  vat_amount: "2300.00",
  gross_amount: "12300.00",
  due_date: "2026-11-15",
  due_date_set: true,
  counterparty_id: 5,
  counterparty_name: "Firma Testowa sp. z o.o.",
  cost_account: "402-203",
  concerning: { kind: "contractor", person: "Jan Testowy", label: "Jan Testowy", status: null, status_label: null },
  own: false,
  reject_reason: null,
  note: null,
  payment: null,
  can: { verify: true, ready: true },
  settlement: null,
  source_label: "Faktura kontraktora",
  symfonia_partner_id: "SYM-1",
  stage_changed_at: null,
  history: [],
  decree: null as unknown as CostCardData["decree"],
};

let client: QueryClient;

function renderCard(data: Partial<CostCardData> | Error) {
  if (data instanceof Error) get.mockRejectedValue(data);
  else get.mockResolvedValue({ data: { ...CARD, ...data } });
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CostCard id={42} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  showToast.mockReset();
  askReason.mockReset();
  useAuthStore.setState({ realUser: null });
});

afterEach(() => {
  useAuthStore.setState({ realUser: null });
});

describe("CostCard — odczyt", () => {
  it("pokazuje netto, VAT i brutto z walutą oraz dzień wpływu w kalendarzu Warszawy", async () => {
    renderCard({});
    await screen.findByRole("heading", { name: "FV/11/2026/1" });
    expect(get).toHaveBeenCalledWith("/api/finance/costs/42");
    const body = text(document.body);
    expect(body).toContain("10 000,00 zł");
    expect(body).toContain("2300,00 zł");
    expect(body).toContain("12 300,00 zł");
    // 23:30 UTC 2 listopada to już 3 listopada w Warszawie.
    expect(body).toContain("03.11.2026");
    expect(body).toContain("Dziennik: Kontraktorzy");
    expect(screen.getByRole("link", { name: "← Koszty" })).toHaveAttribute(
      "href",
      "/finance?view=costs&costStage=new",
    );
  });

  it("faktura w walucie obcej i bez kwot: kod ISO i „—”, nigdy „0 zł”", async () => {
    renderCard({ currency: "EUR", net_amount: "250", vat_amount: null, gross_amount: null, invoice_number: null });
    await screen.findByRole("heading", { name: "Faktura #42" });
    const body = text(document.body);
    expect(body).toContain("250,00 EUR");
    expect(body).not.toContain("0,00 zł");
  });

  it("etapy: z KSeF jest pięć kroków z bieżącym oznaczonym, z PDF-u cztery", async () => {
    renderCard({});
    const steps = await screen.findByRole("list", { name: "Etap faktury" });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(5);
    expect(within(steps).getByText("Do opisu")).toHaveAttribute("aria-current", "step");
  });

  it("faktura z PDF-u: bez kroku poczekalni KSeF i bez „Cofnij do poczekalni”", async () => {
    renderCard({ from_ksef: false });
    const steps = await screen.findByRole("list", { name: "Etap faktury" });
    expect(within(steps).getAllByRole("listitem")).toHaveLength(4);
    expect(screen.queryByRole("button", { name: "Cofnij do poczekalni" })).not.toBeInTheDocument();
    expect(screen.getByText("PDF")).toBeInTheDocument();
  });

  it("odrzucona: powód zamiast kroków, link wstecz z etapem", async () => {
    renderCard({ stage: "rejected", stage_label: "Odrzucona", reject_reason: "duplikat faktury" });
    await screen.findByText("Odrzucona: duplikat faktury");
    expect(screen.queryByRole("list", { name: "Etap faktury" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Przywróć" })).toBeInTheDocument();
  });

  it("poczekalnia KSeF: link wstecz bez parametru etapu", async () => {
    renderCard({ stage: "received", stage_label: "Z KSeF do przyjęcia" });
    await screen.findByRole("button", { name: "Przyjmij" });
    expect(screen.getByRole("link", { name: "← Koszty" })).toHaveAttribute("href", "/finance?view=costs");
  });

  it("brak kontrahenta w kartotece kieruje do „Kontrahenci”", async () => {
    renderCard({ counterparty_id: null });
    await screen.findByText(/NIP-u sprzedawcy nie ma w kartotece/);
    expect(screen.getByRole("link", { name: "Kontrahenci" })).toHaveAttribute(
      "href",
      "/finance?view=counterparties",
    );
  });

  it("rozliczenie miesiąca: kwota z RCP, kontrole z plakietkami i link do klienta", async () => {
    renderCard({
      settlement: {
        state: "differs",
        label: "Kwota różni się od RCP",
        tone: "warn",
        month: "2026-10",
        rcp: "168 h",
        client_id: 3,
        amount_cost: "16800.00",
        checks: [
          { state: "ok", title: "NIP nabywcy zgodny" },
          { state: "fail", title: "Kwota z RCP", detail: "Różnica 100,00 zł" },
          { state: "warn", title: "Termin krótszy niż w umowie" },
        ],
        payment: { state: "none", title: "Bramka zapłaty", can_pay: false },
      },
    });
    await screen.findByText("Rozliczenie miesiąca 2026-10");
    expect(text(document.body)).toContain("wyliczenie z RCP 16 800,00 zł netto");
    expect(screen.getByText("OK")).toBeInTheDocument();
    expect(screen.getByText("Błąd")).toBeInTheDocument();
    expect(screen.getByText("Uwaga")).toBeInTheDocument();
    expect(screen.getByText("Info")).toBeInTheDocument();
    expect(screen.getByText("Różnica 100,00 zł")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Faktury i rozliczenie klienta" })).toHaveAttribute(
      "href",
      "/clients/3?tab=faktury",
    );
  });

  it("rozliczenie bez miesiąca i klienta: ogólny tytuł, bez linku", async () => {
    renderCard({ settlement: { state: "missing", label: "Brak rozliczenia", tone: "none" } });
    await screen.findByText("Rozliczenie miesiąca");
    expect(screen.queryByRole("link", { name: "Faktury i rozliczenie klienta" })).not.toBeInTheDocument();
  });

  it("historia: opisy zdarzeń, flag, kategorii i terminu", async () => {
    renderCard({
      history: [
        { at: "2026-11-03T08:00:00Z", action: "decree", action_label: "Dekret", from_stage: null, to_stage: null, to_stage_label: null, detail: { manual: true }, actor: "Anna Przykładowa" },
        { at: "2026-11-03T08:01:00Z", action: "decree", action_label: "Dekret", from_stage: null, to_stage: null, to_stage_label: null, detail: {}, actor: null },
        { at: "2026-11-03T08:02:00Z", action: "export", action_label: "Eksport", from_stage: null, to_stage: null, to_stage_label: null, detail: { batch: "P-7" }, actor: null },
        { at: "2026-11-03T08:03:00Z", action: "unexport", action_label: "Anulowanie", from_stage: null, to_stage: null, to_stage_label: null, detail: { batch: "P-7" }, actor: null },
        { at: "2026-11-03T08:04:00Z", action: "book", action_label: "Księgowanie", from_stage: null, to_stage: null, to_stage_label: null, detail: {}, actor: null },
        { at: "2026-11-03T08:05:00Z", action: "reject", action_label: "Odrzucenie", from_stage: null, to_stage: null, to_stage_label: null, detail: { reason: "zła kwota" }, actor: null },
        { at: "2026-11-03T08:06:00Z", action: "back", action_label: "Cofnięcie", from_stage: "verified", to_stage: "new", to_stage_label: "Do opisu", detail: {}, actor: null },
        { at: "2026-11-03T08:07:00Z", action: "verify", action_label: "Zweryfikowana", from_stage: "new", to_stage: "verified", to_stage_label: "Zweryfikowana", detail: {}, actor: null },
        { at: "2026-11-03T08:08:00Z", action: "flags", action_label: "Flagi", from_stage: null, to_stage: null, to_stage_label: null, detail: { to: ["mpp", "hold_payment"] }, actor: null },
        { at: "2026-11-03T08:09:00Z", action: "flags", action_label: "Flagi", from_stage: null, to_stage: null, to_stage_label: null, detail: { to: [] }, actor: null },
        { at: "2026-11-03T08:10:00Z", action: "category", action_label: "Kategoria", from_stage: null, to_stage: null, to_stage_label: null, detail: { to: "office", folder: "Biuro 2026" }, actor: null },
        { at: "2026-11-03T08:11:00Z", action: "category", action_label: "Kategoria", from_stage: null, to_stage: null, to_stage_label: null, detail: {}, actor: null },
        { at: "2026-11-03T08:12:00Z", action: "due_date", action_label: "Termin", from_stage: null, to_stage: null, to_stage_label: null, detail: { to: "2026-12-01" }, actor: null },
        { at: "2026-11-03T08:13:00Z", action: "due_date", action_label: "Termin", from_stage: null, to_stage: null, to_stage_label: null, detail: { to: null }, actor: null },
        { at: "2026-11-03T08:14:00Z", action: "note", action_label: "Notatka zmieniona", from_stage: null, to_stage: null, to_stage_label: null, detail: {}, actor: null },
      ],
    });
    await screen.findByText(/Dekret poprawiony ręcznie/);
    for (const line of [
      "Dekret przeliczony z reguły",
      "W paczce eksportu P-7",
      "Paczka P-7 anulowana",
      "Zaksięgowana (paczka —)",
      "Odrzucona: zła kwota",
      "Cofnięta do „Do opisu”",
      "Flagi: MPP, Wstrzymać płatność",
      "Flagi: bez flag",
      "Kategoria: Biuro (folder eBI24 „Biuro 2026”)",
      "Kategoria: —",
      "Termin płatności: 01.12.2026",
      "Termin płatności: usunięty",
      "Notatka zmieniona",
    ]) {
      expect(text(document.body)).toContain(line);
    }
    expect(text(document.body)).toContain("· Anna Przykładowa");
    expect(text(document.body)).toContain("wpłynęła z KSeF");
  });

  it("awaria odczytu to komunikat błędu, nie pusta karta", async () => {
    renderCard(new Error("503"));
    expect(await screen.findByRole("button", { name: /spróbuj ponownie/i })).toBeInTheDocument();
    expect(screen.queryByText("Faktura")).not.toBeInTheDocument();
  });

  it("dekret pokazuje się tylko, gdy przyszedł z API", async () => {
    renderCard({ decree: { computed: true } as unknown as CostCardData["decree"] });
    expect(await screen.findByTestId("decree-panel")).toHaveAttribute("data-readonly", "false");
    expect(screen.getByTestId("payment-panel")).toHaveAttribute("data-entry", "42");
  });
});

describe("CostCard — uprawnienia", () => {
  it("własna faktura: komunikat, bez przycisków etapu, opis zablokowany", async () => {
    renderCard({ own: true, decree: { computed: true } as unknown as CostCardData["decree"] });
    await screen.findByText(/To Twoja faktura/);
    expect(screen.queryByRole("button", { name: "Zweryfikuj" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Kategoria")).toBeDisabled();
    expect(screen.getByLabelText("Termin płatności")).toBeDisabled();
    expect(screen.getByRole("button", { name: "MPP" })).toBeDisabled();
    expect(screen.getByTestId("decree-panel")).toHaveAttribute("data-readonly", "true");
  });

  it("podgląd jako inna osoba: tylko odczyt, także płatność", async () => {
    useAuthStore.setState({ realUser: { id: 1 } as never });
    renderCard({});
    await screen.findByRole("heading", { name: "FV/11/2026/1" });
    expect(screen.queryByRole("button", { name: "Zweryfikuj" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Kategoria")).toBeDisabled();
    expect(screen.getByTestId("payment-panel")).toHaveAttribute("data-readonly", "true");
  });

  it("bez prawa weryfikacji „Zweryfikuj” jest wyłączone z podpowiedzią", async () => {
    renderCard({ can: { verify: false, ready: true } });
    const button = await screen.findByRole("button", { name: "Zweryfikuj" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title");
    expect(screen.getByRole("button", { name: "Odrzuć" })).toBeEnabled();
  });

  it("zaksięgowana: bez przycisków etapu; kategoria i notatka zamknięte, flagi płatności dalej wolno", async () => {
    renderCard({ stage: "booked", stage_label: "Zaksięgowana" });
    await screen.findByRole("heading", { name: "FV/11/2026/1" });
    expect(screen.queryByRole("button", { name: "Cofnij o krok" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Kategoria")).toBeDisabled();
    expect(screen.getByLabelText("Notatka")).toBeDisabled();
    expect(screen.getByLabelText("Termin płatności")).toBeEnabled();
    expect(screen.getByRole("button", { name: "MPP" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Zapłata na konto US" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Duplikat" })).toBeDisabled();
  });

  it("gotowa do księgowania: kategoria zamknięta z podpowiedzią „najpierw Cofnij”", async () => {
    renderCard({ stage: "ready", stage_label: "Gotowa do księgowania" });
    const select = await screen.findByLabelText("Kategoria");
    expect(select).toBeDisabled();
    expect(select).toHaveAttribute("title", expect.stringContaining("najpierw Cofnij"));
  });
});

describe("CostCard — zapis", () => {
  it("zmiana etapu wysyła id faktury i akcję", async () => {
    const user = userEvent.setup();
    post.mockResolvedValue({ data: { changed: 1, refused: [] } });
    renderCard({});
    await user.click(await screen.findByRole("button", { name: "Zweryfikuj" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/costs/actions", {
        ids: [42],
        action: "verify",
        reason: undefined,
      }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zapisano.", "success"));
  });

  it("odrzucenie pyta o powód przez useConfirmV2 i wysyła go", async () => {
    const user = userEvent.setup();
    askReason.mockResolvedValue("faktura nie dotyczy firmy");
    post.mockResolvedValue({ data: { changed: 1, refused: [] } });
    renderCard({});
    await user.click(await screen.findByRole("button", { name: "Odrzuć" }));
    expect(askReason).toHaveBeenCalledWith(expect.objectContaining({ title: "Odrzucić fakturę?", variant: "destructive" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/finance/costs/actions", {
        ids: [42],
        action: "reject",
        reason: "faktura nie dotyczy firmy",
      }),
    );
  });

  it("anulowane pytanie o powód nie wysyła nic", async () => {
    const user = userEvent.setup();
    askReason.mockResolvedValue(null);
    renderCard({});
    await user.click(await screen.findByRole("button", { name: "Odrzuć" }));
    await waitFor(() => expect(askReason).toHaveBeenCalled());
    expect(post).not.toHaveBeenCalled();
  });

  it("błąd zmiany etapu idzie toastem", async () => {
    const user = userEvent.setup();
    post.mockRejectedValue(new Error("boom"));
    renderCard({});
    await user.click(await screen.findByRole("button", { name: "Zweryfikuj" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.any(String), "error"));
  });

  it("MPP i NIE MPP wykluczają się: włączenie MPP zdejmuje NIE MPP", async () => {
    const user = userEvent.setup();
    patch.mockResolvedValue({ data: { ...CARD, flags: ["mpp"] } });
    renderCard({ flags: ["no_mpp", "duplicate"] });
    expect(await screen.findByRole("button", { name: "NIE MPP" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "MPP" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/finance/costs/42", { flags: ["duplicate", "mpp"] }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Flagi zapisane.", "success"));
  });

  it("włączenie NIE MPP zdejmuje MPP, wyłączenie flagi ją usuwa", async () => {
    const user = userEvent.setup();
    patch.mockResolvedValue({ data: CARD });
    renderCard({ flags: ["mpp", "hold_payment"] });
    await user.click(await screen.findByRole("button", { name: "NIE MPP" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/finance/costs/42", { flags: ["hold_payment", "no_mpp"] }),
    );
  });

  it("wyłączenie włączonej flagi usuwa ją z listy", async () => {
    const user = userEvent.setup();
    patch.mockResolvedValue({ data: CARD });
    renderCard({ flags: ["mpp", "hold_payment"] });
    await user.click(await screen.findByRole("button", { name: "Wstrzymać płatność" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/api/finance/costs/42", { flags: ["mpp"] }));
  });

  it("kategoria i termin zapisują się od razu; wyczyszczony termin to null", async () => {
    const user = userEvent.setup();
    patch.mockResolvedValue({ data: CARD });
    renderCard({});
    await user.selectOptions(await screen.findByLabelText("Kategoria"), "office");
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/api/finance/costs/42", { category: "office" }));
    await user.clear(screen.getByLabelText("Termin płatności"));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/api/finance/costs/42", { due_date: null }));
  });

  it("termin z rozliczenia osoby (nieustawiony ręcznie) jest tylko podpowiedzią", async () => {
    renderCard({ due_date_set: false, due_date: "2026-11-20" });
    await screen.findByText("Termin z rozliczenia osoby: 20.11.2026.");
    expect(screen.getByLabelText("Termin płatności")).toHaveValue("");
  });

  it("notatka: przycisk dopiero po zmianie, pusta notatka zapisuje null, błąd idzie toastem", async () => {
    const user = userEvent.setup();
    patch.mockRejectedValueOnce(new Error("boom")).mockResolvedValue({ data: CARD });
    renderCard({ note: "do sprawdzenia" });
    const note = await screen.findByLabelText("Notatka");
    expect(screen.queryByRole("button", { name: "Zapisz notatkę" })).not.toBeInTheDocument();
    await user.clear(note);
    await user.type(note, "   ");
    await user.click(screen.getByRole("button", { name: "Zapisz notatkę" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/api/finance/costs/42", { note: null }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.any(String), "error"));
  });
});
