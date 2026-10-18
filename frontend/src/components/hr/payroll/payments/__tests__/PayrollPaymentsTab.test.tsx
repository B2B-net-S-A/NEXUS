import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FinanceList, StatementOverview, UnmatchedLine } from "@/lib/api/hr-payments";

import { payableRow } from "./payments-fixtures";

const FULL_ACCOUNT = "53999900020000000000004521";
const state: {
  finance: Record<string, unknown>;
  statements: Record<string, unknown>;
} = { finance: {}, statements: {} };
const download = vi.fn(async (..._args: unknown[]) => undefined);
const importMutate = vi.fn();

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/lib/api/hr", () => ({ downloadHrFile: (...args: unknown[]) => download(...args) }));
vi.mock("@/components/ui/select", () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/lib/api/hr-payments", () => {
  const mutation = () => ({ mutate: vi.fn(), isPending: false });
  return {
    paymentPaths: {
      financeCsv: (year: number | null, month: number | null) =>
        `/api/hr/payments/finance/export.csv${year ? `?year=${year}&month=${month}` : ""}`,
      nipList: "/api/hr/payments/nip-list.csv",
      batchFile: (key: string) => `/api/hr/payments/batches/${key}/file`,
    },
    useFinanceList: () => state.finance,
    useStatementOverview: () => state.statements,
    useBatches: () => ({ data: undefined, isError: false }),
    useImportStatement: () => ({ mutate: importMutate, isPending: false }),
    useAssignStatementLine: mutation,
    useIgnoreStatementLine: mutation,
    usePreviewBatch: mutation,
    useCreateBatch: mutation,
    useConfirmBatch: mutation,
    useCancelBatch: mutation,
  };
});

import { PayrollPaymentsTab } from "../PayrollPaymentsTab";
import { assignOptions } from "../UnmatchedLinesTable";

const mandate = payableRow({
  settlement_id: 2,
  user_id: 8,
  name: "Kuba Lato",
  employment_type: "zlecenie",
  form_label: "Zlecenie",
  amount_basis: "gross",
  amount_to_pay: null,
  expected_amount: "1856.00",
  invoices: [],
  title: "Wynagrodzenie zlecenie 10/2026",
  account_source: "manual",
  account_last4: "0937",
});

function finance(overrides: Partial<FinanceList> = {}): FinanceList {
  return {
    year: 2026,
    month: 10,
    rows: [payableRow(), mandate],
    totals_to_pay: { PLN: "21106.80" },
    stats: { payable: 2, b2b: 1, payroll_program: 1, overdue: 0, unmatched_lines: 1 },
    transfer_batch_enabled: false,
    ...overrides,
  };
}

const unmatched: UnmatchedLine = {
  id: 41,
  booked_on: "2026-11-18",
  amount: "21000.00",
  currency: "PLN",
  title: "FV 10/2026 1234563218-20261104-5F2A9C0D71B3-4E",
  reason: "Kwota przelewu inna niż do zapłaty.",
  counterparty_last4: "4521",
  format: "mt940",
  hints: [
    {
      settlement_id: 1,
      name: "Ola Nowak",
      period: "10/2026",
      employment_type: "b2b",
      to_pay: "21106.80",
      expected_amount: "17160.00",
      currency: "PLN",
    },
  ],
};

function ok<T>(data: T) {
  return { data, isLoading: false, isError: false, error: null, isSuccess: true, refetch: vi.fn() };
}

beforeEach(() => {
  download.mockClear();
  importMutate.mockClear();
  state.finance = ok(finance());
  state.statements = ok<StatementOverview>({ recent: [], unmatched: [unmatched] });
});

