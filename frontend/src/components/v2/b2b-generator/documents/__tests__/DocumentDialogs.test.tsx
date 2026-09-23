import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  effects: vi.fn(),
  confirmSigned: vi.fn(),
  redownload: vi.fn(),
  prefill: vi.fn(),
  create: vi.fn(),
  downloadBlob: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {},
  b2bGeneratorApi: { generated: vi.fn() },
}));

vi.mock("@/lib/api/b2bDocuments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/b2bDocuments")>();
  return {
    ...actual,
    b2bDocumentsApi: {
      ...actual.b2bDocumentsApi,
      effects: (...a: unknown[]) => mocks.effects(...a),
      confirmSigned: (...a: unknown[]) => mocks.confirmSigned(...a),
      redownload: (...a: unknown[]) => mocks.redownload(...a),
      prefill: (...a: unknown[]) => mocks.prefill(...a),
      create: (...a: unknown[]) => mocks.create(...a),
    },
  };
});

vi.mock("@/lib/cv-generator", () => ({
  downloadBlob: (...a: unknown[]) => mocks.downloadBlob(...a),
  parseDispositionFilename: (_d: string, fallback: string) => fallback,
}));

import { ToastProvider } from "@/components/Toast";
import {
  ConfirmSignedDialog,
  RedownloadDialog,
} from "@/components/v2/b2b-generator/documents/DocumentDialogs";
import { DocumentWizard } from "@/components/v2/b2b-generator/documents/DocumentWizard";
import type {
  DocumentFieldDef,
  DocumentItem,
  DocumentTypeDef,
} from "@/lib/api/b2bDocuments";

function field(key: string, label: string, extra: Partial<DocumentFieldDef> = {}): DocumentFieldDef {
  return {
    key,
    label,
    kind: "text",
    required: false,
    sensitive: false,
    help: null,
    options: [],
    show_if: null,
    group: "document",
    ...extra,
  };
}

const PRELIMINARY: DocumentTypeDef = {
  key: "preliminary_cez",
  label: "Umowa przedwstępna",
  family: "preliminary",
  languages: ["pl"],
  parent: "none",
  description: "",
  effect_label: "Brak zmian w kontraktach.",
  signatories: "partner_and_company",
  uses_refs: false,
  fields: [
    field("document_date", "Data dokumentu", { kind: "date", required: true }),
    field("pesel", "PESEL", { required: true, sensitive: true, group: "partner" }),
  ],
};

const TERMINATION: DocumentTypeDef = {
  ...PRELIMINARY,
  key: "termination_agreement",
  label: "Porozumienie o rozwiązaniu umowy",
  family: "termination",
  parent: "b2b",
  uses_refs: true,
  fields: [
    field("document_date", "Data dokumentu", { kind: "date", required: true }),
    field("partner_name", "Imię i nazwisko", { required: true, group: "partner" }),
  ],
};

function item(overrides: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id: 5,
    document_type: "preliminary_cez",
    type_label: "Umowa przedwstępna",
    family: "preliminary",
    language: "pl",
    label: "Umowa przedwstępna z dnia 23.09.2026",
    document_date: "2026-09-23",
    parent_generated_contract_id: null,
    parent_contract_number: null,
    contract_id: null,
    candidate_id: 1,
    partner_name: "Anna",
    client_name: "CeZ",
    status: "issued",
    signature_status: "unsigned",
    signed_at: null,
    effect_applied_at: null,
    effect_summary: null,
    created_by_name: null,
    created_at: null,
    requires_sensitive_input: true,
    sensitive_fields: ["pesel"],
    can_edit: true,
    can_delete: true,
    can_confirm_signed: true,
    cancelled_reason: null,
    ...overrides,
  };
}

function renderWith(ui: React.ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

function blobError(status: number, detail: unknown) {
  return {
    response: {
      status,
      data: new Blob([JSON.stringify({ detail })], { type: "application/json" }),
    },
  };
}

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
});

