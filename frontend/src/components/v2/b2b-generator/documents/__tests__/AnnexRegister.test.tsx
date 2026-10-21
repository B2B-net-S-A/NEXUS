/**
 * Rejestr aneksów (13.10.2026): lista w zakładce „Generator aneksów”, jedno
 * wyszukiwanie osoby zamiast „Umowa spoza Nexusa”, podpis ze skanem
 * i etykieta aneksu na wierszu umowy.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  types: vi.fn(),
  effects: vi.fn(),
  confirmSigned: vi.fn(),
  uploadSignedScan: vi.fn(),
  restore: vi.fn(),
  subjects: vi.fn(),
  history: vi.fn(),
  clients: vi.fn(),
  seesContracts: vi.fn(),
}));

vi.mock("@/store/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/store/auth")>();
  return { ...actual, canManageOrderLifecycle: () => mocks.seesContracts() };
});

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: (...a: unknown[]) => mocks.clients(...a) },
  api: {},
  b2bGeneratorApi: { generated: vi.fn() },
}));

vi.mock("@/lib/api/b2bDocuments", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/b2bDocuments")>();
  return {
    ...actual,
    b2bDocumentsApi: {
      ...actual.b2bDocumentsApi,
      list: (...a: unknown[]) => mocks.list(...a),
      types: (...a: unknown[]) => mocks.types(...a),
      effects: (...a: unknown[]) => mocks.effects(...a),
      confirmSigned: (...a: unknown[]) => mocks.confirmSigned(...a),
      uploadSignedScan: (...a: unknown[]) => mocks.uploadSignedScan(...a),
      restore: (...a: unknown[]) => mocks.restore(...a),
      subjects: (...a: unknown[]) => mocks.subjects(...a),
      history: (...a: unknown[]) => mocks.history(...a),
    },
  };
});

import { ToastProvider } from "@/components/Toast";
import { AnnexRegister } from "@/components/v2/b2b-generator/documents/AnnexRegister";
import {
  AnnexSubjectPicker,
  EMPTY_ANNEX_CHOICE,
  annexChoiceReady,
  choiceFromSubject,
  type AnnexSubjectChoice,
} from "@/components/v2/b2b-generator/documents/AnnexSubjectPicker";
import { ConfirmSignedDialog } from "@/components/v2/b2b-generator/documents/DocumentDialogs";
import {
  RegisterAnnexLabel,
  RegisterStartDate,
} from "@/components/v2/b2b-generator/RegisterAnnexLabel";
import type {
  DocumentItem,
  DocumentSubject,
  DocumentTypeDef,
} from "@/lib/api/b2bDocuments";

const RATE_TYPE: DocumentTypeDef = {
  key: "annex_rate_change",
  label: "Aneks — zmiana stawki",
  family: "annex",
  languages: ["pl"],
  parent: "b2b",
  fields: [],
  effect_label: "",
  description: "",
  signatories: "both",
  uses_refs: false,
  allows_external: true,
  legacy_languages: [],
};
const DELEGATE_TYPE: DocumentTypeDef = {
  ...RATE_TYPE,
  key: "annex_subcontractor",
  allows_external: false,
};

function annex(overrides: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id: 5,
    document_type: "annex_rate_change",
    type_label: "Aneks — zmiana stawki",
    family: "annex",
    language: "pl",
    label: "Aneks — zmiana stawki z dnia 10.10.2026",
    document_date: "2026-10-10",
    parent_generated_contract_id: null,
    parent_contract_number: null,
    contract_id: 651,
    candidate_id: 11,
    partner_name: "Piotr Zając",
    client_name: "Ubezpieczenia Alfa S.A.",
    status: "issued",
    signature_status: "unsigned",
    signed_at: null,
    effect_applied_at: null,
    effect_summary: null,
    created_by_name: "Kamil Dudek",
    created_at: "2026-10-10T09:40:00Z",
    requires_sensitive_input: false,
    sensitive_fields: [],
    can_edit: true,
    can_delete: true,
    can_confirm_signed: true,
    cancelled_reason: null,
    client_id: 3,
    person_name: "Piotr Zając",
    partner_legal_name: "ZAJĄC IT Piotr Zając",
    partner_nip: "5213900011",
    external: true,
    effective_date: "2026-11-01",
    state: "waiting",
    change: {
      kind: "rate",
      hidden: false,
      currency: "PLN",
      items: [{ rate: 150, from: null, to: null }],
      before: [{ rate: 140, from: null, to: null }],
    },
    can_restore: false,
    can_link_contract: false,
    signed_scan_document_id: null,
    ...overrides,
  };
}

function subject(overrides: Partial<DocumentSubject> = {}): DocumentSubject {
  return {
    kind: "contract",
    parent_generated_contract_id: null,
    contract_number: null,
    source: null,
    agreement_status: null,
    contract_id: 651,
    contract_status: "active",
    contract_start_date: "2026-07-06",
    contract_options: [],
    candidate_id: 11,
    person_name: "Piotr Zając",
    partner_name: "ZAJĄC IT Piotr Zając",
    partner_nip: "5213900011",
    client_id: 3,
    client_name: "Ubezpieczenia Alfa S.A.",
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

function register() {
  return <AnnexRegister search="" onSearch={() => {}} onEdit={() => {}} />;
}

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
  mocks.types.mockResolvedValue({ types: [RATE_TYPE], ref_labels: {}, ref_defaults: {}, mandate_forms: [] });
  mocks.seesContracts.mockReturnValue(true);
});

describe("Rejestr aneksów", () => {
  it("pyta tylko o aneksy i mówi, dla kogo, jaki aneks i w jakim stanie", async () => {
    mocks.list.mockResolvedValue([
      annex(),
      annex({
        id: 6,
        document_type: "annex_start_date",
        parent_generated_contract_id: 41,
        parent_contract_number: "1541/2026",
        contract_id: 712,
        external: false,
        person_name: "Ewa Lis",
        partner_legal_name: null,
        partner_nip: "7123500066",
        status: "signed",
        signature_status: "signed_both",
        state: "signed_pending",
        effective_date: "2026-11-16",
        can_confirm_signed: false,
        can_edit: false,
        can_delete: false,
        change: { kind: "start_date", before: "2026-11-02", after: "2026-11-16" },
      }),
      annex({
        id: 7,
        person_name: "Tomasz Wrona",
        status: "cancelled",
        state: "cancelled",
        cancelled_reason: "Partner nie podpisał",
        can_confirm_signed: false,
        can_edit: false,
        can_delete: false,
        can_restore: true,
      }),
    ]);
    renderWith(register());

    // Wiersz szukany po osobie: nazwy stanów są też opcjami filtra nad tabelą.
    const waiting = (await screen.findByRole("link", { name: "Piotr Zając" })).closest("tr")!;
    expect(within(waiting).getByText("Czeka na podpis")).toBeInTheDocument();
    expect(mocks.list).toHaveBeenCalledWith(
      expect.objectContaining({ family: ["annex"] }),
    );
    expect(within(waiting).getByText("Umowa spoza Nexusa")).toBeInTheDocument();
    expect(within(waiting).getByText("ZAJĄC IT Piotr Zając · NIP 5213900011")).toBeInTheDocument();
    expect(within(waiting).getByText("Zmiana stawki")).toBeInTheDocument();
    expect(within(waiting).getByText("140,00")).toHaveClass("line-through");
    expect(within(waiting).getByText("150,00 zł/h")).toBeInTheDocument();
    expect(within(waiting).getByText("01.11.2026")).toBeInTheDocument();
    expect(within(waiting).getByRole("link", { name: "Kontrakt #651" })).toHaveAttribute(
      "href",
      "/contracts/651?tab=amendments",
    );
    expect(
      within(waiting).getByRole("button", { name: "Oznacz jako podpisany" }),
    ).toBeInTheDocument();

    // Podpisany przed dniem wejścia w życie jeszcze nie „obowiązuje”.
    const pending = screen.getByText("Umowa 1541/2026").closest("tr")!;
    expect(within(pending).getByText("Podpisany")).toBeInTheDocument();
    expect(within(pending).getByText("wejdzie w życie 16.11.2026")).toBeInTheDocument();
    expect(within(pending).getByText("02.11.2026")).toHaveClass("line-through");
    expect(
      within(pending).queryByRole("button", { name: "Oznacz jako podpisany" }),
    ).not.toBeInTheDocument();

    const cancelled = screen.getByRole("link", { name: "Tomasz Wrona" }).closest("tr")!;
    expect(within(cancelled).getByText("Anulowany")).toBeInTheDocument();
    expect(within(cancelled).getByText("Partner nie podpisał")).toBeInTheDocument();
  });

  it("aneks „Bez kontraktu” czeka na powiązanie, a kwoty bez wglądu w stawki znikają", async () => {
    mocks.list.mockResolvedValue([
      annex({
        contract_id: null,
        can_confirm_signed: false,
        can_link_contract: true,
        change: { kind: "rate", hidden: true },
      }),
    ]);
    renderWith(register());

    const row = (await screen.findByRole("link", { name: "Piotr Zając" })).closest("tr")!;
    expect(within(row).getByText("Czeka na podpis")).toBeInTheDocument();
    expect(within(row).getByText("bez kontraktu")).toBeInTheDocument();
    expect(within(row).getByText("podpis po powiązaniu z kontraktem")).toBeInTheDocument();
    expect(
      within(row).getByRole("button", { name: "Powiąż z kontraktem" }),
    ).toBeInTheDocument();
    expect(
      within(row).queryByRole("button", { name: "Oznacz jako podpisany" }),
    ).not.toBeInTheDocument();
    expect(within(row).getByText("Zmiana stawki")).toBeInTheDocument();
    expect(within(row).queryByText(/zł\/h/)).not.toBeInTheDocument();
  });

  it("awaria listy nie wygląda jak pusty rejestr", async () => {
    mocks.list.mockRejectedValue({ response: { status: 500, data: {} } });
    renderWith(register());
    expect(await screen.findByText("Nie udało się wczytać aneksów")).toBeInTheDocument();
    expect(screen.queryByText("Nie ma jeszcze aneksów")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
  });

  it("pusty rejestr mówi, jak przygotować aneks", async () => {
    mocks.list.mockResolvedValue([]);
    renderWith(register());
    expect(await screen.findByText("Nie ma jeszcze aneksów")).toBeInTheDocument();
  });

  it("anulowany aneks da się przywrócić z menu wiersza", async () => {
    const cancelled = annex({
      status: "cancelled",
      state: "cancelled",
      can_confirm_signed: false,
      can_edit: false,
      can_delete: false,
      can_restore: true,
    });
    mocks.list.mockResolvedValue([cancelled]);
    mocks.restore.mockResolvedValue(annex());
    renderWith(register());

    await userEvent.click(
      await screen.findByRole("button", { name: /Więcej akcji/ }),
    );
    await userEvent.click(await screen.findByRole("menuitem", { name: "Przywróć" }));
    await waitFor(() => expect(mocks.restore).toHaveBeenCalledWith(5));
  });
});

describe("Dla kogo jest aneks", () => {
  it("umowa z rejestru niesie swój kontrakt; przy kilku trzeba wskazać", () => {
    const linked = choiceFromSubject(
      subject({
        kind: "agreement",
        parent_generated_contract_id: 41,
        contract_number: "1541/2026",
        contract_id: 712,
      }),
    );
    expect(linked).toMatchObject({
      parentId: 41,
      parentLabel: "1541/2026 — Piotr Zając",
      contractId: 712,
      needsContractPick: false,
    });

    const options = [
      { contract_id: 7, status: "active", start_date: null },
      { contract_id: 8, status: "active", start_date: null },
    ];
    const several = subject({
      kind: "agreement",
      parent_generated_contract_id: 42,
      contract_number: "264A",
      contract_id: null,
      contract_options: options,
    });
    expect(choiceFromSubject(several)).toMatchObject({
      contractId: null,
      needsContractPick: true,
    });
    expect(annexChoiceReady(RATE_TYPE, choiceFromSubject(several))).toBe(false);
    expect(annexChoiceReady(RATE_TYPE, choiceFromSubject(several, 8))).toBe(true);
    // Jedyny trwający kontrakt osoby wiąże się z umową sam.
    expect(
      choiceFromSubject({ ...several, contract_options: [options[0]] }),
    ).toMatchObject({ contractId: 7, needsContractPick: false });
  });

  it("bez kontraktu aneks wymaga klienta, a typ bez tej ścieżki — umowy", () => {
    const without: AnnexSubjectChoice = { ...EMPTY_ANNEX_CHOICE, withoutContract: true };
    expect(annexChoiceReady(RATE_TYPE, without)).toBe(false);
    expect(annexChoiceReady(RATE_TYPE, { ...without, clientId: 3 })).toBe(true);
    expect(annexChoiceReady(RATE_TYPE, choiceFromSubject(subject()))).toBe(true);
    // „Osoba skierowana” cytuje paragrafy umowy z rejestru.
    expect(annexChoiceReady(DELEGATE_TYPE, choiceFromSubject(subject()))).toBe(false);
    expect(annexChoiceReady(DELEGATE_TYPE, { ...without, clientId: 3 })).toBe(false);
  });

  it("jedno wyszukiwanie pokazuje kontrakt bez umowy w rejestrze i pozwala go wybrać", async () => {
    mocks.subjects.mockResolvedValue([subject()]);
    const onChoice = vi.fn();
    renderWith(
      <AnnexSubjectPicker
        type={RATE_TYPE}
        choice={EMPTY_ANNEX_CHOICE}
        onChoice={onChoice}
      />,
    );
    expect(screen.getByText(/Wpisz co najmniej dwa znaki/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Dla kogo jest aneks?"), "Zając");

    const option = await screen.findByRole("button", { name: /Kontrakt #651/ });
    expect(within(option).getByText("umowa spoza Nexusa")).toBeInTheDocument();
    expect(mocks.subjects).toHaveBeenCalledWith({
      documentType: "annex_rate_change",
      q: "Zając",
    });
    await userEvent.click(option);
    expect(onChoice).toHaveBeenCalledWith(
      expect.objectContaining({ parentId: null, contractId: 651 }),
    );
    expect(
      screen.getByRole("button", { name: "Tej osoby nie ma w kontraktach NEXUSA" }),
    ).toBeInTheDocument();
  });

  it("bez prawa edycji kontraktów wybór nie twierdzi, że osoby nie ma w kontraktach", async () => {
    // Serwer nie pokazuje takiej osobie kontraktów — „nie ma w kontraktach
    // NEXUSA” byłoby zgadywaniem, a powiązać aneks musi ktoś inny.
    mocks.seesContracts.mockReturnValue(false);
    mocks.subjects.mockResolvedValue([
      subject({
        kind: "agreement",
        parent_generated_contract_id: 12,
        contract_number: "1700/2026",
        contract_id: null,
        contract_status: null,
        contract_start_date: null,
      }),
    ]);
    renderWith(
      <AnnexSubjectPicker
        type={RATE_TYPE}
        choice={EMPTY_ANNEX_CHOICE}
        onChoice={() => {}}
      />,
    );
    expect(screen.getByText(/pokażemy umowy tej osoby z rejestru/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Tej osoby nie ma w kontraktach NEXUSA" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Umowy tej osoby nie ma w rejestrze" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/powiąże go osoba prowadząca kontrakty/),
    ).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Dla kogo jest aneks?"), "1700");
    const option = await screen.findByRole("button", { name: /Umowa 1700\/2026/ });
    expect(
      within(option).getByText(/Umowa bez powiązanego kontraktu/),
    ).toBeInTheDocument();
  });

  it("typ bez ścieżki „spoza Nexusa” nie proponuje aneksu bez kontraktu", () => {
    renderWith(
      <AnnexSubjectPicker
        type={DELEGATE_TYPE}
        choice={EMPTY_ANNEX_CHOICE}
        onChoice={() => {}}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Tej osoby nie ma w kontraktach NEXUSA" }),
    ).not.toBeInTheDocument();
  });
});

describe("Podpis ze skanem", () => {
  const scan = () =>
    new File(["%PDF-1.4"], "aneks-podpisany.pdf", { type: "application/pdf" });

  beforeEach(() => {
    mocks.effects.mockResolvedValue({
      effect_label: "",
      changes: ["Stawka Partnera 150 PLN/h od 01.11.2026."],
      warnings: [],
      blockers: [],
    });
  });

  it("najpierw zapisuje podpis, potem wysyła skan", async () => {
    mocks.confirmSigned.mockResolvedValue(annex({ status: "signed" }));
    mocks.uploadSignedScan.mockResolvedValue(annex({ status: "signed" }));
    const onClose = vi.fn();
    renderWith(<ConfirmSignedDialog item={annex()} onClose={onClose} />);

    const file = scan();
    await userEvent.upload(
      await screen.findByLabelText("Skan podpisanego aneksu"),
      file,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Potwierdź podpis obu stron" }),
    );
    await waitFor(() => expect(mocks.uploadSignedScan).toHaveBeenCalledWith(5, file));
    expect(mocks.confirmSigned).toHaveBeenCalledWith(5);
    expect(mocks.confirmSigned.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.uploadSignedScan.mock.invocationCallOrder[0],
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("nieudany skan nie cofa podpisu — okno mówi, gdzie go dołączyć", async () => {
    mocks.confirmSigned.mockResolvedValue(annex({ status: "signed" }));
    mocks.uploadSignedScan.mockRejectedValue({
      response: { status: 415, data: { detail: "Zły format pliku." } },
    });
    const onClose = vi.fn();
    renderWith(<ConfirmSignedDialog item={annex()} onClose={onClose} />);

    await userEvent.upload(
      await screen.findByLabelText("Skan podpisanego aneksu"),
      scan(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Potwierdź podpis obu stron" }),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(
      await screen.findByText(/oznaczony jako podpisany, ale skan nie został zapisany/),
    ).toBeInTheDocument();
  });

  it("plik, który nie jest skanem, blokuje potwierdzenie przed wysyłką", async () => {
    renderWith(<ConfirmSignedDialog item={annex()} onClose={() => {}} />);
    const word = new File(["PK"], "aneks.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    await userEvent.upload(
      await screen.findByLabelText("Skan podpisanego aneksu"),
      word,
      { applyAccept: false },
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Skan podpisanego aneksu musi być plikiem PDF, JPG albo PNG.",
    );
    expect(
      screen.getByRole("button", { name: "Potwierdź podpis obu stron" }),
    ).toBeDisabled();
    expect(mocks.confirmSigned).not.toHaveBeenCalled();
  });

  it("aneks bez kontraktu i dokument spoza aneksów nie mają pola skanu", async () => {
    renderWith(
      <ConfirmSignedDialog item={annex({ contract_id: null })} onClose={() => {}} />,
    );
    expect(
      await screen.findByText("Stawka Partnera 150 PLN/h od 01.11.2026."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Skan podpisanego aneksu")).not.toBeInTheDocument();
  });
});

describe("Etykieta aneksu na wierszu umowy", () => {
  it("najnowszy aneks, jego stan i licznik pozostałych", () => {
    render(
      <RegisterAnnexLabel
        row={{
          contract_number: "1538/2026",
          latest_annex: {
            document_id: 9,
            document_type: "annex_rate_change",
            state: "in_force",
            effective_date: "2026-11-01",
          },
          annex_count: 3,
          annex_rates: [
            { rate: 150, from: null, to: null, client_id: null, client_name: null },
          ],
        }}
      />,
    );
    expect(screen.getByText("Aneks: stawka 150 zł/h · obowiązuje")).toBeInTheDocument();
    expect(screen.getByText("od 01.11.2026")).toBeInTheDocument();
    const more = screen.getByRole("link", { name: "+2 aneksy" });
    expect(more).toHaveAttribute(
      "href",
      "/contracts/b2b-generator?tab=annexes&q=1538%2F2026",
    );
  });

  it("bez wglądu w stawki etykieta nie niesie kwoty; bez aneksu nie ma etykiety", () => {
    const { container, rerender } = render(
      <RegisterAnnexLabel
        row={{
          contract_number: "1538/2026",
          latest_annex: {
            document_id: 9,
            document_type: "annex_rate_change",
            state: "waiting",
            effective_date: null,
          },
          annex_count: 1,
          annex_rates: null,
        }}
      />,
    );
    expect(screen.getByText("Aneks: stawka · czeka na podpis")).toBeInTheDocument();
    expect(screen.queryByText(/\+\d/)).not.toBeInTheDocument();
    rerender(
      <RegisterAnnexLabel
        row={{ contract_number: "1/2026", latest_annex: null, annex_count: 0 }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("data startu: przed podpisem obie daty, po podpisie stara przekreślona", () => {
    const { rerender } = render(
      <RegisterStartDate
        row={{
          start_date: "2026-11-16",
          start_date_before: "2026-11-02",
          start_date_annex_state: "waiting",
        }}
      />,
    );
    expect(screen.getByText("02.11.2026")).not.toHaveClass("line-through");
    expect(screen.getByText("→ 16.11.2026")).toBeInTheDocument();
    expect(screen.getByText("po podpisie aneksu")).toBeInTheDocument();

    rerender(
      <RegisterStartDate
        row={{
          start_date: "2026-11-16",
          start_date_before: "2026-11-02",
          start_date_annex_state: "in_force",
        }}
      />,
    );
    expect(screen.getByText("02.11.2026")).toHaveClass("line-through");
    expect(screen.queryByText("po podpisie aneksu")).not.toBeInTheDocument();

    rerender(<RegisterStartDate row={{ start_date: "2026-08-25" }} />);
    expect(screen.getByText("25.08.2026")).toBeInTheDocument();
  });
});
