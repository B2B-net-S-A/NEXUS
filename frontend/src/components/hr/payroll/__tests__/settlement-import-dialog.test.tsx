import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettlementImportDialog } from "../SettlementImportDialog";

const previewMutate = vi.fn();
const applyMutate = vi.fn();

vi.mock("@/lib/api/hr-payroll", () => ({
  useSettlementImportPreview: () => ({ mutate: previewMutate, isPending: false }),
  useApplySettlementImport: () => ({ mutate: applyMutate, isPending: false }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: async () => true, confirmDialog: null }),
}));

const base = {
  person: "Bąk Jan",
  candidate: "Anna Nowak",
  note: "",
  recipient_active: true,
  contract_id: 1,
  contract_label: "Anna Nowak (Firma)",
  start_date: "2026-09-01",
  role: "recruiter",
  keyed: true,
  category: "recruiter",
  automat_name: null,
  automat_amount: null,
};

const rows = [
  { ...base, index: 2, amount: "1000.00", recipient_user_id: 5, recipient_name: "Jan Bąk", selected: true, status: "matches" },
  { ...base, index: 3, amount: "3000.00", recipient_user_id: 6, recipient_name: "Ewa Kowal", selected: true, status: "differs", automat_name: "Ola Lis" },
  { ...base, index: 4, amount: "1500.00", recipient_user_id: 7, recipient_name: "Ola Lis", recipient_active: false, selected: false, status: "inactive" },
  { ...base, index: 5, amount: "500.00", recipient_user_id: null, recipient_name: null, person: "Ktoś Obcy", selected: false, status: "no_person" },
];

function renderDialog() {
  render(
    <SettlementImportDialog open onOpenChange={vi.fn()} year={2026} month={10} label="Październik 2026" />,
  );
  previewMutate.mockImplementation((_file, { onSuccess }) =>
    onSuccess({ year: 2026, month: 10, rows, counts: { matches: 1, differs: 1, inactive: 1, no_person: 1 }, total: "6000.00" }),
  );
  fireEvent.change(screen.getByLabelText("Arkusz rozliczenia"), {
    target: { files: [new File(["x"], "rozliczenie.xlsx")] },
  });
}

describe("SettlementImportDialog", () => {
  beforeEach(() => {
    previewMutate.mockReset();
    applyMutate.mockReset();
  });

  it("zaznacza wiersze z podglądu, a konta nieaktywnego domyślnie nie", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "Przyznaj zaznaczone (2)" })).toBeInTheDocument();
    expect(screen.getByText("Automat: Ola Lis")).toBeInTheDocument();
    expect(screen.getByLabelText("Przyznaj: Ktoś Obcy, Anna Nowak")).toBeDisabled();
  });

  it("wysyła tylko zaznaczone wiersze", async () => {
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Przyznaj zaznaczone (2)" }));
    await waitFor(() => expect(applyMutate).toHaveBeenCalled());
    expect(applyMutate.mock.calls[0][0].map((row: { index: number }) => row.index)).toEqual([2, 3]);
  });

  it("awaria odczytu pokazuje komunikat zamiast pustej tabeli", () => {
    render(
      <SettlementImportDialog open onOpenChange={vi.fn()} year={2026} month={10} label="Październik 2026" />,
    );
    previewMutate.mockImplementation((_file, { onError }) => onError(new Error("x")));
    fireEvent.change(screen.getByLabelText("Arkusz rozliczenia"), {
      target: { files: [new File(["x"], "zly.xlsx")] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się odczytać arkusza.");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
