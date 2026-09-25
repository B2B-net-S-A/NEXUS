import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InvoiceLinesField } from "@/components/finance/InvoiceLinesField";
import { OrderChangesList } from "@/components/finance/OrderChangesPanel";
import type { InvoiceLine, OrderChangesResponse } from "@/lib/api/finance";
import {
  withCheck,
  withInvoiceLines,
  type StatusFilter,
} from "@/lib/finance-order-board";

vi.mock("@/components/v2/files/SearchablePdfPreview", () => ({
  SearchablePdfPreview: () => <div data-testid="pdf-preview" />,
}));

const FULL =
  "NIDS: 2099-000123, IT Retail Banking, Nordea Contact: Jan Testowy, Contractor: Ewa Przykładowa ID:";

const line = (overrides: Partial<InvoiceLine> = {}): InvoiceLine => ({
  index: 0,
  consultant: "Ewa Przykładowa",
  text: FULL,
  edited_by_name: null,
  edited_at: null,
  ...overrides,
});

let writeText: ReturnType<typeof vi.fn>;

beforeEach(() => {
  writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("InvoiceLinesField", () => {
  it("shows the formula and copies it with a confirmation", async () => {
    render(<InvoiceLinesField lines={[line()]} canSave onSave={vi.fn()} />);
    expect(screen.getByText("Pozycja faktury")).toBeInTheDocument();
    expect(screen.getByText(FULL, { exact: false })).toBeInTheDocument();
    expect(
      screen.queryByText("Uzupełnij brakujące dane w formule"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Kopiuj/ }));
    expect(await screen.findByText("Skopiowano")).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(FULL);
  });

  it("says when copying failed instead of pretending it worked", async () => {
    writeText.mockRejectedValueOnce(new Error("denied"));
    render(<InvoiceLinesField lines={[line()]} canSave={false} />);
    fireEvent.click(screen.getByRole("button", { name: /Kopiuj/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się skopiować",
    );
    expect(screen.queryByText("Skopiowano")).not.toBeInTheDocument();
  });

  it("warns about [brak] and saves a manual correction", async () => {
    const onSave = vi.fn().mockResolvedValue(true);
    const missing = FULL.replace("2099-000123", "[brak]");
    render(
      <InvoiceLinesField
        lines={[line({ text: missing })]}
        canSave
        onSave={onSave}
      />,
    );
    expect(
      screen.getByText("Uzupełnij brakujące dane w formule"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Edytuj/ }));
    const input = screen.getByRole("textbox", { name: "Pozycja faktury" });
    fireEvent.change(input, { target: { value: FULL } });
    expect(
      screen.queryByText("Uzupełnij brakujące dane w formule"),
    ).not.toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    });
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ index: 0 }),
      FULL,
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("textbox", { name: "Pozycja faktury" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("lets a reader edit and copy, but not save", () => {
    render(<InvoiceLinesField lines={[line()]} canSave={false} />);
    fireEvent.click(screen.getByRole("button", { name: /Edytuj/ }));
    expect(screen.queryByRole("button", { name: "Zapisz" })).not.toBeInTheDocument();
    expect(screen.getByText(/Poprawki nie zapiszesz/)).toBeInTheDocument();
  });

  it("gives every consultant a separate formula with its own copy button", async () => {
    render(
      <InvoiceLinesField
        lines={[
          line(),
          line({
            index: 1,
            consultant: "Karol Demo",
            text: FULL.replace("Ewa Przykładowa", "Karol Demo"),
          }),
        ]}
        canSave
        onSave={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Pozycja faktury — Ewa Przykładowa"),
    ).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: /Kopiuj/ });
    expect(buttons).toHaveLength(2);
    fireEvent.click(buttons[1]);
    await screen.findByText("Skopiowano");
    expect(writeText).toHaveBeenCalledWith(
      FULL.replace("Ewa Przykładowa", "Karol Demo"),
    );
  });
});

// ── Na karcie „Wejść” ───────────────────────────────────────────────────────

const DATA: OrderChangesResponse = {
  period: { year: 2026, month: 9, label: "Wrzesień 2026" },
  counts: { changes: 0, entries: 1, exits: 0, ending: 0, gaps: 0 },
  changes: [],
  entries: [
    {
      order_id: 21,
      order_group_id: null,
      contract_id: 1,
      client_id: 11,
      client_name: "Nordea Bank Abp",
      consultant_name: "Ewa Przykładowa",
      order_number: "299001",
      item_key: "entry:21",
      start_date: "2026-09-14",
      end_date: "2027-03-12",
      rate_cost: 110,
      rate_revenue: 135,
      rate_unit: "hourly",
      currency: "PLN",
      order_type: "periodic",
      status: "active",
      invoice_lines: [line()],
    },
  ],
  exits: [],
  ending_orders: [],
  gaps: [],
  changes_tracked_since: null,
  gaps_tracked_since: "2026-08-01",
  open_gaps_total: 0,
  can_check: true,
};

function Board() {
  const [data, setData] = useState(DATA);
  const [status] = useState<StatusFilter>("all");
  return (
    <OrderChangesList
      data={data}
      subTab="entries"
      onOpenGaps={vi.fn()}
      board={{
        status,
        selectedClient: null,
        onSelectClient: vi.fn(),
        onToggle: (item, done) =>
          setData((current) =>
            withCheck(
              current,
              item.key,
              done ? { by_name: "Anna Finanse", at: "2026-09-25T08:00:00Z" } : null,
            ),
          ),
        onSaveInvoiceLine: async (item, saved, text) => {
          setData((current) =>
            withInvoiceLines(current, item.orderId ?? 0, [{ ...saved, text }]),
          );
          return true;
        },
        pendingKeys: new Set(),
        onDownloadPdf: vi.fn(),
        downloadingPdf: null,
        previewCard: null,
        onPreviewCard: vi.fn(),
        preview: {
          history: { items: [], loading: false, failed: false },
          loadPdf: async () => new Blob(["%PDF"]),
          onOpenInPdfs: vi.fn(),
        },
      }}
    />
  );
}

describe("Wejścia: pozycja faktury Nordei", () => {
  it("stays on the card after the entry is marked done", () => {
    render(<Board />);
    expect(screen.getByText(FULL, { exact: false })).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("checkbox", { name: /Oznacz jako zrobione: Nowe zamówienie/ }),
    );
    expect(screen.getByText(/Zrobione: Anna Finanse/)).toBeInTheDocument();
    expect(screen.getByText(FULL, { exact: false })).toBeInTheDocument();
  });

  it("does not toggle „Zrobione” when the formula buttons are used", () => {
    render(<Board />);
    fireEvent.click(screen.getByRole("button", { name: /Edytuj/ }));
    expect(
      screen.getByRole("checkbox", { name: /Oznacz jako zrobione/ }),
    ).not.toBeChecked();
  });
});
