/**
 * Zakładka „Umowa” rozwiniętego panelu osoby (04.10.2026): rekruter generuje
 * umowę w rekrutacji tym samym formularzem co w Generatorze, a przy
 * istniejącej umowie widzi stan, poprawkę pod tym samym numerem i podpis.
 */
import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const generated = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {},
  b2bGeneratorApi: {
    generated: (...a: unknown[]) => generated(...a),
    requestSignature: vi.fn(),
    downloadGenerated: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn() }),
}));
// Formularz i okno podpisu żyją w module Generatora i mają własne testy —
// tu liczy się, z jakimi propsami panel je otwiera.
vi.mock("@/components/v2/pages/B2BContractGeneratorV2", () => ({
  GeneratorForm: (p: {
    lockedPair?: boolean;
    prefillCandidateId?: number | null;
    prefillJobId?: number | null;
    editGeneratedId?: number | null;
  }) => (
    <div data-testid="generator-form">
      para {p.prefillCandidateId}/{p.prefillJobId} · zablokowana {String(p.lockedPair)} · edycja{" "}
      {String(p.editGeneratedId)}
    </div>
  ),
  ConfirmFullySignedDialog: () => <div role="dialog">okno podpisu</div>,
}));

import { AgreementPanelTab, liveAgreementRow } from "@/components/v2/b2b-generator/AgreementPanelTab";
import { useAuthStore } from "@/store/auth";

const ROW = {
  id: 501,
  candidate_id: 42,
  contract_number: "1506/2026",
  contract_status: "in_progress",
  signature_status: "unsigned",
  created_at: "2026-10-01T10:00:00Z",
  created_by_name: "Marek Dąb",
  can_confirm_signed: false,
  can_edit: true,
  can_download: true,
};

function renderTab(props: Partial<React.ComponentProps<typeof AgreementPanelTab>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AgreementPanelTab candidateId={42} jobId={10} readOnly={false} {...props} />
    </QueryClientProvider>,
  );
}

function loginAs(canGenerate: boolean) {
  useAuthStore.setState({
    user: {
      id: 3,
      role: "recruiter",
      effective_section_access: { sourcing: canGenerate ? "write" : "read" },
      effective_action_access: { b2b_contract_generator: canGenerate ? "generate" : "view" },
    },
  } as never);
}

beforeEach(() => {
  generated.mockReset();
  loginAs(true);
});

describe("AgreementPanelTab", () => {
  it("bez umowy: formularz Generatora z ustaloną parą", async () => {
    generated.mockResolvedValue([]);
    renderTab();
    expect(await screen.findByTestId("generator-form")).toHaveTextContent(
      "para 42/10 · zablokowana true · edycja null",
    );
  });

  it("bez uprawnienia do generowania: zdanie zamiast formularza", async () => {
    loginAs(false);
    generated.mockResolvedValue([]);
    renderTab();
    expect(await screen.findByText(/wymaga uprawnienia do Generatora/)).toBeInTheDocument();
    expect(screen.queryByTestId("generator-form")).toBeNull();
  });

  it("jest umowa: stan, „Popraw umowę” otwiera formularz pod tym samym numerem", async () => {
    generated.mockResolvedValue([ROW]);
    renderTab();
    expect(await screen.findByText("Umowa 1506/2026")).toBeInTheDocument();
    expect(screen.getByText(/przez Marek Dąb/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Poproś o potwierdzenie podpisu" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Popraw umowę" }));
    expect(await screen.findByTestId("generator-form")).toHaveTextContent("edycja 501");
    expect(screen.getByText(/numer zostaje ten sam/)).toBeInTheDocument();
  });

  it("bez prawa poprawki (serwer: can_edit=false) nie ma „Popraw umowę”", async () => {
    generated.mockResolvedValue([{ ...ROW, can_edit: false }]);
    renderTab();
    await screen.findByText("Umowa 1506/2026");
    expect(screen.queryByRole("button", { name: "Popraw umowę" })).toBeNull();
  });

  it("podpisana: bez poprawki i bez prośby o podpis", async () => {
    generated.mockResolvedValue([{ ...ROW, signature_status: "signed_both", contract_status: "active" }]);
    renderTab();
    expect(await screen.findByText("Podpisana obustronnie")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Popraw umowę" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Poproś o potwierdzenie/ })).toBeNull();
  });

  it("anulowana i zakończona umowa nie jest żywą umową pary", () => {
    expect(
      liveAgreementRow([{ ...ROW, contract_status: "cancelled" }] as never, 42),
    ).toBeNull();
    expect(liveAgreementRow([ROW] as never, 7)).toBeNull();
    expect(liveAgreementRow([ROW] as never, 42)?.id).toBe(501);
  });
});
