/**
 * Wzory własne (asystent prawny, część B): sekcja „Wzory własne” w kreatorze
 * „Nowy dokument”, formularz dokumentu ze wzoru (braki przed wysłaniem),
 * lista wzorów (pusty stan tylko po udanym zapytaniu) i blokery zgłoszenia.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  prefill: vi.fn(),
  createDocument: vi.fn(),
  preview: vi.fn(),
  submit: vi.fn(),
  update: vi.fn(),
}));

vi.mock("@/lib/api/customTemplates", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/customTemplates")>();
  return {
    ...actual,
    customTemplatesApi: {
      ...actual.customTemplatesApi,
      prefill: (...a: unknown[]) => mocks.prefill(...a),
      createDocument: (...a: unknown[]) => mocks.createDocument(...a),
      preview: (...a: unknown[]) => mocks.preview(...a),
      submit: (...a: unknown[]) => mocks.submit(...a),
      update: (...a: unknown[]) => mocks.update(...a),
    },
  };
});

import { ToastProvider } from "@/components/Toast";
import { DocumentWizard } from "@/components/v2/b2b-generator/documents/DocumentWizard";
import type { DocumentTypesResponse } from "@/lib/api/b2bDocuments";
import type {
  CustomDocumentType,
  CustomFieldDef,
  CustomTemplateDetail,
} from "@/lib/api/customTemplates";

import { CustomTemplatesPanelView } from "../CustomTemplatesPanel";
import { TemplateStudio } from "../TemplateStudio";

function field(key: string, label: string, extra: Partial<CustomFieldDef> = {}): CustomFieldDef {
  return {
    key,
    label,
    kind: "text",
    group: "Partner",
    source: "manual",
    source_label: "ręcznie",
    required: false,
    sensitive: false,
    help: null,
    options: [],
    item_keys: [],
    ...extra,
  };
}

const TYPE: CustomDocumentType = {
  key: "custom:3",
  template_id: 3,
  version_id: 31,
  version_no: 2,
  label: "Umowa o szkolenie stacjonarne",
  description: "Trener z działalnością",
  kind: "contract",
  kind_label: "Umowa",
  client_scope: "all",
  client_ids: [],
  signatories: "both",
  signature_form: "written",
  approved_at: null,
  fields: [
    field("partner.nip", "NIP", { required: true }),
    field("fees.total", "Wynagrodzenie", { kind: "money", group: "Pieniądze", required: true }),
  ],
};

const TYPES: DocumentTypesResponse = {
  types: [],
  ref_labels: {},
  ref_defaults: {},
  mandate_forms: [],
  custom_types: [TYPE],
};

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
  mocks.prefill.mockResolvedValue({ values: {} });
});

describe("Nowy dokument → Wzory własne", () => {
  it("lists approved custom templates and opens their form", async () => {
    const onNew = vi.fn();
    wrap(<DocumentWizard typesData={TYPES} onClose={() => undefined} onNewTemplate={onNew} />);
    await userEvent.click(screen.getByRole("button", { name: /Nowy wzór z asystentem/ }));
    expect(onNew).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /Umowa o szkolenie stacjonarne/ }));
    expect(await screen.findByText("Wzór własny v2")).toBeInTheDocument();
    expect(screen.getByLabelText(/NIP/)).toBeInTheDocument();
  });

  it("does not send a document with missing or malformed fields", async () => {
    wrap(<DocumentWizard typesData={TYPES} initialType="custom:3" onClose={() => undefined} />);
    await userEvent.type(await screen.findByLabelText(/Wynagrodzenie/), "dużo");
    await userEvent.click(screen.getByRole("button", { name: /Pobierz DOCX/ }));
    expect(mocks.createDocument).not.toHaveBeenCalled();
    expect(await screen.findByText("Uzupełnij zaznaczone pola.")).toBeInTheDocument();
  });

  it("sends values with the chosen subject", async () => {
    mocks.createDocument.mockResolvedValue({ data: new Blob(["x"]), headers: {} });
    wrap(<DocumentWizard typesData={TYPES} initialType="custom:3" onClose={() => undefined} />);
    await userEvent.type(await screen.findByLabelText(/NIP/), "0000000000");
    await userEvent.type(screen.getByLabelText(/Wynagrodzenie/), "6200,50");
    await userEvent.click(screen.getByRole("button", { name: /Pobierz DOCX/ }));
    await waitFor(() => expect(mocks.createDocument).toHaveBeenCalled());
    expect(mocks.createDocument.mock.calls[0][0]).toBe(3);
    expect(mocks.createDocument.mock.calls[0][1]).toMatchObject({
      values: { "partner.nip": "0000000000", "fees.total": "6200,50" },
      candidate_id: null,
      job_id: null,
    });
  });
});

describe("Lista wzorów własnych", () => {
  it("shows the empty state only for an empty successful list", () => {
    const props = { onRetry: () => undefined, onOpen: () => undefined, onNew: () => undefined, canGenerate: true };
    const { rerender } = wrap(<CustomTemplatesPanelView state="error" error={new Error("x")} {...props} />);
    expect(screen.queryByText("Nie ma jeszcze wzorów własnych")).not.toBeInTheDocument();
    rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <CustomTemplatesPanelView state="empty" data={{ templates: [], is_admin: false }} {...props} />
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByText("Nie ma jeszcze wzorów własnych")).toBeInTheDocument();
  });
});

describe("Zapis i zatwierdzenie", () => {
  const detail: CustomTemplateDetail = {
    id: 5,
    withdrawn_at: null,
    withdrawn_by_name: null,
    withdrawn_reason: null,
    active: null,
    history: [],
    can_edit: true,
    can_review: false,
    can_withdraw: false,
    can_new_version: false,
    working: {
      id: 11,
      version_no: 1,
      status: "draft",
      status_label: "szkic",
      name: "Wzór",
      kind: "contract",
      kind_label: "Umowa",
      description: "",
      client_scope: "all",
      client_ids: [],
      signatories: "both",
      signature_form: "any",
      origin: "upload",
      base_key: null,
      instruction: null,
      ai_used: false,
      created_by_name: "Osoba Przykładowa",
      created_at: null,
      submitted_by_name: null,
      submitted_at: null,
      reviewed_by_name: null,
      reviewed_at: null,
      review_note: null,
      fields: [field("partner.nip", "NIP")],
      checks: [
        {
          key: "art53_pr_aut",
          state: "block",
          text: "Ustaw podpis na papierze albo kwalifikowany",
          cite: "art. 53 pr. aut.",
          cite_kind: "law",
          cite_state: "unverified",
        },
      ],
      problems: [],
      changes: [],
      warnings: [],
      unused_fields: [],
      preview_html: "<p>NIP <span class=\"tpl-field\">NIP</span></p>",
    },
  };

  it("blocks submit until the written signature form is chosen", async () => {
    mocks.update.mockResolvedValue(detail);
    mocks.submit.mockResolvedValue({ ...detail, working: { ...detail.working!, status: "pending" } });
    wrap(<TemplateStudio templateId={5} initialDetail={detail} onTemplate={() => undefined} onClose={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: /3\. Zapis i zatwierdzenie/ }));
    const send = screen.getByRole("button", { name: "Wyślij do zatwierdzenia" });
    expect(send).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "Na papierze albo kwalifikowany" }));
    expect(send).toBeEnabled();
    await userEvent.click(send);
    await waitFor(() => expect(mocks.submit).toHaveBeenCalledWith(5));
    expect(mocks.update.mock.calls[0][1]).toMatchObject({ signature_form: "written" });
  });
});
