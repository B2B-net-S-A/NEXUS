/**
 * „Powiąż z kontraktem” przy aneksie do umowy z rejestru (audyt 13.10.2026):
 * okno szukało wyłącznie po numerze umowy wpisanym z góry i nie miało pola
 * wyszukiwania — przy umowie bez numeru albo gdy numer nie trafiał, zostawało
 * „Wpisz co najmniej dwa znaki” bez miejsca, gdzie je wpisać.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  subjects: vi.fn(),
  linkContract: vi.fn(),
}));

vi.mock("@/lib/api/b2bDocuments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/b2bDocuments")>();
  return {
    ...actual,
    b2bDocumentsApi: {
      ...actual.b2bDocumentsApi,
      subjects: (...a: unknown[]) => mocks.subjects(...a),
      linkContract: (...a: unknown[]) => mocks.linkContract(...a),
    },
  };
});

import { ToastProvider } from "@/components/Toast";
import { LinkContractDialog } from "@/components/v2/b2b-generator/documents/AnnexRegisterDialogs";
import type { DocumentItem, DocumentSubject } from "@/lib/api/b2bDocuments";

function annex(overrides: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id: 5,
    document_type: "annex_start_date",
    type_label: "Aneks — data rozpoczęcia",
    family: "annex",
    language: "pl",
    label: "Aneks — data rozpoczęcia z dnia 10.10.2026",
    document_date: "2026-10-10",
    parent_generated_contract_id: 41,
    parent_contract_number: null,
    contract_id: null,
    candidate_id: 11,
    partner_name: "Ewa Przykładowa",
    client_name: "Klient Testowy S.A.",
    status: "issued",
    signature_status: "unsigned",
    signed_at: null,
    effect_applied_at: null,
    effect_summary: null,
    created_by_name: "Osoba Testowa",
    created_at: "2026-10-10T09:40:00Z",
    requires_sensitive_input: false,
    sensitive_fields: [],
    can_edit: true,
    can_delete: true,
    can_confirm_signed: false,
    cancelled_reason: null,
    client_id: 3,
    person_name: "Ewa Przykładowa",
    partner_legal_name: null,
    partner_nip: null,
    external: false,
    effective_date: "2026-11-16",
    state: "waiting",
    change: { kind: "start_date", before: "2026-11-02", after: "2026-11-16" },
    can_restore: false,
    can_link_contract: true,
    signed_scan_document_id: null,
    ...overrides,
  };
}

function agreement(): DocumentSubject {
  return {
    kind: "agreement",
    parent_generated_contract_id: 41,
    contract_number: "EXCEL-7",
    source: "excel",
    agreement_status: "active",
    contract_id: null,
    contract_status: null,
    contract_start_date: null,
    contract_options: [
      { contract_id: 900, status: "active", start_date: "2026-07-06" },
    ],
    candidate_id: 11,
    person_name: "Ewa Przykładowa",
    partner_name: null,
    partner_nip: null,
    client_id: 3,
    client_name: "Klient Testowy S.A.",
  };
}

function renderDialog(item: DocumentItem) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <LinkContractDialog item={item} onClose={() => {}} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.subjects.mockReset();
  mocks.linkContract.mockReset();
  mocks.subjects.mockResolvedValue([agreement()]);
  mocks.linkContract.mockResolvedValue(annex({ contract_id: 900 }));
});

describe("Powiąż z kontraktem — aneks do umowy z rejestru", () => {
  it("umowa bez numeru: pole wyszukiwania pozwala znaleźć jej kontrakt po osobie", async () => {
    renderDialog(annex());
    const field = screen.getByRole("textbox", { name: "Umowa, osoba, firma albo NIP" });
    expect(field).toHaveValue("");

    await userEvent.type(field, "Przykładowa");
    const option = await screen.findByRole("button", { name: /Kontrakt #900/ });
    await waitFor(() =>
      expect(mocks.subjects).toHaveBeenLastCalledWith({
        documentType: "annex_start_date",
        q: "Przykładowa",
      }),
    );
    await userEvent.click(option);
    await userEvent.click(screen.getByRole("button", { name: "Powiąż" }));
    await waitFor(() => expect(mocks.linkContract).toHaveBeenCalledWith(5, 900));
  });

  it("numer umowy dalej jest podpowiedzią na start", async () => {
    renderDialog(annex({ parent_contract_number: "EXCEL-7" }));
    expect(
      screen.getByRole("textbox", { name: "Umowa, osoba, firma albo NIP" }),
    ).toHaveValue("EXCEL-7");
    expect(
      await screen.findByRole("button", { name: /Kontrakt #900/ }),
    ).toBeInTheDocument();
    expect(mocks.subjects).toHaveBeenCalledWith({
      documentType: "annex_start_date",
      q: "EXCEL-7",
    });
  });

  it("aneks bez umowy w rejestrze szuka jak dotąd po osobie", () => {
    renderDialog(
      annex({ parent_generated_contract_id: null, person_name: "Ewa Przykładowa" }),
    );
    expect(
      screen.getByRole("textbox", { name: "Osoba, firma albo NIP" }),
    ).toHaveValue("Ewa Przykładowa");
  });
});