describe("Płace → Przelewy", () => {
  it("lista dla Finansów: brutto faktury, netto z programu i tylko 4 cyfry rachunku", () => {
    const { container } = render(<PayrollPaymentsTab year={2026} month={10} />);
    expect(screen.getByText("Dla Finansów — zatwierdzone do zapłaty")).toBeInTheDocument();
    expect(screen.getByText("Ola Nowak")).toBeInTheDocument();
    expect(screen.getAllByText(/21\s106,80\szł/).length).toBeGreaterThan(0);
    expect(screen.getByText("netto z programu płacowego")).toBeInTheDocument();
    expect(screen.getByText("•• 4521 · biała lista VAT")).toBeInTheDocument();
    expect(container.textContent).not.toContain(FULL_ACCOUNT);
    // Paczka przelewów wyłączona — zdanie zamiast przycisku.
    expect(screen.getByText(/Paczka przelewów jest wyłączona/)).toBeInTheDocument();
    expect(screen.queryByText("Pobierz paczkę do banku")).not.toBeInTheDocument();
  });

  it("operacje z wyciągu do decyzji z powodem i przyciskami", () => {
    render(<PayrollPaymentsTab year={2026} month={10} />);
    expect(screen.getByText("Z wyciągu — do decyzji (1)")).toBeInTheDocument();
    expect(screen.getByText("Kwota przelewu inna niż do zapłaty.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Przypisz" })).toBeDisabled();
  });

  it("CSV dla Finansów i lista NIP-ów pobierają pliki; zakres „Wszystkie miesiące”", async () => {
    render(<PayrollPaymentsTab year={2026} month={10} />);
    fireEvent.click(screen.getByRole("button", { name: /Eksport dla Finansów/ }));
    await vi.waitFor(() =>
      expect(download).toHaveBeenCalledWith(
        "/api/hr/payments/finance/export.csv?year=2026&month=10",
        "do-zaplaty.csv",
      ),
    );
    const nipButton = screen.getByRole("button", { name: /Lista NIP-ów dla eBI24/ });
    await vi.waitFor(() => expect(nipButton).not.toBeDisabled());
    fireEvent.click(nipButton);
    await vi.waitFor(() =>
      expect(download).toHaveBeenCalledWith("/api/hr/payments/nip-list.csv", "nip-zespolu.csv"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Wszystkie miesiące" }));
    expect(screen.getByRole("button", { name: "Wszystkie miesiące" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("awaria listy to komunikat z ponowieniem, nie pusta lista", () => {
    state.finance = {
      data: undefined,
      isLoading: false,
      isError: true,
      error: { response: { status: 500 } },
      isSuccess: false,
      refetch: vi.fn(),
    };
    render(<PayrollPaymentsTab year={2026} month={10} />);
    expect(screen.queryByText(/Nic nie czeka na zapłatę/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
  });

  it("pusta lista tylko po udanym odczycie", () => {
    state.finance = ok(finance({ rows: [], totals_to_pay: {} }));
    render(<PayrollPaymentsTab year={2026} month={10} />);
    expect(screen.getByText(/Nic nie czeka na zapłatę/)).toBeInTheDocument();
  });

  it("zły plik wyciągu zatrzymuje się przed wysłaniem", () => {
    render(<PayrollPaymentsTab year={2026} month={10} />);
    const input = screen.getByLabelText("Plik wyciągu");
    fireEvent.change(input, {
      target: { files: [new File(["x"], "wyciag.pdf", { type: "application/pdf" })] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/MT940/);
    expect(importMutate).not.toHaveBeenCalled();
    fireEvent.change(input, {
      target: { files: [new File([":20:X"], "wyciag.sta", { type: "text/plain" })] },
    });
    expect(importMutate).toHaveBeenCalledTimes(1);
  });

  it("przypisanie podpowiada najpierw rozliczenia z tymi samymi 4 cyframi", () => {
    const options = assignOptions(unmatched, [payableRow(), mandate]);
    expect(options.map((o) => o.label)).toEqual(["Ola Nowak · 10/2026", "Kuba Lato · 10/2026"]);
    expect(assignOptions({ ...unmatched, currency: "EUR", hints: [] }, [payableRow()])).toEqual([]);
  });
});
