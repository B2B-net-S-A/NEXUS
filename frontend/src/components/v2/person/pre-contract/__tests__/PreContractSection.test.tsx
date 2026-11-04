import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PreContractPair, PreContractRequest } from "@/lib/api/preContracts";

const mocks = vi.hoisted(() => ({ pair: vi.fn() }));

vi.mock("@/lib/api/preContracts", async (orig) => {
  const actual = await orig<typeof import("@/lib/api/preContracts")>();
  return {
    ...actual,
    usePreContractPair: () => ({
      isLoading: false,
      isError: false,
      isSuccess: true,
      data: mocks.pair(),
      refetch: vi.fn(),
    }),
  };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() }),
}));

import { PreContractSection, preContractSteps } from "@/components/v2/person/pre-contract/PreContractSection";

function request(over: Partial<PreContractRequest> = {}): PreContractRequest {
  return {
    id: 1,
    candidate_id: 10,
    candidate_name: "Anna Nowak",
    job_id: 20,
    job_title: "Backend Java",
    client_name: "Klient Testowy",
    state: "requested",
    state_label: "Prośba — nie wystawiona",
    badge: { state: "requested", label: "Przedwstępna przed wysłaniem CV — nie wystawiona", tone: "missing", detail: "" },
    is_open: true,
    needed_before: "cv_sent",
    needed_before_label: "przed wysłaniem CV",
    requested_by: { id: 2, name: "Paweł R." },
    requested_at: "2026-10-20T08:00:00Z",
    assignee: { id: 3, name: "Kasia M." },
    watchers: [
      { id: 2, name: "Paweł R." },
      { id: 3, name: "Kasia M." },
    ],
    watching: false,
    can_withdraw: false,
    can_decide_penalty: false,
    events: [
      { id: 1, kind: "requested", label: "Prośba", at: "2026-10-20T08:00:00Z", actor: { id: 2, name: "Paweł R." } },
    ],
    ...over,
  };
}

function renderSection(pair: PreContractPair, readOnly = false) {
  mocks.pair.mockReturnValue(pair);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PreContractSection candidateId={10} jobId={20} personLabel="Anna Nowak · Backend Java" readOnly={readOnly} />
    </QueryClientProvider>,
  );
}

describe("PreContractSection", () => {
  beforeEach(() => mocks.pair.mockReset());

  it("bez prośby proponuje „Poproś o przedwstępną”", () => {
    renderSection({ current: null, history: [], documents: [] });
    expect(screen.getByText("Nikt nie prosił o umowę przedwstępną dla tej osoby.")).toBeInTheDocument();
    expect(screen.getByTestId("pre-contract-request")).toBeInTheDocument();
  });

  it("prośba: kto prosił, kto wystawia, „Wystaw umowę” i podpięcie umowy z Generatora", () => {
    renderSection({
      current: request({ can_withdraw: true }),
      history: [],
      documents: [{ id: 7, document_type: "preliminary_cez", document_date: "2026-10-21", status: "issued", signed: false, linked: false }],
    });
    expect(screen.getByTestId("pre-contract-badge")).toHaveTextContent("nie wystawiona");
    expect(screen.getByText("Kasia M.")).toBeInTheDocument();
    expect(screen.getByTestId("pre-contract-issue")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Podepnij umowę z 21.10.2026" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wycofaj prośbę" })).toBeInTheDocument();
  });

  it("podpisana: rezygnacja kandydata i „Zrealizowana”, bez podmiany plików", () => {
    renderSection({
      current: request({
        state: "signed",
        document_id: 7,
        sent_at: "2026-10-21T08:00:00Z",
        candidate_signed_at: "2026-10-22T08:00:00Z",
        candidate_signature_form: "trusted_profile",
        candidate_signature_form_label: "profil zaufany",
        candidate_file_name: "a.pdf",
        company_signed_at: "2026-10-23T08:00:00Z",
        company_file_name: "b.pdf",
        valid_until: "2026-12-20",
        badge: { state: "signed", label: "Przedwstępna do 20.12", tone: "ok", detail: "" },
      }),
      history: [],
      documents: [],
    });
    expect(screen.getByText("Kandydat podpisał — profil zaufany")).toBeInTheDocument();
    expect(screen.getByText("Obowiązuje do 20.12.2026")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kandydat zrezygnował…" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Wgraj/ })).not.toBeInTheDocument();
  });

  it("tylko odczyt: stan bez przycisków", () => {
    renderSection({ current: request(), history: [], documents: [] }, true);
    expect(screen.getByTestId("pre-contract-badge")).toBeInTheDocument();
    expect(screen.queryByTestId("pre-contract-issue")).not.toBeInTheDocument();
  });
});

describe("preContractSteps", () => {
  it("opisuje krok z historii: data i osoba", () => {
    const steps = preContractSteps(request());
    expect(steps[0]).toMatchObject({ key: "requested", done: true, meta: "20.10 · Paweł R." });
    expect(steps.filter((s) => s.done)).toHaveLength(1);
  });
});
