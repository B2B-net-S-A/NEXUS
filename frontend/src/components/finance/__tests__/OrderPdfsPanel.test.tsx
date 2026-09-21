import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { OrderPdfsPanel } from "@/components/finance/OrderPdfsPanel";
import { defaultOrderPdfMonth } from "@/components/finance/OrderPdfsTab";
import type { OrderPdfClient, OrderPdfFile, OrderPdfMonth } from "@/lib/api/finance";
import { filesLabel, orderPdfPeriod } from "@/lib/finance-order-pdfs";

vi.mock("@/lib/api/finance", () => ({ financeApi: {}, orderPdfFilePath: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));

const FILE: OrderPdfFile = {
  kind: "order",
  id: 7,
  download_name: "zamowienie_alior_Nowak_15.09.2026-31.12.2026.pdf",
  original_name: "zamowienie_alior.pdf",
  consultant_name: "Jan Nowak",
  start: "2026-09-15",
  end: "2026-12-31",
  entry_type: "extension",
  status: "active",
  order_number: "OIT/1",
  uploaded_at: null,
};

const CLIENTS: OrderPdfClient[] = [
  { client_id: 1, client_name: "Alior", files: [FILE] },
  {
    client_id: 2,
    client_name: "BNP",
    files: [{ ...FILE, id: 8, kind: "group", consultant_name: null }],
  },
];

const MONTHS: OrderPdfMonth[] = [{ month: "2026-09", clients: 2, files: 2 }];

function Harness({ onDownload }: { onDownload: (file: OrderPdfFile) => void }) {
  const [clientId, setClientId] = useState<number | null>(null);
  return (
    <OrderPdfsPanel
      months={MONTHS}
      month="2026-09"
      onMonthChange={() => undefined}
      clients={CLIENTS}
      clientId={clientId}
      onClientChange={setClientId}
      onDownload={onDownload}
      downloadingKey={null}
    />
  );
}

describe("OrderPdfsPanel", () => {
  it("shows the months, then the client's files with the download name", () => {
    const onDownload = vi.fn();
    render(<Harness onDownload={onDownload} />);

    expect(screen.getByRole("option", { name: /Wrzesień 2026/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("Wybierz klienta, aby zobaczyć PDF-y.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("option", { name: /Alior/ }));
    expect(screen.getByText(FILE.download_name)).toBeInTheDocument();
    expect(screen.getByText("Przedłużenie")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: `Pobierz ${FILE.download_name}` }));
    expect(onDownload).toHaveBeenCalledWith(FILE);
  });

  it("marks a file without an assigned person", () => {
    render(<Harness onDownload={vi.fn()} />);
    fireEvent.click(screen.getByRole("option", { name: /BNP/ }));
    expect(screen.getByText("Nazwisko do uzupełnienia")).toBeInTheDocument();
  });
});

describe("order PDF helpers", () => {
  it("picks the current month, else the latest past, else the nearest future", () => {
    const today = new Date(2026, 8, 21);
    const m = (month: string) => ({ month, clients: 1, files: 1 });
    expect(defaultOrderPdfMonth([m("2026-10"), m("2026-09")], today)).toBe("2026-09");
    expect(defaultOrderPdfMonth([m("2026-12"), m("2026-07")], today)).toBe("2026-07");
    expect(defaultOrderPdfMonth([m("2027-02"), m("2026-11")], today)).toBe("2026-11");
    expect(defaultOrderPdfMonth([], today)).toBeNull();
  });

  it("formats period and counts", () => {
    expect(orderPdfPeriod({ start: "2026-09-15", end: null })).toBe(
      "15.09.2026–bezterminowo",
    );
    expect(filesLabel(1)).toBe("1 plik");
    expect(filesLabel(3)).toBe("3 pliki");
    expect(filesLabel(12)).toBe("12 plików");
  });
});
