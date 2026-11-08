import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";

import { EditClientModal } from "@/components/AppShell";
import api from "@/lib/api";

vi.mock("@/lib/api", () => {
  const client = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  };
  return {
  default: client,
  api: client,
  phase5Api: { clientsLookup: vi.fn() },
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
  };
});

/**
 * Kontrakt zapisu nazwy klienta (ticket #1 bug 4): edycja pisze do
 * sync-odpornego `display_name` (Traffit nadpisuje `name` codziennie),
 * i TYLKO gdy pole faktycznie zmieniono — bezwarunkowy zapis zamroziłby
 * nazwę względem Traffita przy każdej edycji np. branży.
 */

// GET zwraca nazwę EFEKTYWNĄ w `name` (coalesce(display_name, name)).
const CLIENT = {
  id: 42,
  name: "Acme Sp. z o.o.",
  industry: "IT",
  website: null,
  address: null,
  status: "active",
  nda_signed: false,
  contract_type: null,
  notes: null,
};

function renderModal(client: Record<string, unknown> = CLIENT) {
  const queries = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queries}>
      <EditClientModal client={client} onClose={() => {}} onSuccess={() => {}} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);
  vi.mocked(api.get).mockResolvedValue({
    data: {
      number: "1111111111",
      invoices: 0,
      totals: [],
      first_date: null,
      last_date: null,
      buyer_name: null,
    },
  } as never);
});

describe("EditClientModal — NIP i nazwa prawna", () => {
  const WITH_LEGAL = { ...CLIENT, nip: "1111111111", legal_name: "Acme Spółka" };

  it("does not send legal fields when untouched", async () => {
    const user = userEvent.setup();
    renderModal(WITH_LEGAL);
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    const body = vi.mocked(api.patch).mock.calls[0][1] as Record<string, unknown>;
    expect(body).not.toHaveProperty("nip");
    expect(body).not.toHaveProperty("legal_name");
  });

  it("sends a changed NIP without separators", async () => {
    const user = userEvent.setup();
    renderModal(WITH_LEGAL);
    const nip = screen.getByPlaceholderText(/FI12345678/);
    await user.clear(nip);
    await user.type(nip, "222-222-22-22");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    const body = vi.mocked(api.patch).mock.calls[0][1] as Record<string, unknown>;
    expect(body.nip).toBe("2222222222");
  });

  it("blocks a bad checksum without sending the form", async () => {
    const user = userEvent.setup();
    renderModal(WITH_LEGAL);
    const nip = screen.getByPlaceholderText(/FI12345678/);
    await user.clear(nip);
    await user.type(nip, "1111111112");
    expect(screen.getByRole("alert")).toHaveTextContent("niepoprawną sumę kontrolną");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    expect(api.patch).not.toHaveBeenCalled();
  });

  it("hides the fields when the account cannot read legal data", () => {
    const { notes: _notes, ...withoutLegal } = CLIENT;
    renderModal(withoutLegal);
    expect(screen.queryByText("NIP")).not.toBeInTheDocument();
  });

  it("shows the KSeF frame for a valid number with waiting invoices", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        number: "1111111111",
        invoices: 13,
        totals: [{ currency: "PLN", amount: "301269.00" }],
        first_date: "2026-08-07",
        last_date: "2026-10-13",
        buyer_name: "ACME SPÓŁKA",
      },
    } as never);
    renderModal(WITH_LEGAL);
    expect(await screen.findByText(/13 faktur z KSeF czeka na ten NIP/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith(
      "/api/clients/42/invoicing/waiting-for-number",
      { params: { number: "1111111111" } },
    );
  });

  it("stays quiet when the frame request is refused", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("403"));
    renderModal(WITH_LEGAL);
    await waitFor(() => expect(api.get).toHaveBeenCalled());
    expect(screen.queryByText(/czeka na ten NIP/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zapisz zmiany" })).toBeEnabled();
  });
});

describe("EditClientModal — display_name contract", () => {
  it("does not send name nor display_name when the name field is untouched", async () => {
    const user = userEvent.setup();
    renderModal();

    // Zmiana INNEGO pola (branża) — nazwa nietknięta.
    const industry = screen.getByPlaceholderText("IT / Finance...");
    await user.clear(industry);
    await user.type(industry, "Fintech");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(api.patch).mock.calls[0][1] as Record<
      string,
      unknown
    >;
    expect(payload.industry).toBe("Fintech");
    // `name` nigdy nie jest wysyłane; `display_name` tylko przy zmianie.
    expect("name" in payload).toBe(false);
    expect("display_name" in payload).toBe(false);
  });

  it("sends the edited name as display_name (never as name)", async () => {
    const user = userEvent.setup();
    renderModal();

    const nameInput = screen.getByPlaceholderText("Acme Sp. z o.o.");
    await user.clear(nameInput);
    await user.type(nameInput, "Nordea Bank Abp");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith(
      "/api/clients/42",
      expect.objectContaining({ display_name: "Nordea Bank Abp" }),
    );
    const payload = vi.mocked(api.patch).mock.calls[0][1] as Record<
      string,
      unknown
    >;
    expect("name" in payload).toBe(false);
  });

  it("sends display_name: null when the name field is cleared (revert to source)", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.clear(screen.getByPlaceholderText("Acme Sp. z o.o."));
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith(
      "/api/clients/42",
      expect.objectContaining({ display_name: null }),
    );
  });
});

/**
 * Notatki klienta idą razem z danymi prawnymi (uprawnienie „Stawki i kwoty:
 * podgląd”). Konto bez niego dostaje klienta BEZ pola `notes`, a formularz
 * wysyłał `notes: null` przy każdym zapisie — edycja branży kasowała cudzy wpis.
 */
describe("EditClientModal — notatki", () => {
  async function saveIndustry() {
    const user = userEvent.setup();
    const industry = screen.getByPlaceholderText("IT / Finance...");
    await user.clear(industry);
    await user.type(industry, "Fintech");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    return vi.mocked(api.patch).mock.calls[0][1] as Record<string, unknown>;
  }

  it("konto bez danych prawnych nie widzi pola i nie wysyła notatek", async () => {
    const { notes: _hidden, ...withoutLegal } = CLIENT;
    renderModal(withoutLegal);

    expect(screen.queryByPlaceholderText("Dodatkowe informacje...")).toBeNull();
    const payload = await saveIndustry();
    expect("notes" in payload).toBe(false);
  });

  it("nietknięte notatki nie jadą w zapisie innego pola", async () => {
    renderModal({ ...CLIENT, notes: "Faktury do 10. dnia miesiąca" });

    const payload = await saveIndustry();
    expect("notes" in payload).toBe(false);
  });

  it("zmienione notatki są wysyłane, a wyczyszczone zapisują null", async () => {
    const user = userEvent.setup();
    renderModal({ ...CLIENT, notes: "Stara notatka" });

    await user.clear(screen.getByPlaceholderText("Dodatkowe informacje..."));
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));

    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith(
      "/api/clients/42",
      expect.objectContaining({ notes: null }),
    );
  });
});