describe("Oznacz jako podpisany", () => {
  it("blokada z serwera wyłącza potwierdzenie", async () => {
    mocks.effects.mockResolvedValue({
      effect_label: "Kontrakt dostanie datę zakończenia.",
      changes: ["Umowa w rejestrze: „Zakończona”."],
      warnings: [],
      blockers: ["Kontrakt ma otwartą sprawę offboardingu MD."],
    });
    renderWith(<ConfirmSignedDialog item={item()} onClose={() => {}} />);
    expect(await screen.findByText("Kontrakt ma otwartą sprawę offboardingu MD.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Potwierdź podpis obu stron" })).toBeDisabled();
    expect(mocks.confirmSigned).not.toHaveBeenCalled();
  });

  it("bez blokad pokazuje zmiany i potwierdza", async () => {
    mocks.effects.mockResolvedValue({
      effect_label: "…",
      changes: ["Nowa stawka od 01.10.2026."],
      warnings: ["Kontrakt bez harmonogramu."],
      blockers: [],
    });
    mocks.confirmSigned.mockResolvedValue(item({ status: "signed" }));
    const onClose = vi.fn();
    renderWith(<ConfirmSignedDialog item={item()} onClose={onClose} />);
    expect(await screen.findByText("Nowa stawka od 01.10.2026.")).toBeInTheDocument();
    expect(screen.getByText("Kontrakt bez harmonogramu.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Potwierdź podpis obu stron" }));
    await waitFor(() => expect(mocks.confirmSigned).toHaveBeenCalledWith(5));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe("Ponowne pobranie z danymi wrażliwymi", () => {
  it("wysyła tylko pola wrażliwe i pokazuje 422 przy polu", async () => {
    mocks.redownload.mockRejectedValueOnce(
      blobError(422, {
        code: "sensitive_values_required",
        message: "Tych danych nie przechowujemy — podaj je, żeby pobrać dokument: PESEL.",
        missing: ["PESEL"],
      }),
    );
    renderWith(<RedownloadDialog item={item()} type={PRELIMINARY} onClose={() => {}} />);
    // Formularz okna zna wyłącznie pola wrażliwe.
    expect(screen.queryByLabelText(/Data dokumentu/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Pobierz DOCX" }));
    expect(await screen.findByText(/podaj je, żeby pobrać dokument: PESEL/)).toBeInTheDocument();
    expect(screen.getByLabelText(/PESEL/)).toHaveAttribute("aria-invalid", "true");

    mocks.redownload.mockResolvedValueOnce({ data: new Blob(["x"]), headers: {} });
    await userEvent.type(screen.getByLabelText(/PESEL/), "90010112345");
    await userEvent.click(screen.getByRole("button", { name: "Pobierz DOCX" }));
    await waitFor(() => expect(mocks.redownload).toHaveBeenLastCalledWith(5, { pesel: "90010112345" }));
    await waitFor(() => expect(mocks.downloadBlob).toHaveBeenCalled());
  });
});

describe("Kreator — błąd 422 z serwera", () => {
  it("pokazuje komunikat i oznacza brakujące pole", async () => {
    mocks.prefill.mockResolvedValue({
      values: { document_date: "2026-09-23", partner_name: "Anna" },
      base: { contract_number: "1234/2026" },
      needs_refs: false,
      ref_defaults: {},
      languages: ["pl"],
      default_language: "pl",
    });
    mocks.create.mockRejectedValue(
      blobError(422, {
        code: "document_fields_missing",
        message: "Uzupełnij: Imię i nazwisko.",
        missing: ["Imię i nazwisko"],
      }),
    );
    renderWith(
      <DocumentWizard
        typesData={{ types: [TERMINATION], ref_labels: {}, ref_defaults: {} }}
        initialType="termination_agreement"
        initialParentId={12}
        onClose={() => {}}
      />,
    );
    const name = await screen.findByLabelText(/Imię i nazwisko/);
    expect(name).toHaveValue("Anna");
    await userEvent.click(screen.getByRole("button", { name: /Pobierz DOCX/ }));
    expect(await screen.findByText("Uzupełnij: Imię i nazwisko.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Imię i nazwisko/)).toHaveAttribute("aria-invalid", "true");
    expect(mocks.create).toHaveBeenCalledWith({
      document_type: "termination_agreement",
      language: "pl",
      parent_generated_contract_id: 12,
      values: { document_date: "2026-09-23", partner_name: "Anna" },
    });
  });

  it("puste wymagane pole zatrzymuje wysyłkę po stronie przeglądarki", async () => {
    mocks.prefill.mockResolvedValue({
      values: { document_date: "2026-09-23" },
      base: { contract_number: "1234/2026" },
      needs_refs: false,
      ref_defaults: {},
      languages: ["pl"],
      default_language: "pl",
    });
    renderWith(
      <DocumentWizard
        typesData={{ types: [TERMINATION], ref_labels: {}, ref_defaults: {} }}
        initialType="termination_agreement"
        initialParentId={12}
        onClose={() => {}}
      />,
    );
    await screen.findByLabelText(/Imię i nazwisko/);
    await userEvent.click(screen.getByRole("button", { name: /Pobierz DOCX/ }));
    expect(await screen.findByText("Uzupełnij: Imię i nazwisko.")).toBeInTheDocument();
    expect(mocks.create).not.toHaveBeenCalled();
  });
});
