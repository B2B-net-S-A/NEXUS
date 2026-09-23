import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { OrderPdfsPanel } from "@/components/finance/OrderPdfsPanel";
import { defaultOrderPdfMonth } from "@/components/finance/OrderPdfsTab";
import type { OrderPdfClient, OrderPdfFile, OrderPdfMonth } from "@/lib/api/finance";
import { filesLabel, orderPdfPeriod } from "@/lib/finance-order-pdfs";

vi.mock("@/lib/api/finance", () => ({
  financeApi: {},
  orderPdfFilePath: vi.fn(),
  orderPdfZipPath: vi.fn(),
}));
vi.mock("@/components/v2/files/SearchablePdfPreview", () => ({
  SearchablePdfPreview: () => <div data-testid="pdf-preview" />,
}));
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
  downloaded_at: null,
  pending_change: true,
};

const DOWNLOADED: OrderPdfFile = {
  ...FILE,
  id: 9,
  download_name: "aneks_Nowak.pdf",
  entry_type: "amendment",
  order_number: null,
  downloaded_at: "2026-09-22T08:30:00Z",
  pending_change: false,
};

const CLIENTS: OrderPdfClient[] = [
  { client_id: 1, client_name: "Alior", files: [FILE, DOWNLOADED] },
  {
    client_id: 2,
    client_name: "BNP",
    files: [{ ...FILE, id: 8, kind: "group", consultant_name: null }],
  },
];

const MONTHS: OrderPdfMonth[] = [{ month: "2026-09", clients: 2, files: 3 }];

function Harness({
  onDownload,
  onDownloadMonth = vi.fn(),
  onDownloadClient = vi.fn(),
  onDownloadFiles = vi.fn(),
}: {
  onDownload: (file: OrderPdfFile) => void;
  onDownloadMonth?: () => void;
  onDownloadClient?: (client: OrderPdfClient) => void;
  onDownloadFiles?: (client: OrderPdfClient, files: OrderPdfFile[]) => void;
}) {
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
      onDownloadMonth={onDownloadMonth}
      onDownloadClient={onDownloadClient}
      onDownloadFiles={onDownloadFiles}
      zipBusy={null}
      loadPdf={async () => new Blob(["%PDF"])}
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
    expect(screen.getByText("Przedłużenie", { selector: "span" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: `Pobierz ${FILE.download_name}` }));
    expect(onDownload).toHaveBeenCalledWith(FILE);
  });

  it("marks a file without an assigned person", () => {
    render(<Harness onDownload={vi.fn()} />);
    fireEvent.click(screen.getByRole("option", { name: /BNP/ }));
    expect(screen.getByText("Nazwisko do uzupełnienia")).toBeInTheDocument();
  });
});

describe("OrderPdfsPanel — ZIP i statusy pobrania", () => {
  it("shows per-person status and the pending-change tag", () => {
    render(<Harness onDownload={vi.fn()} />);
    const alior = screen.getByRole("option", { name: /Alior/ });
    expect(alior.textContent).toContain("2 pliki · 1 nowy");
    fireEvent.click(alior);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0].textContent).toContain("● Nowy");
    expect(rows[0].textContent).toContain("zmiana do rozliczenia");
    expect(rows[1].textContent).toContain("Pobrane przez Ciebie 22.09.2026");
  });

  it("downloads the month, the client, the new and the selected files", () => {
    const onDownloadMonth = vi.fn();
    const onDownloadClient = vi.fn();
    const onDownloadFiles = vi.fn();
    render(
      <Harness
        onDownload={vi.fn()}
        onDownloadMonth={onDownloadMonth}
        onDownloadClient={onDownloadClient}
        onDownloadFiles={onDownloadFiles}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Pobierz cały miesiąc/ }));
    expect(onDownloadMonth).toHaveBeenCalledTimes(1);

    fireEvent.click(
      screen.getByRole("button", { name: "Pobierz wszystkie pliki klienta: BNP" }),
    );
    expect(onDownloadClient).toHaveBeenCalledWith(CLIENTS[1]);

    fireEvent.click(screen.getByRole("option", { name: /Alior/ }));
    fireEvent.click(screen.getByRole("button", { name: "Pobierz nowe (1)" }));
    expect(onDownloadFiles).toHaveBeenLastCalledWith(CLIENTS[0], [FILE]);

    expect(screen.getByRole("button", { name: "Pobierz zaznaczone (0)" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz wszystkie" }));
    fireEvent.click(screen.getByRole("button", { name: "Pobierz zaznaczone (2)" }));
    expect(onDownloadFiles).toHaveBeenLastCalledWith(CLIENTS[0], [FILE, DOWNLOADED]);
  });

  it("filters to files not yet downloaded and previews one", () => {
    render(<Harness onDownload={vi.fn()} />);
    fireEvent.click(screen.getByRole("option", { name: /Alior/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tylko niepobrane" }));
    expect(screen.queryByText(DOWNLOADED.download_name)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: `Podgląd: ${FILE.download_name}` }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(FILE.download_name)).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
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
