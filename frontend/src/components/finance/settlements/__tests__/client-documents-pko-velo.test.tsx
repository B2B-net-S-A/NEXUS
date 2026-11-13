import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientDocumentsMonth } from "@/lib/api/client-settlements";

import { ClientDocumentsPanel } from "../ClientDocumentsPanel";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  download: vi.fn(),
  copy: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, put: vi.fn() } }));
vi.mock("@/lib/authenticated-files", () => ({ downloadBlob: mocks.download }));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: mocks.copy }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: mocks.success, showError: mocks.error }) }));

const common: Omit<ClientDocumentsMonth, "kind"> = {
  client_id: 7,
  month: "2026-10",
  enabled: true,
  stage: null,
  can_see_amounts: true,
  projects: [],
  skipped: [],
};

const protocol: ClientDocumentsMonth = {
  ...common,
  kind: "Protokół odbioru",
  layout: "month",
  protocol: {
    people: 3,
    accepted: 2,
    ready: false,
    send_to: "paczki@klient.example",
    signed: false,
    signed_by: null,
    missing_roles: ["Ola Testowa"],
    missing_orders: [],
    waiting: [{ person: "Jan Próbny", status: "warnings" }],
    hours: "352.00",
    net: "35200.00",
    files: [
      { person: "Ola Testowa", timesheet: true },
      { person: "Ewa Nowa", timesheet: true },
    ],
  },
};

const sheets: ClientDocumentsMonth = {
  ...common,
  kind: "Arkusz zbiorczy",
  layout: "signer",
  sheets: {
    signers: [
      { signer: "Podpisujący A", people: 2, md: "39.500", signed: 1 },
      { signer: "Bez podpisującego", people: 1, md: "19.000", signed: 0 },
    ],
    rows: [
      { contract_id: 1, person: "Ola Testowa", signer: "Podpisujący A", md: "19.000", status: "accepted", signed: true, signed_by: "Podpisujący A", signed_at: "2026-11-05T10:00:00+01:00", amount: null },
      { contract_id: 2, person: "Jan Próbny", signer: "Podpisujący A", md: "20.500", status: "warnings", signed: false, signed_by: null, signed_at: null, amount: null },
      { contract_id: 3, person: "Ewa Nowa", signer: "Bez podpisującego", md: "19.000", status: "ok", signed: false, signed_by: null, signed_at: null, amount: null },
    ],
    without_sheet: [{ person: "Adam Drugi", status: "missing" }],
    all_signed: false,
    net: "52000.00",
  },
};

function renderPanel(data: ClientDocumentsMonth) {
  mocks.get.mockImplementation((_url: string, config?: { responseType?: string }) =>
    Promise.resolve({ data: config?.responseType === "blob" ? new Blob(["x"]) : data }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientDocumentsPanel clientId={7} month="2026-10" />
    </QueryClientProvider>,
  );
}

describe("Dokumenty dla klienta na wiele osób (E6.1, E6.2)", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset();
  });

  it("PKO: protokół i paczka czekają na komplet, adres paczki i braki roli widać", async () => {
    renderPanel(protocol);
    expect(await screen.findByRole("heading", { name: /przyjęte 2 z 3 osób/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz protokół do podpisu/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Pobierz paczkę/ })).toBeDisabled();
    expect(screen.getByText(/na paczki@klient.example/)).toBeInTheDocument();
    expect(screen.getByText(/Czekamy na: Jan Próbny \(z uwagami\)/)).toBeInTheDocument();
    expect(screen.getByText(/Bez roli w protokole/)).toBeInTheDocument();
  });

  it("PKO: przy komplecie pobiera protokół, bez dostępu do kwot nie ma przycisków", async () => {
    const ready = { ...protocol, protocol: { ...protocol.protocol!, ready: true, accepted: 3, waiting: [] } };
    const { unmount } = renderPanel(ready);
    fireEvent.click(await screen.findByRole("button", { name: /Pobierz protokół do podpisu/ }));
    await waitFor(() => expect(mocks.download).toHaveBeenCalledWith(expect.any(Blob), "Protokol_odbioru_2026-10.pdf"));
    expect(mocks.get).toHaveBeenLastCalledWith(
      "/api/finance/settlements/client-documents/file",
      expect.objectContaining({ params: expect.objectContaining({ kind: "protocol" }) }),
    );
    unmount();
    renderPanel({ ...ready, can_see_amounts: false });
    expect(await screen.findByText(/pobierają go osoby z dostępem do kwot/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pobierz protokół/ })).toBeNull();
  });

  it("Velo: arkusz przy każdym podpisującym osobno obok „Pobierz wszystkie”", async () => {
    renderPanel(sheets);
    expect(await screen.findByText(/2 podpisujących, podpisane 1 z 3/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz wszystkie/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Arkusz pod fakturę/ })).toBeDisabled();
    expect(screen.getByText(/Podpisany: Podpisujący A, 05.11/)).toBeInTheDocument();
    expect(screen.getAllByText("Do podpisu")).toHaveLength(2);
    expect(screen.getByText(/Ustaw menedżera u klienta/)).toBeInTheDocument();
    expect(screen.getByText(/Poza arkuszami: Adam Drugi \(brak rcp\)/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Pobierz arkusz: Podpisujący A" }));
    await waitFor(() => expect(mocks.download).toHaveBeenCalled());
    expect(mocks.get).toHaveBeenLastCalledWith(
      "/api/finance/settlements/client-documents/file",
      expect.objectContaining({ params: expect.objectContaining({ kind: "sheet", signer: "Podpisujący A" }) }),
    );
  });

  it("Wgranie podpisanego dokumentu idzie na trasę rozpoznania", async () => {
    mocks.post.mockResolvedValue({ data: { document_id: 9, recognized: true } });
    const { container } = renderPanel(sheets);
    await screen.findByText(/podpisujących/);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["%PDF"], "arkusz.pdf", { type: "application/pdf" })] } });
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/client-documents/signed", expect.any(FormData)));
    await waitFor(() => expect(mocks.success).toHaveBeenCalled());
  });
});
