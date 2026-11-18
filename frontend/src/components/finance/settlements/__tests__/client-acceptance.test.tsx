import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ClientAcceptanceMonth } from "@/lib/api/client-settlements";

import { ClientAcceptancePanel, kcpFileName } from "../ClientAcceptancePanel";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  download: vi.fn(),
  copy: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, put: vi.fn() },
}));
vi.mock("@/lib/authenticated-files", () => ({ downloadBlob: mocks.download }));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: mocks.copy }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.success, showError: mocks.error }),
}));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, confirmDialog: null }),
}));

const person = (contract_id: number, name: string, state: string, extra = {}) => ({
  contract_id,
  person: name,
  state,
  sent_at: null,
  accepted_at: null,
  reply: null,
  source: null,
  ...extra,
});

const month: ClientAcceptanceMonth = {
  enabled: true,
  client_id: 7,
  month: "2026-10",
  email: "body@bank.example",
  subject: "KCP B2Bnetwork październik 2026",
  body: "Dzień dobry,\n\nw załączeniu przesyłam KCP naszych konsultantów za październik 2026: Ola Testowa.\nProśba o akceptację.\n",
  people: [
    person(1, "Jan Próbny", "accepted", {
      sent_at: "2026-11-06T10:17:00+01:00",
      accepted_at: "2026-11-10T10:30:00+01:00",
      reply: "Akceptuję nadesłane KCP.",
      source: "mail",
    }),
    person(2, "Ewa Nowa", "sent", { sent_at: "2026-11-10T13:36:00+01:00" }),
    person(3, "Ola Testowa", "to_send"),
    person(4, "Adam Brak", "none"),
  ] as ClientAcceptanceMonth["people"],
  batches: [
    { sent_at: "2026-11-06T10:17:00+01:00", people: 1, accepted: 1, accepted_at: "2026-11-10T10:30:00+01:00", reply: "Akceptuję nadesłane KCP." },
    { sent_at: "2026-11-10T13:36:00+01:00", people: 1, accepted: 0, accepted_at: null, reply: null },
  ],
  counts: { none: 1, to_send: 1, sent: 1, accepted: 1 },
};

function renderPanel(data: ClientAcceptanceMonth, canWrite = true) {
  mocks.get.mockResolvedValue({ data });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ClientAcceptancePanel clientId={7} month="2026-10" canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

describe("ClientAcceptancePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.confirm.mockResolvedValue(true);
    mocks.copy.mockResolvedValue(true);
  });

  it("nic nie pokazuje u klienta bez reguły akceptacji", async () => {
    const { container } = renderPanel({ enabled: false, client_id: 7, month: "2026-10" });
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("pokazuje paczki, osoby do wysłania i brak KCP", async () => {
    renderPanel(month);
    expect(await screen.findByText(/zaakceptowane 1 z 3/)).toBeInTheDocument();
    expect(screen.getByText(/Paczka 06\.11 10:17 · 1 KCP · zaakceptowana 10\.11/)).toBeInTheDocument();
    expect(screen.getByText("„Akceptuję nadesłane KCP.”")).toBeInTheDocument();
    expect(screen.getByText(/Paczka 10\.11 13:36 · 1 KCP · zaakceptowane 0 z 1/)).toBeInTheDocument();
    expect(screen.getByText("Do wysłania: Ola Testowa")).toBeInTheDocument();
    expect(screen.getByText("Brak KCP: Adam Brak.")).toBeInTheDocument();
  });

  it("szkic maila: paczka zip, treść i oznaczenie wysyłki tylko osób do wysłania", async () => {
    mocks.post.mockResolvedValue({ data: { sent: 1 } });
    renderPanel(month);
    fireEvent.click(await screen.findByRole("button", { name: /Wyślij do akceptacji \(1 KCP\)/ }));
    expect(screen.getByText("O. Testowa.pdf")).toBeInTheDocument();
    expect(screen.getByText("KCP B2Bnetwork październik 2026")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Kopiuj treść/ }));
    await waitFor(() => expect(mocks.copy).toHaveBeenCalledWith(month.body));
    fireEvent.click(screen.getByRole("button", { name: "Oznacz jako wysłane" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/client-acceptance/sent", {
        client_id: 7,
        month: "2026-10",
        contract_ids: [3],
      }),
    );
  });

  it("„Klient zaakceptował” przy paczce czekającej na klienta", async () => {
    mocks.post.mockResolvedValue({ data: { accepted: 1 } });
    renderPanel(month);
    fireEvent.click(await screen.findByRole("button", { name: "Klient zaakceptował" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/finance/settlements/client-acceptance/accept", {
        client_id: 7,
        month: "2026-10",
        contract_ids: [2],
      }),
    );
  });

  it("bez prawa zapisu tylko stan, bez przycisków", async () => {
    renderPanel(month, false);
    await screen.findByText(/zaakceptowane 1 z 3/);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("nazwa pliku jak w instrukcji: pierwsza litera imienia i nazwisko", () => {
    expect(kcpFileName("Jan Maria Testowy")).toBe("J. Maria Testowy.pdf");
    expect(kcpFileName("Testowy")).toBe("Testowy.pdf");
  });
});
