/**
 * Krok „Umowa” w panelu osoby (PR 6 ścieżki kandydata, 04.10.2026): stan
 * umowy, podpisu i zamówienia bez przechodzenia do warsztatu.
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const generated = vi.fn();
const requestSignature = vi.fn();
const showSuccess = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {},
  b2bGeneratorApi: {
    generated: (...a: unknown[]) => generated(...a),
    requestSignature: (...a: unknown[]) => requestSignature(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError: vi.fn() }),
}));
vi.mock("@/components/v2/pages/B2BContractGeneratorV2", () => ({
  ConfirmFullySignedDialog: (p: { row: { contract_number: string } }) => (
    <div role="dialog" aria-label="okno podpisu">
      Podpis umowy {p.row.contract_number}
    </div>
  ),
}));

import { DockContractSteps } from "@/components/v2/jobs/DockContractSteps";

function renderSteps(props: Partial<React.ComponentProps<typeof DockContractSteps>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DockContractSteps
        candidateId={42}
        jobId={10}
        clientId={7}
        orderStatus={null}
        readOnly={false}
        {...props}
      />
    </QueryClientProvider>,
  );
}

const ROW = {
  id: 501,
  candidate_id: 42,
  contract_number: "1506/2026",
  contract_status: "in_progress",
  signature_status: "unsigned",
  created_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
  can_confirm_signed: false,
};

beforeEach(() => {
  generated.mockReset();
  requestSignature.mockReset();
  showSuccess.mockReset();
});

describe("DockContractSteps", () => {
  it("bez umowy prowadzi do Generatora z wybraną osobą i rekrutacją", async () => {
    generated.mockResolvedValue([]);
    renderSteps();
    const link = await screen.findByRole("link", { name: "Otwórz Generator umów" });
    expect(link.getAttribute("href")).toContain("candidate=42");
    expect(link.getAttribute("href")).toContain("job=10");
    expect(generated).toHaveBeenCalledWith(50, { jobId: 10 });
  });

  it("bez umowy i z rozwinięciem panelu: „Wygeneruj umowę” otwiera zakładkę „Umowa”", async () => {
    generated.mockResolvedValue([]);
    const onGenerate = vi.fn();
    renderSteps({ onGenerate });
    fireEvent.click(await screen.findByRole("button", { name: "Wygeneruj umowę" }));
    expect(onGenerate).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("link", { name: "Otwórz Generator umów" })).toBeNull();
  });

  it("umowa niepodpisana bez „Podpis B2B”: dni czekania i prośba do Delivery Leada", async () => {
    generated.mockResolvedValue([ROW]);
    requestSignature.mockResolvedValue({ sent: true, requested_at: "2026-10-04T10:00:00Z", recipient_names: ["Anna DL"] });
    renderSteps();
    expect(await screen.findByText("Nr 1506/2026")).toBeInTheDocument();
    expect(screen.getByText(/Czeka na podpis od 3 dni/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "W rejestrze ↗" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Poproś o potwierdzenie podpisu" }));
    await waitFor(() => expect(requestSignature).toHaveBeenCalledWith(501));
    expect(showSuccess).toHaveBeenCalledWith(expect.stringContaining("Anna DL"));
    expect(await screen.findByRole("button", { name: "Przypomnij o podpisie" })).toBeInTheDocument();
  });

  it("prośba już wysłana (z karty): przycisk przypomina, zdanie podaje datę", async () => {
    generated.mockResolvedValue([ROW]);
    renderSteps({
      agreement: {
        id: 501,
        number: "1506/2026",
        contract_status: "in_progress",
        signature_status: "unsigned",
        created_at: ROW.created_at,
        signed_at: null,
        signature_requested_at: "2026-10-02T10:00:00Z",
        contract_id: null,
      },
    });
    expect(await screen.findByRole("button", { name: "Przypomnij o podpisie" })).toBeInTheDocument();
    expect(screen.getByText(/Prośba wysłana 02\.10\.2026/)).toBeInTheDocument();
  });

  it("z uprawnieniem „Podpis B2B”: okno podpisu z rejestru, bez prośby", async () => {
    generated.mockResolvedValue([{ ...ROW, can_confirm_signed: true }]);
    renderSteps();
    fireEvent.click(await screen.findByRole("button", { name: "Oznacz jako podpisaną…" }));
    expect(await screen.findByText("Podpis umowy 1506/2026")).toBeInTheDocument();
    expect(requestSignature).not.toHaveBeenCalled();
  });

  it("zatrudniony bez zamówienia: zdanie o sprawie i link do zamówień klienta", async () => {
    generated.mockResolvedValue([{ ...ROW, signature_status: "signed_both" }]);
    renderSteps({ orderStatus: "missing" });
    expect(await screen.findByRole("link", { name: "Zamówienia klienta" })).toHaveAttribute(
      "href",
      "/clients/7?tab=zamowienia",
    );
    expect(screen.queryByRole("button", { name: /Poproś o potwierdzenie/ })).toBeNull();
  });

  it("anulowana umowa nie liczy się — panel znów prowadzi do Generatora", async () => {
    generated.mockResolvedValue([{ ...ROW, contract_status: "cancelled" }]);
    renderSteps();
    expect(await screen.findByRole("link", { name: "Otwórz Generator umów" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Poproś o potwierdzenie/ })).toBeNull();
  });

  it("tylko do odczytu: stan bez przycisków", async () => {
    generated.mockResolvedValue([]);
    renderSteps({ readOnly: true });
    await screen.findByText("Umowa wygenerowana");
    expect(screen.queryByRole("link", { name: "Otwórz Generator umów" })).toBeNull();
  });
});
