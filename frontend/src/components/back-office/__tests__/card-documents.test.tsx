import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: vi.fn(), showSuccess: vi.fn(), showError: vi.fn() }),
}));

import { CardDocuments } from "@/components/back-office/CardDocuments";
import type { StaffDocument } from "@/lib/api/portal-staff";

function document_(fields: Partial<StaffDocument> = {}): StaffDocument {
  return {
    id: 7,
    kind: "invoice",
    status: "received",
    file_name: "Faktura_FV1_11_2026.pdf",
    channel: "mailbox",
    created_at: "2026-11-20T10:00:00+00:00",
    reject_reason: null,
    contract_id: null,
    period_year: 2026,
    period_month: 11,
    period_guessed: false,
    sender_email: "nadawca@example.com",
    invoice_signal_at: null,
    ...fields,
  };
}

function show(row: StaffDocument) {
  get.mockResolvedValue({ data: { items: [row] } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CardDocuments cardId={1} />
    </QueryClientProvider>,
  );
}

const month = () => screen.queryByRole("combobox", { name: "Miesiąc usługi" });

async function assignTo(contract: string) {
  await userEvent.type(screen.getByRole("textbox", { name: "Numer kontraktu" }), contract);
  await userEvent.click(screen.getByRole("button", { name: "Przypisz" }));
}

describe("Przypisz: miesiąc faktury z poczty (26.11.2026)", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-26T12:00:00Z") });
    post.mockResolvedValue({ data: document_() });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("domyślnie pokazuje miesiąc z czytnika i niczego o nim nie wysyła", async () => {
    show(document_());
    expect(await screen.findByRole("textbox", { name: "Numer kontraktu" })).toBeInTheDocument();
    expect(month()).toHaveValue("2026-11");

    await assignTo("512");

    expect(post).toHaveBeenCalledWith("/api/back-office/portal/documents/7/assign", { contract_id: 512 });
  });

  it("wybrany miesiąc usługi idzie razem z numerem kontraktu", async () => {
    show(document_());
    await screen.findByRole("textbox", { name: "Numer kontraktu" });

    await userEvent.selectOptions(month()!, "październik 2026");
    await assignTo("512");

    expect(post).toHaveBeenCalledWith("/api/back-office/portal/documents/7/assign", {
      contract_id: 512,
      period_year: 2026,
      period_month: 10,
    });
  });

  it("daje dwa lata wstecz do bieżącego miesiąca i miesiąc faktury spoza zakresu", async () => {
    show(document_({ period_year: 2027, period_month: 1 }));
    await screen.findByRole("textbox", { name: "Numer kontraktu" });

    const values = Array.from((month() as HTMLSelectElement).options, (option) => option.value);
    expect(values.slice(0, 3)).toEqual(["2027-01", "2026-11", "2026-10"]);
    expect(values.at(-1)).toBe("2024-11");
    expect(values).toHaveLength(26);
    expect(month()).toHaveValue("2027-01");
  });

  it("raport też ma wybór miesiąca, od którego policzy się rozliczenie", async () => {
    show(document_({ kind: "report", file_name: "TS_raport.pdf", period_guessed: true }));
    await screen.findByRole("textbox", { name: "Numer kontraktu" });

    expect(screen.getByText(/okres nie z nazwy pliku: sprawdź/)).toBeInTheDocument();
    expect(screen.getByText(/Rozliczenie policzy się za ten miesiąc/)).toBeInTheDocument();
    await userEvent.selectOptions(month()!, "wrzesień 2026");
    await assignTo("512");

    expect(post).toHaveBeenCalledWith("/api/back-office/portal/documents/7/assign", {
      contract_id: 512,
      period_year: 2026,
      period_month: 9,
    });
  });

  it("faktura z kontraktem ma tylko decyzję, bez wyboru miesiąca", async () => {
    show(document_({ contract_id: 512 }));
    expect(await screen.findByRole("button", { name: "Przyjmij fakturę" })).toBeInTheDocument();
    expect(month()).not.toBeInTheDocument();
  });
});
