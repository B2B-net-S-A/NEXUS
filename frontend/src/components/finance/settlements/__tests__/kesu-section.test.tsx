import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KesuBlock } from "@/lib/api/client-settlements";

import { KesuSection } from "../KesuSection";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  download: vi.fn(),
  copy: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: mocks.post, put: vi.fn() } }));
vi.mock("@/lib/authenticated-files", () => ({ downloadBlob: mocks.download }));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: mocks.copy }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess: mocks.success, showError: mocks.error }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: mocks.confirm, confirmDialog: null }),
}));

const block: KesuBlock = {
  state: "awaiting_client",
  state_label: "Czeka na podpis klienta",
  approver: "Paweł Opiekun",
  accepted_at: "2026-11-03T13:08:00",
  hours: "160.00",
  days: 20,
  approver_email: "Pawel.Opiekun@klient.example",
  md_hours: "8",
  rate_md: "1145.68",
  rate_contract: "1145.68",
  rate_order: "1145.68",
  fee_gross: "28183.73",
  extra_costs: "0.00",
  total_gross: "28183.73",
  rate_differs: false,
  mail: {
    to: "Pawel.Opiekun@klient.example",
    to_name: "Paweł Opiekun",
    subject: "KEŚU październik - Ewa Kozłowska",
    body: "Dzień dobry,\n\nW załączeniu KEŚU (Ewa) z naszym podpisem.",
  },
  payment: {
    state: "fail",
    title: "Zapłata czeka na podpis klienta na KEŚU",
    detail: "Gdy podpisujący jest nieobecny i nie ma zastępstwa, można zapłacić po akceptacji mailowej.",
    can_pay: false,
    on_mail: false,
    can_use_mail: true,
  },
  invoice_waits: true,
  package_ready: true,
};

function renderSection(data: KesuBlock, canWrite = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <KesuSection contractId={5} month="2026-10" person="Ewa Kozłowska" block={data} canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

describe("KEŚU z Jiry na karcie osoby (E6.3)", () => {
  beforeEach(() => {
    Object.values(mocks).forEach((m) => m.mockReset());
  });

  it("pokazuje opiekuna, czas, stawkę i razem brutto, a fakturę wstrzymuje do podpisu klienta", () => {
    renderSection(block);
    expect(screen.getAllByText("Czeka na podpis klienta").length).toBeGreaterThan(0);
    expect(screen.getByText("Paweł Opiekun, 03.11.2026 13:08")).toBeInTheDocument();
    expect(screen.getByText("160 h, 20 dni")).toBeInTheDocument();
    expect(screen.getByText(/1\s145,68/)).toBeInTheDocument();
    expect(screen.getByText(/28\s183,73/)).toBeInTheDocument();
    expect(screen.getByText("Faktura do klienta: dopiero po podpisie klienta.")).toBeInTheDocument();
    // Stawka z kontraktu zgodna z zamówieniem: różnicy nie pokazujemy.
    expect(screen.queryByText("Na zamówieniu")).not.toBeInTheDocument();
  });

  it("różnicę stawki pokazuje tylko, gdy kontrakt nie zgadza się z zamówieniem", () => {
    renderSection({ ...block, rate_order: "1100.00", rate_differs: true });
    expect(screen.getByText("Na zamówieniu")).toBeInTheDocument();
    expect(screen.getByText(/różnica 45,68/)).toBeInTheDocument();
  });

  it("bez dostępu do kwot nie pokazuje stawki ani paczki", () => {
    renderSection({ ...block, rate_md: null, rate_contract: null, rate_order: null, fee_gross: null, total_gross: null });
    expect(screen.queryByText("Razem w PLN BRUTTO")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Paczka do podpisu/ })).not.toBeInTheDocument();
  });

  it("pobiera paczkę PDF i kopiuje mail do opiekuna z maila z Jiry", async () => {
    mocks.get.mockResolvedValue({ data: new Blob(["%PDF"]) });
    mocks.copy.mockResolvedValue(true);
    renderSection(block);
    fireEvent.click(screen.getByRole("button", { name: /Paczka do podpisu/ }));
    await waitFor(() => expect(mocks.download).toHaveBeenCalled());
    expect(mocks.get.mock.calls[0][0]).toContain("/contract/5/kesu/package");
    expect(mocks.download.mock.calls[0][1]).toBe("KESU_Ewa_Kozlowska_10.2026.pdf");
    fireEvent.click(screen.getByRole("button", { name: /Mail do opiekuna/ }));
    await waitFor(() => expect(mocks.copy).toHaveBeenCalled());
    expect(mocks.copy.mock.calls[0][0]).toContain("Do: Pawel.Opiekun@klient.example");
    expect(mocks.copy.mock.calls[0][0]).toContain("Temat: KEŚU październik - Ewa Kozłowska");
  });

  it("zapłata po mailu dopiero po potwierdzeniu i tylko z prawem zapisu", async () => {
    mocks.confirm.mockResolvedValue(true);
    mocks.post.mockResolvedValue({ data: {} });
    renderSection(block);
    fireEvent.click(screen.getByRole("button", { name: "Podpisujący nieobecny" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    expect(mocks.post.mock.calls[0][0]).toContain("/contract/5/pay-on-mail");
    expect(mocks.success).toHaveBeenCalled();

    mocks.post.mockReset();
    mocks.confirm.mockResolvedValue(false);
    renderSection({ ...block }, true);
    fireEvent.click(screen.getAllByRole("button", { name: "Podpisujący nieobecny" })[1]);
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledTimes(2));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("bez prawa zapisu nie ma przycisku zapłaty po mailu, po podpisie nie ma paczki ani maila", () => {
    const { unmount } = renderSection(block, false);
    expect(screen.queryByRole("button", { name: "Podpisujący nieobecny" })).not.toBeInTheDocument();
    unmount();
    renderSection({ ...block, state: "signed", payment: { ...block.payment!, state: "ok", can_pay: true, can_use_mail: false } });
    expect(screen.getByText("Oba podpisy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Paczka do podpisu/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Mail do opiekuna/ })).not.toBeInTheDocument();
  });
});
