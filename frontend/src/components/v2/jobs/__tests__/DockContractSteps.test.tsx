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
vi.mock("@/components/v2/b2b-generator/esign/SendForSignatureDialog", () => ({
  SendForSignatureDialog: (p: { row: { contract_number: string } }) => (
    <div role="dialog" aria-label="okno wysyłki">
      Wysyłka umowy {p.row.contract_number}
    </div>
  ),
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

  it("bramka KRZ (0801): „Sprawdź w KRZ” zamiast „Czeka na podpis” i prośby do DL", async () => {
    // Ścieżka na stagingu 27.11.2026: nad bramką stało „Czeka na podpis od 1 dnia”,
    // choć umowa czeka na sprawdzenie w KRZ.
    generated.mockResolvedValue([
      {
        ...ROW,
        krz: {
          required: true,
          result: null,
          entry_kind: null,
          entry_label: null,
          entry_note: null,
          checked_at: null,
          checked_by_name: null,
          decision: null,
          decision_reason: null,
          decided_at: null,
          decided_by_name: null,
          nip_changed: false,
          block_reason: "Najpierw sprawdź Partnera w Krajowym Rejestrze Zadłużonych.",
          decider_names: [],
          can_record: true,
          can_decide: false,
        },
      },
    ]);
    renderSteps();
    expect(await screen.findByText("KRZ: nie sprawdzono")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sprawdź w KRZ" })).toBeInTheDocument();
    expect(screen.queryByText(/Czeka na podpis od/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Poproś o potwierdzenie podpisu" })).toBeNull();
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
    await screen.findByText("Umowa B2B z Generatora");
    expect(screen.queryByRole("link", { name: "Otwórz Generator umów" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Przesuń na „Zatrudniony”…" })).toBeNull();
  });

  // 20.10.2026: „czy zatrudnia tylko DL” i „czy bez zamówienia się da”.
  describe("przed zatrudnieniem — kto i co jest potrzebne", () => {
    it("mówi, że przesuwa każdy z zespołu, a zamówienie jest krokiem po zatrudnieniu", async () => {
      generated.mockResolvedValue([ROW]);
      renderSteps();
      expect(await screen.findByText("Do „Zatrudnionego”")).toBeInTheDocument();
      expect(screen.getByTestId("dock-hire-who")).toHaveTextContent(
        "Przesuwa każdy z zespołu rekrutacji. Zamówienie od klienta nie jest potrzebne.",
      );
      const after = screen.getByTestId("dock-after-hire");
      expect(after).toHaveTextContent("Po zatrudnieniu — nie blokuje ruchu");
      expect(after).toHaveTextContent("Zamówienie od klienta — po zatrudnieniu");
      expect(after).toHaveTextContent("Szkic powstanie sam przy zatrudnieniu");
    });

    it("prośba o podpis nie mówi, że zatrudnia tylko Delivery Lead", async () => {
      generated.mockResolvedValue([ROW]);
      renderSteps();
      expect(
        await screen.findByText(/Podpis tej umowy potwierdza osoba z uprawnieniem „Podpis B2B”/),
      ).toBeInTheDocument();
    });

    it("umowa poza Generatorem: „Przesuń na Zatrudniony…” woła ruch", async () => {
      generated.mockResolvedValue([]);
      const onMarkHired = vi.fn();
      renderSteps({ onMarkHired });
      fireEvent.click(await screen.findByRole("button", { name: "Przesuń na „Zatrudniony”…" }));
      expect(onMarkHired).toHaveBeenCalledTimes(1);
    });

    it("bez kolumny „Zatrudniony” do wyboru — bez przycisku", async () => {
      generated.mockResolvedValue([]);
      renderSteps();
      await screen.findByText("Umowa B2B z Generatora");
      expect(screen.queryByTestId("dock-hire-offline")).toBeNull();
    });
  });

  it("zatrudniony bez umowy z Generatora (np. umowa o pracę): bez „Wygeneruj umowę”", async () => {
    generated.mockResolvedValue([]);
    renderSteps({ orderStatus: "missing", onGenerate: vi.fn(), onMarkHired: vi.fn() });
    expect(await screen.findByRole("link", { name: "Zamówienia klienta" })).toBeInTheDocument();
    expect(screen.getByText("Umowa")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Umowa B2B z Generatora")).toBeNull());
    expect(screen.queryByRole("button", { name: "Wygeneruj umowę" })).toBeNull();
    expect(screen.queryByTestId("dock-hire-offline")).toBeNull();
  });
});

describe("DockContractSteps przy umowie w podpisie w NEXUSIE (etap 1b)", () => {
  it("pokazuje kroki podpisu i zamiast ręcznego „Zatrudniony” mówi, jak go odblokować", async () => {
    generated.mockResolvedValue([
      {
        ...ROW,
        esign: {
          request_id: 4,
          status: "contractor_signed",
          contractor_signed_at: "2026-10-21T10:14:00Z",
          completed_at: null,
          expires_at: "2026-11-04T10:00:00Z",
          company_signer_name: "Olaf",
        },
      },
    ]);
    renderSteps({ onMarkHired: vi.fn() });
    expect(await screen.findByText("W NEXUSIE")).toBeInTheDocument();
    expect(screen.getByText(/Kontraktor · 21\.10/)).toBeInTheDocument();
    expect(screen.getByText(/NEXUS potwierdzi podpis sam/)).toBeInTheDocument();
    expect(screen.getByTestId("dock-hire-esign-lock")).toHaveTextContent("Przejdź na zwykłą drogę");
    expect(screen.queryByTestId("dock-hire-offline")).not.toBeInTheDocument();
  });

  it("wycofana wysyłka wraca do zwykłej drogi", async () => {
    generated.mockResolvedValue([
      {
        ...ROW,
        esign: {
          request_id: 4,
          status: "withdrawn",
          contractor_signed_at: null,
          completed_at: null,
          expires_at: "2026-11-04T10:00:00Z",
          company_signer_name: "Olaf",
        },
      },
    ]);
    renderSteps({ onMarkHired: vi.fn() });
    expect(await screen.findByTestId("dock-hire-offline")).toBeInTheDocument();
    expect(screen.queryByTestId("dock-hire-esign-lock")).not.toBeInTheDocument();
  });
});

describe("DockContractSteps — wysyłka do podpisu w NEXUSIE jako główna akcja (22.11.2026)", () => {
  it("umowę do wysłania wysyła się z panelu, a droga mailowa zostaje pod spodem", async () => {
    generated.mockResolvedValue([{ ...ROW, can_send_esign: true, can_download: true }]);
    renderSteps();

    const send = await screen.findByRole("button", { name: "Wyślij do podpisu w NEXUSIE" });
    expect(send.className).toContain("bg-primary");
    expect(screen.getByText(/Czeka na wysyłkę do podpisu · 3 dni od wygenerowania/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz DOCX" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Poproś o potwierdzenie podpisu" })).toBeInTheDocument();

    fireEvent.click(send);
    expect(await screen.findByRole("dialog", { name: "okno wysyłki" })).toHaveTextContent(
      "Wysyłka umowy 1506/2026",
    );
  });

  it("z prawem potwierdzania „Oznacz jako podpisaną…” jest obrysowane, nie główne", async () => {
    generated.mockResolvedValue([{ ...ROW, can_send_esign: true, can_confirm_signed: true }]);
    renderSteps();

    await screen.findByRole("button", { name: "Wyślij do podpisu w NEXUSIE" });
    const confirm = screen.getByRole("button", { name: "Oznacz jako podpisaną…" });
    expect(confirm.className).not.toContain("bg-primary");
    expect(confirm.className).toContain("border");
  });

  it("bez prawa wysyłki albo tylko do odczytu zostaje dotychczasowy krok", async () => {
    generated.mockResolvedValue([{ ...ROW, can_send_esign: false }]);
    const { unmount } = renderSteps();
    expect(await screen.findByRole("button", { name: "Poproś o potwierdzenie podpisu" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Wyślij do podpisu w NEXUSIE" })).toBeNull();
    unmount();

    generated.mockResolvedValue([{ ...ROW, can_send_esign: true }]);
    renderSteps({ readOnly: true });
    await screen.findByText("Nr 1506/2026");
    expect(screen.queryByRole("button", { name: "Wyślij do podpisu w NEXUSIE" })).toBeNull();
  });
});
