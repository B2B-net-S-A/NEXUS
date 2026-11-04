"use client";

/**
 * Harness wizualny generatora dokumentów pochodnych (zakładki „Dokumenty”
 * i „Generator aneksów” Generatora Umów B2B): lista w czterech stanach,
 * rejestr aneksów we wszystkich stanach wiersza, wybór osoby przy nowym
 * aneksie, kreator porozumienia o rozwiązaniu umowy bez i ze zwolnieniem
 * z zakazu konkurencji, wybór rodzaju dokumentu i okno „Oznacz jako
 * podpisany” (skutki, blokada, skan podpisanego aneksu).
 *
 * ZERO zapytań: cache react-query jest zasiany tymi samymi funkcjami kluczy
 * co komponenty (`b2bDocumentsKeys`), z `updatedAt` w przyszłości — zapytania
 * ze `staleTime: 0` (prefill, skutki) nie odświeżają się same. Na wypadek
 * klucza, którego nie przewidziano, interceptor żądań odrzuca wszystko.
 */

import { useEffect, useMemo, useState } from "react";
import {
  QueryClient,
  QueryClientProvider,
  type InfiniteData,
} from "@tanstack/react-query";

import { ContractAmendmentsTab } from "@/components/ContractAmendmentsTab";
import { ToastProvider } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  AnnexRegister,
  AnnexRegisterTable,
} from "@/components/v2/b2b-generator/documents/AnnexRegister";
import {
  AnnexSubjectPicker,
  EMPTY_ANNEX_CHOICE,
  type AnnexSubjectChoice,
} from "@/components/v2/b2b-generator/documents/AnnexSubjectPicker";
import {
  ConfirmSignedDialog,
  EffectsView,
} from "@/components/v2/b2b-generator/documents/DocumentDialogs";
import {
  DocumentsListView,
  DocumentsTabContent,
  type WizardState,
} from "@/components/v2/b2b-generator/documents/DocumentsTab";
import { DocumentWizard } from "@/components/v2/b2b-generator/documents/DocumentWizard";
import { BUSINESS_DATA_ANNEX_QUEUE_KEY } from "@/components/v2/b2b-generator/documents/BusinessDataAnnexQueue";
import { api, type B2BGeneratedContractRow } from "@/lib/api";
import {
  b2bDocumentsKeys,
  type DocumentEffects,
  type DocumentFieldDef,
  type DocumentItem,
  type DocumentPrefill,
  type DocumentSubject,
  type DocumentTypeDef,
  type DocumentTypesResponse,
} from "@/lib/api/b2bDocuments";
import { ANNEX_FAMILIES, NON_ANNEX_FAMILIES } from "@/lib/b2b-documents";
import { useAuthStore } from "@/store/auth";

// ── Dane fikcyjne ───────────────────────────────────────────────────────────

function field(
  key: string,
  label: string,
  extra: Partial<DocumentFieldDef> = {},
): DocumentFieldDef {
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
    lookup: null,
    lookup_fills: [],
    ...extra,
  };
}

const DOCUMENT_DATE = field("document_date", "Data dokumentu", {
  kind: "date",
  required: true,
  help: "Data w nagłówku dokumentu. Domyślnie dziś.",
});
const PARTNER: DocumentFieldDef[] = [
  field("gender", "Płeć Partnera", { kind: "gender", required: true, group: "partner" }),
  field("partner_name", "Imię i nazwisko", { required: true, group: "partner" }),
  field("partner_instrumental", "Imię i nazwisko — narzędnik", {
    help: "„z Panem/Panią …”",
    group: "partner",
  }),
  field("partner_legal_name", "Nazwa firmy", { group: "partner" }),
  field("partner_business_address", "Adres siedziby firmy", { group: "partner" }),
  field("partner_nip", "NIP", { group: "partner" }),
  field("partner_regon", "REGON", { group: "partner" }),
];

// Generator aneksów — lustro `registry.ANNEX_GENERATOR_TYPES` (skrót).
const JDG: [string, string] = ["partner_variant", "sole_trader"];
const COMPANY: [string, string] = ["partner_variant", "company"];
const ANNEX_BASE: DocumentFieldDef[] = [
  field("contract_number", "Numer umowy", { required: true, group: "base" }),
  field("contract_signing_date", "Data zawarcia umowy", {
    kind: "date",
    required: true,
    group: "base",
  }),
  field("document_date", "Data sporządzenia aneksu", {
    kind: "date",
    required: true,
    help: "Data w nagłówku aneksu. Domyślnie dziś.",
  }),
  field("effective_date", "Data wejścia zmian w życie", { kind: "date", required: true }),
];
const REGISTRY_FILLS: [string, string][] = [
  ["name", "partner_legal_name"],
  ["address", "partner_business_address"],
  ["regon", "partner_regon"],
];
const ANNEX_PARTNER: DocumentFieldDef[] = [
  field("partner_variant", "Wariant Partnera", {
    kind: "select",
    required: true,
    group: "partner",
    options: [
      ["sole_trader", "JDG"],
      ["company", "spółka"],
    ],
  }),
  field("gender", "Płeć", {
    kind: "gender",
    required: true,
    group: "partner",
    help: "Przy spółce — płeć osoby reprezentującej spółkę.",
  }),
  field("partner_name", "Imię i nazwisko Partnera", { required: true, group: "partner" }),
  field("partner_instrumental", "Imię i nazwisko — narzędnik", {
    group: "partner",
    show_if: JDG,
  }),
  field("partner_legal_name", "Nazwa firmy (spółki)", { required: true, group: "partner" }),
  field("partner_nip", "NIP", {
    required: true,
    group: "partner",
    lookup: "registry",
    lookup_fills: REGISTRY_FILLS,
    show_if: JDG,
  }),
  field("partner_nip", "NIP", {
    required: true,
    group: "partner",
    lookup: "registry",
    lookup_fills: [...REGISTRY_FILLS, ["krs", "partner_krs"]],
    show_if: COMPANY,
  }),
  field("partner_business_address", "Adres (z CEIDG / siedziby spółki)", {
    required: true,
    group: "partner",
  }),
  field("partner_regon", "REGON", { required: true, group: "partner" }),
  field("partner_seat_locative", "Siedziba — „z siedzibą …”", {
    required: true,
    group: "partner",
    show_if: COMPANY,
  }),
  field("partner_krs", "KRS", { required: true, group: "partner", show_if: COMPANY }),
];
const PARAGRAPH: DocumentFieldDef[] = [
  field("paragraph", "Zmieniany paragraf (§)", { required: true, group: "change" }),
  field("paragraph_section", "Ustęp", { required: true, group: "change" }),
];
function annex(
  key: string,
  label: string,
  description: string,
  fields: DocumentFieldDef[],
): DocumentTypeDef {
  return {
    key,
    label,
    family: "annex",
    languages: ["pl"],
    parent: "b2b",
    description,
    effect_label: "Rejestr zmienia się przy wygenerowaniu, kontrakt po podpisie.",
    signatories: "both",
    uses_refs: false,
    allows_external: true,
    legacy_languages: [],
    fields,
  };
}
const ANNEX_TYPES: DocumentTypeDef[] = [
  annex(
    "annex_party_data",
    "Aneks — uzupełnienie danych firmy",
    "Umowa zawarta z osobą fizyczną przed założeniem działalności: od aneksu Partnerem jest jej JDG.",
    [
      ...ANNEX_BASE,
      field("gender", "Płeć Partnera", { kind: "gender", required: true, group: "partner" }),
      field("partner_name", "Imię i nazwisko", { required: true, group: "partner" }),
      field("partner_home_address", "Adres zamieszkania", {
        required: true,
        sensitive: true,
        group: "partner",
      }),
      field("id_document", "Numer dowodu osobistego", {
        required: true,
        sensitive: true,
        group: "partner",
      }),
      field("new_nip", "NIP działalności", {
        required: true,
        group: "change",
        lookup: "registry",
        lookup_fills: [
          ["name", "new_legal_name"],
          ["address", "new_business_address"],
          ["regon", "new_regon"],
        ],
      }),
      field("new_legal_name", "Nazwa firmy", { required: true, group: "change" }),
      field("new_business_address", "Adres działalności (CEIDG)", {
        required: true,
        group: "change",
      }),
      field("new_regon", "REGON", { required: true, group: "change" }),
    ],
  ),
  annex(
    "annex_start_date",
    "Aneks — zmiana daty startu",
    "Przesunięcie daty rozpoczęcia świadczenia usług.",
    [
      ...ANNEX_BASE,
      ...ANNEX_PARTNER,
      ...PARAGRAPH,
      field("current_start_date", "Obecna data rozpoczęcia usług", {
        kind: "date",
        required: true,
        group: "change",
      }),
      field("new_start_date", "Nowa data rozpoczęcia usług", {
        kind: "date",
        required: true,
        group: "change",
      }),
    ],
  ),
  annex(
    "annex_rate_change",
    "Aneks — zmiana stawki",
    "Nowe wynagrodzenie godzinowe: jedna stawka, stawka progresywna albo różne stawki dla różnych klientów.",
    [
      ...ANNEX_BASE,
      ...ANNEX_PARTNER,
      ...PARAGRAPH,
      field("rate_items", "Stawki", {
        kind: "rate_items",
        required: true,
        group: "change",
        help: "Jedna pozycja = jedna stawka. Kilka pozycji: stawka progresywna (daty „od”) albo różne stawki dla klientów.",
      }),
    ],
  ),
];

const TYPES: DocumentTypeDef[] = [
  ...ANNEX_TYPES,
  {
    key: "termination_agreement",
    label: "Porozumienie o rozwiązaniu umowy",
    family: "termination",
    languages: ["pl", "en"],
    parent: "b2b",
    description: "Rozwiązanie umowy B2B za porozumieniem stron.",
    effect_label:
      "Kontrakt dostanie datę zakończenia (powód: porozumienie stron), zamówienia zostaną domknięte, umowa w rejestrze — „Zakończona”.",
    signatories: "both",
    uses_refs: true,
    allows_external: false,
    legacy_languages: [],
    fields: [
      DOCUMENT_DATE,
      ...PARTNER,
      field("termination_date", "Umowa ulega rozwiązaniu z dniem", {
        kind: "date",
        required: true,
      }),
      field("last_service_date", "Ostatni dzień świadczenia usług", {
        kind: "date",
        required: true,
        help: "Zwykle ta sama data co rozwiązanie umowy.",
      }),
      field("release_non_compete", "Zwolnienie z zakazu konkurencji", {
        kind: "bool",
        help: "Partner może świadczyć usługi na rzecz Klienta bez B2B.net.",
      }),
      field("non_compete_client_name", "Klient, którego dotyczy zwolnienie", {
        required: true,
        help: "Pełna nazwa (z formą prawną). Obejmuje też spółki powiązane.",
        show_if: ["release_non_compete", true],
      }),
    ],
  },
  {
    key: "termination_notice",
    label: "Wypowiedzenie umowy (przez B2B.net)",
    family: "termination",
    languages: ["pl"],
    parent: "b2b",
    description:
      "Jednostronne wypowiedzenie umowy B2B przez B2B.net z zachowaniem okresu wypowiedzenia.",
    effect_label: "Kontrakt dostanie datę zakończenia po okresie wypowiedzenia.",
    signatories: "company",
    uses_refs: true,
    allows_external: false,
    legacy_languages: [],
    fields: [DOCUMENT_DATE],
  },
  {
    key: "preliminary_cez",
    label: "Umowa przedwstępna — Instytut Przykładowy",
    family: "preliminary",
    languages: ["pl"],
    parent: "none",
    description:
      "Umowa przedwstępna z kandydatem przed rozstrzygnięciem rekrutacji w Instytut Przykładowy.",
    effect_label: "Brak zmian w kontraktach.",
    signatories: "partner_and_company",
    uses_refs: false,
    allows_external: false,
    legacy_languages: [],
    fields: [
      DOCUMENT_DATE,
      field("pesel", "PESEL", { required: true, sensitive: true, group: "partner" }),
    ],
  },
];

const TYPES_RESPONSE: DocumentTypesResponse = {
  types: TYPES,
  ref_labels: {
    rate_paragraph: "Paragraf wynagrodzenia",
    non_compete_paragraph: "Paragraf zakazu konkurencji",
    notice_paragraph: "Paragraf wypowiedzenia",
  },
  ref_defaults: {
    rate_paragraph: "§ 5",
    non_compete_paragraph: "§ 9",
    notice_paragraph: "§ 12",
  },
  mandate_forms: [
    {
      key: "contractor_statement_pl",
      label: "Oświadczenie zleceniobiorcy",
      description:
        "Dane do kadr, PIT i ZUS: adresy, urząd skarbowy, NFZ, konto, status (student, inne zatrudnienie, emerytura). Wzór na 2026.",
      download_name: "Oświadczenie zleceniobiorcy 2026.docx",
      format: "DOCX",
    },
    {
      key: "contractor_statement_pl_en",
      label: "Oświadczenie zleceniobiorcy (PL/EN)",
      description: "To samo oświadczenie z tłumaczeniem na angielski.",
      download_name: "Oświadczenie zleceniobiorcy 2026 PL-EN.docx",
      format: "DOCX",
    },
    {
      key: "pit_2",
      label: "PIT-2",
      description:
        "Oświadczenia i wnioski do zaliczek na podatek, m.in. kwota zmniejszająca podatek (dla osób powyżej 26 lat).",
      download_name: "PIT-2.pdf",
      format: "PDF",
    },
    {
      key: "ppk_resignation",
      label: "Deklaracja rezygnacji z wpłat do PPK",
      description: "Dla zleceniobiorcy, który nie chce oszczędzać w PPK.",
      download_name: "Deklaracja rezygnacji z PPK.pdf",
      format: "PDF",
    },
    {
      key: "foreigner_tax_statement",
      label: "Oświadczenie do celów podatkowych — cudzoziemcy",
      description: "Rezydencja podatkowa cudzoziemca; z kopią paszportu.",
      download_name: "Oświadczenie do celów podatkowych - cudzoziemcy.pdf",
      format: "PDF",
    },
  ],
};

const PARENT_ID = 101;

const PREFILL: DocumentPrefill = {
  values: {
    document_date: "2026-09-23",
    gender: "f",
    partner_name: "Anna Przykładowa",
    partner_legal_name: "Anna Przykładowa Consulting",
    partner_business_address: "ul. Przykładowa 1, 00-001 Warszawa",
    partner_nip: "0000000000",
    termination_date: "2026-10-31",
    last_service_date: "2026-10-31",
    non_compete_client_name: "Bank Przykładowy S.A.",
  },
  base: {
    contract_number: "1234/2026",
    signing_date: "2026-03-01",
    start_date: "2026-03-15",
    start_date_mode: "exact",
    client_name: "Bank Przykładowy",
    client_legal_name: "Bank Przykładowy S.A.",
    currency: "PLN",
    template_version: null,
  },
  // Umowa z importu (nieznana wersja wzoru) — pokazuje sekcję paragrafów.
  needs_refs: true,
  ref_defaults: TYPES_RESPONSE.ref_defaults,
  languages: ["pl", "en"],
  default_language: "pl",
};

const ANNEX_PREFILL: DocumentPrefill = {
  ...PREFILL,
  values: {
    document_date: "2026-09-29",
    effective_date: "2026-10-01",
    contract_number: "1234/2026",
    contract_signing_date: "2026-03-01",
    gender: "f",
    partner_variant: "sole_trader",
    partner_name: "Anna Przykładowa",
    partner_instrumental: "Anną Przykładową",
    partner_legal_name: "Anna Przykładowa Consulting",
    partner_business_address: "ul. Przykładowa 1, 00-001 Warszawa",
    partner_nip: "0000000000",
    partner_regon: "000000000",
    paragraph: "6",
    paragraph_section: "1",
    rate_items: [
      { rate: 150, client_id: 1, client_name: "Bank Przykładowy S.A.", from: null, to: "2026-12-31" },
      { rate: "160,50", client_id: null, client_name: null, from: "2027-01-01", to: null },
    ],
  },
  needs_refs: false,
  paragraph_defaults: { sole_trader: ["6", "1"], company: ["6", "1"] },
  languages: ["pl"],
};

const ANNEX_EXTERNAL_PREFILL: DocumentPrefill = {
  ...ANNEX_PREFILL,
  values: {
    document_date: "2026-09-29",
    effective_date: "2026-09-29",
    gender: "m",
    partner_variant: "sole_trader",
    paragraph: "12",
    paragraph_section: "2",
  },
  paragraph_defaults: { sole_trader: ["12", "2"], company: ["13", "2"] },
};

function doc(overrides: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id: 1,
    document_type: "termination_agreement",
    type_label: "Porozumienie o rozwiązaniu umowy",
    family: "termination",
    language: "pl",
    label: "Porozumienie o rozwiązaniu umowy z dnia 23.09.2026 do umowy 1234/2026",
    document_date: "2026-09-23",
    parent_generated_contract_id: PARENT_ID,
    parent_contract_number: "1234/2026",
    contract_id: 55,
    candidate_id: 7,
    partner_name: "Anna Przykładowa",
    client_name: "Bank Przykładowy",
    status: "issued",
    signature_status: "unsigned",
    signed_at: null,
    effect_applied_at: null,
    effect_summary: null,
    created_by_name: "Jan Delivery",
    created_at: "2026-09-23T09:15:00Z",
    requires_sensitive_input: false,
    sensitive_fields: [],
    can_edit: true,
    can_delete: true,
    can_confirm_signed: true,
    cancelled_reason: null,
    ...overrides,
  };
}

// Zakładka „Dokumenty” nie pokazuje aneksów — mają własny rejestr.
const ROWS: DocumentItem[] = [
  doc(),
  doc({
    id: 3,
    document_type: "preliminary_cez",
    type_label: "Umowa przedwstępna — Instytut Przykładowy",
    family: "preliminary",
    label: "Umowa przedwstępna — Instytut Przykładowy z dnia 20.09.2026",
    document_date: "2026-09-20",
    parent_generated_contract_id: null,
    parent_contract_number: null,
    partner_name: "Maria Fikcyjna",
    client_name: "Instytut Przykładowy",
    requires_sensitive_input: true,
    sensitive_fields: ["pesel"],
  }),
  doc({
    id: 4,
    label: "Porozumienie o rozwiązaniu umowy z dnia 10.09.2026 do umowy 0555/2026",
    document_date: "2026-09-10",
    partner_name: "Tomasz Wzorcowy",
    status: "cancelled",
    cancelled_reason: "Partner zmienił zdanie — zostaje w projekcie.",
    can_edit: false,
    can_delete: false,
    can_confirm_signed: false,
  }),
];

// ── Rejestr aneksów ─────────────────────────────────────────────────────────

function annexRow(overrides: Partial<DocumentItem> = {}): DocumentItem {
  return doc({
    document_type: "annex_rate_change",
    type_label: "Aneks — zmiana stawki",
    family: "annex",
    label: "Aneks — zmiana stawki z dnia 10.10.2026",
    document_date: "2026-10-10",
    created_at: "2026-10-10T09:40:00Z",
    client_id: 2,
    client_name: "Ubezpieczenia Przykład S.A.",
    external: false,
    state: "waiting",
    effective_date: "2026-11-01",
    can_restore: false,
    can_link_contract: false,
    signed_scan_document_id: null,
    ...overrides,
  });
}

const ANNEX_ROWS: DocumentItem[] = [
  annexRow({
    id: 21,
    parent_generated_contract_id: null,
    parent_contract_number: null,
    contract_id: 651,
    external: true,
    partner_name: "Piotr Testowy",
    person_name: "Piotr Testowy",
    partner_legal_name: "TESTOWY IT Piotr Testowy",
    partner_nip: "0000000011",
    change: {
      kind: "rate",
      hidden: false,
      currency: "PLN",
      items: [{ rate: 150, from: null, to: null }],
      before: [],
    },
  }),
  annexRow({
    id: 22,
    parent_generated_contract_id: null,
    parent_contract_number: null,
    contract_id: null,
    external: true,
    partner_name: "Michał Wzorcowy",
    person_name: "Michał Wzorcowy",
    partner_legal_name: "WZORCOWY Consulting",
    partner_nip: "0000000044",
    client_name: "Telekom Przykładowy Sp. z o.o.",
    created_by_name: "Joanna Delivery",
    can_confirm_signed: false,
    can_link_contract: true,
    change: { kind: "rate", hidden: true },
  }),
  annexRow({
    id: 23,
    document_type: "annex_start_date",
    type_label: "Aneks — zmiana daty startu",
    label: "Aneks — zmiana daty startu z dnia 08.10.2026 do umowy 1541/2026",
    parent_contract_number: "1541/2026",
    contract_id: 712,
    partner_name: "Ewa Przykładowa",
    person_name: "Ewa Przykładowa",
    partner_nip: "0000000066",
    client_name: "Bank Przykładowy S.A.",
    status: "signed",
    signature_status: "signed_both",
    signed_at: "2026-10-09T08:00:00Z",
    state: "signed_pending",
    effective_date: "2026-11-16",
    can_edit: false,
    can_delete: false,
    can_confirm_signed: false,
    change: { kind: "start_date", before: "2026-11-02", after: "2026-11-16" },
  }),
  annexRow({
    id: 24,
    document_type: "annex_party_data",
    type_label: "Aneks — uzupełnienie danych firmy",
    label: "Aneks — uzupełnienie danych firmy z dnia 25.09.2026 do umowy 1538/2026",
    parent_contract_number: "1538/2026",
    contract_id: 706,
    partner_name: "Adam Fikcyjny",
    person_name: "Adam Fikcyjny",
    partner_legal_name: "FIKCYJNY DEV Adam Fikcyjny",
    partner_nip: "0000000088",
    client_name: "Bank Przykładowy S.A.",
    status: "signed",
    signature_status: "signed_both",
    signed_at: "2026-09-28T10:00:00Z",
    state: "in_force",
    effective_date: "2026-10-01",
    can_edit: false,
    can_delete: false,
    can_confirm_signed: false,
    signed_scan_document_id: 900,
    change: {
      kind: "party",
      legal_name: "FIKCYJNY DEV Adam Fikcyjny",
      nip: "0000000088",
    },
  }),
  annexRow({
    id: 25,
    document_type: "annex_subcontractor",
    type_label: "Aneks — osoba skierowana (oddelegowanie)",
    label: "Aneks — osoba skierowana z dnia 24.09.2026 do umowy 1502/2026",
    parent_contract_number: "1502/2026",
    contract_id: 688,
    partner_name: "Karolina Wzorcowa",
    person_name: "Karolina Wzorcowa",
    partner_legal_name: "WZORCOWA Software Sp. z o.o.",
    partner_nip: "0000000022",
    status: "signed",
    signature_status: "signed_both",
    signed_at: "2026-09-26T10:00:00Z",
    state: "in_force",
    effective_date: "2026-10-01",
    can_edit: false,
    can_delete: false,
    can_confirm_signed: false,
    change: { kind: "delegate", name: "Paweł Przykładowy" },
  }),
  annexRow({
    id: 26,
    label: "Aneks — zmiana stawki z dnia 22.09.2026 do umowy 1519/2026",
    parent_contract_number: "1519/2026",
    contract_id: 690,
    partner_name: "Tomasz Wzorcowy",
    person_name: "Tomasz Wzorcowy",
    partner_nip: "0000000077",
    client_name: "Telekom Przykładowy Sp. z o.o.",
    status: "cancelled",
    state: "cancelled",
    effective_date: "2026-10-01",
    cancelled_reason: "Partner nie podpisał",
    can_edit: false,
    can_delete: false,
    can_confirm_signed: false,
    can_restore: true,
    change: {
      kind: "rate",
      hidden: false,
      currency: "PLN",
      items: [{ rate: 130, from: null, to: null }],
      before: [{ rate: 120, from: null, to: null }],
    },
  }),
];

// Zakładka „Aneksy” kontraktu: aneks czekający na podpis, zmiany zapisane
// (z generatora i ręczna) oraz aneks anulowany. Bez aneksu stawki — harness
// nie ma zalogowanej osoby, więc wierszy z kwotami zakładka by nie pokazała.
const CONTRACT_ID = 651;

const CONTRACT_ANNEX_DOCUMENTS = [
  {
    document_id: 31,
    document_type: "annex_start_date",
    type_label: "Aneks — zmiana daty startu",
    state: "waiting",
    effective_date: "2026-11-16",
    change: { kind: "start_date", before: "2026-11-02", after: "2026-11-16" },
    cancelled_reason: null,
    created_at: "2026-10-10T09:40:00Z",
    created_by_name: "Jan Delivery",
  },
  {
    document_id: 32,
    document_type: "annex_subcontractor",
    type_label: "Aneks — osoba skierowana (oddelegowanie)",
    state: "cancelled",
    effective_date: "2026-06-15",
    change: { kind: "delegate", name: "Paweł Przykładowy" },
    cancelled_reason: "Partner nie podpisał",
    created_at: "2026-06-02T08:00:00Z",
    created_by_name: "Jan Delivery",
  },
];

const CONTRACT_AMENDMENTS = [
  {
    id: 41,
    contract_id: CONTRACT_ID,
    amendment_type: "party_data_change",
    old_values: {},
    new_values: { legal_name: "TESTOWY IT Piotr Testowy", nip: "0000000011" },
    effective_date: "2026-09-01",
    reason: null,
    document_id: 900,
    created_by: 1,
    created_by_email: null,
    created_by_name: "Joanna Delivery",
    created_at: "2026-08-20T10:00:00Z",
    source: "generator",
    b2b_document_id: 24,
    state: "in_force",
    document: { id: 900, filename: "Aneks dane firmy.pdf", is_signed_scan: true },
  },
  {
    id: 42,
    contract_id: CONTRACT_ID,
    amendment_type: "scope_change",
    old_values: { project_name: "Migracja" },
    new_values: { project_name: "Hurtownia danych" },
    effective_date: "2026-08-01",
    reason: "Zmiana projektu u klienta",
    document_id: null,
    created_by: 1,
    created_by_email: null,
    created_by_name: "Jan Delivery",
    created_at: "2026-07-28T10:00:00Z",
    source: "manual",
    b2b_document_id: null,
    state: "in_force",
    document: null,
  },
  {
    id: 43,
    contract_id: CONTRACT_ID,
    amendment_type: "start_date_change",
    old_values: { start_date: "2026-07-01" },
    new_values: { start_date: "2026-07-06" },
    effective_date: "2026-07-06",
    reason: null,
    document_id: 901,
    created_by: 1,
    created_by_email: null,
    created_by_name: "Joanna Delivery",
    created_at: "2026-06-28T10:00:00Z",
    source: "generator",
    b2b_document_id: 12,
    state: "in_force",
    document: { id: 901, filename: "Aneks start.docx", is_signed_scan: false },
  },
];

const SUBJECT_QUERY = "Testowy";

const SUBJECTS: DocumentSubject[] = [
  {
    kind: "agreement",
    parent_generated_contract_id: PARENT_ID,
    contract_number: "1234/2026",
    source: "generator",
    agreement_status: "active",
    contract_id: 706,
    contract_status: "active",
    contract_start_date: "2026-10-19",
    contract_options: [],
    candidate_id: 7,
    person_name: "Piotr Testowy",
    partner_name: "TESTOWY IT Piotr Testowy",
    partner_nip: "0000000011",
    client_id: 1,
    client_name: "Bank Przykładowy S.A.",
  },
  {
    kind: "agreement",
    parent_generated_contract_id: 102,
    contract_number: "264A",
    source: "excel",
    agreement_status: "active",
    contract_id: null,
    contract_status: null,
    contract_start_date: null,
    contract_options: [
      { contract_id: 512, status: "active", start_date: "2025-03-01" },
      { contract_id: 540, status: "ending", start_date: "2025-09-01" },
    ],
    candidate_id: 7,
    person_name: "Piotr Testowy",
    partner_name: "TESTOWY IT Piotr Testowy",
    partner_nip: "0000000011",
    client_id: 3,
    client_name: "Telekom Przykładowy Sp. z o.o.",
  },
  {
    kind: "contract",
    parent_generated_contract_id: null,
    contract_number: null,
    source: null,
    agreement_status: null,
    contract_id: 651,
    contract_status: "active",
    contract_start_date: "2026-07-06",
    contract_options: [],
    candidate_id: 7,
    person_name: "Piotr Testowy",
    partner_name: "TESTOWY IT Piotr Testowy",
    partner_nip: "0000000011",
    client_id: 2,
    client_name: "Ubezpieczenia Przykład S.A.",
  },
];

const EFFECTS_ANNEX: DocumentEffects = {
  effect_label: "Stawki wejdą do harmonogramu stawek kontraktu.",
  changes: [
    "Stawka Partnera 150 PLN/h od 01.11.2026 — nowy krok w harmonogramie stawek kontraktu.",
  ],
  warnings: [],
  blockers: [],
};

const EFFECTS_OK: DocumentEffects = {
  effect_label: TYPES[2].effect_label,
  changes: [
    "Kontrakt #55: data zakończenia 31.10.2026 (powód: porozumienie stron).",
    "Zamówienia tej osoby zostaną domknięte z datą 31.10.2026.",
    "Umowa 1234/2026 w rejestrze: „Zakończona”.",
  ],
  warnings: ["Zamówienie 445/2026 kończy się później — zostanie skrócone."],
  blockers: [],
};

const EFFECTS_BLOCKED: DocumentEffects = {
  effect_label: TYPES[2].effect_label,
  changes: ["Umowa 1234/2026 w rejestrze: „Zakończona”."],
  warnings: [],
  blockers: [
    "Kontrakt ma otwartą sprawę offboardingu MD — rozstrzygnij ją przed podpisem.",
  ],
};

const ANNEX_QUEUE = [
  {
    id: 91,
    contract_number: "1402/2026",
    partner_name: "Ewa Przykładowa",
    client_name: "Bank Przykładowy",
  },
] as unknown as B2BGeneratedContractRow[];

// ── Zasiew ──────────────────────────────────────────────────────────────────

const CLIENTS = [
  { id: 1, name: "Bank Przykładowy S.A." },
  { id: 2, name: "Ubezpieczenia Przykład S.A." },
];

const FUTURE = Date.now() + 365 * 24 * 3600 * 1000;

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  const opts = { updatedAt: FUTURE };
  qc.setQueryData(b2bDocumentsKeys.types(), TYPES_RESPONSE, opts);
  qc.setQueryData<InfiniteData<DocumentItem[], number>>(
    b2bDocumentsKeys.list({
      documentType: "",
      status: "",
      q: "",
      family: NON_ANNEX_FAMILIES,
    }),
    { pages: [ROWS], pageParams: [0] },
    opts,
  );
  qc.setQueryData<InfiniteData<DocumentItem[], number>>(
    b2bDocumentsKeys.list({
      documentType: "",
      status: "",
      q: "",
      family: ANNEX_FAMILIES,
    }),
    { pages: [ANNEX_ROWS], pageParams: [0] },
    opts,
  );
  qc.setQueryData(
    b2bDocumentsKeys.subjects("annex_rate_change", SUBJECT_QUERY),
    SUBJECTS,
    opts,
  );
  qc.setQueryData(["b2b-annex-subject-clients"], CLIENTS, opts);
  qc.setQueryData(["contract-amendments", CONTRACT_ID], CONTRACT_AMENDMENTS, opts);
  qc.setQueryData(
    ["contract-annex-documents", CONTRACT_ID],
    CONTRACT_ANNEX_DOCUMENTS,
    opts,
  );
  qc.setQueryData(b2bDocumentsKeys.effects(21), EFFECTS_ANNEX, opts);
  qc.setQueryData(
    b2bDocumentsKeys.prefill("termination_agreement", PARENT_ID, null),
    PREFILL,
    opts,
  );
  qc.setQueryData(
    b2bDocumentsKeys.prefill("annex_rate_change", PARENT_ID, null),
    ANNEX_PREFILL,
    opts,
  );
  qc.setQueryData(
    b2bDocumentsKeys.prefill("annex_start_date", null, null),
    ANNEX_EXTERNAL_PREFILL,
    opts,
  );
  qc.setQueryData(["b2b-annex-rate-clients"], CLIENTS, opts);
  qc.setQueryData(["b2b-generated", "documents-picker", ""], [], opts);
  qc.setQueryData(b2bDocumentsKeys.effects(1), EFFECTS_OK, opts);
  qc.setQueryData(b2bDocumentsKeys.effects(3), EFFECTS_BLOCKED, opts);
  qc.setQueryData(BUSINESS_DATA_ANNEX_QUEUE_KEY, ANNEX_QUEUE, opts);
  return qc;
}

function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      Promise.reject(
        Object.assign(new Error("Harness /preview/b2b-documents nie wysyła zapytań."), {
          isAxiosError: true,
          code: "ERR_PREVIEW_OFFLINE",
        }),
      ),
    ),
  );
  useEffect(
    () => () => {
      api.interceptors.request.eject(interceptorId);
    },
    [interceptorId],
  );
}

/** Fikcyjny administrator: wybór osoby pokazuje kontrakty tylko komuś, kto
 *  je prowadzi, a zakładka kontraktu — kwoty tylko z wglądem w stawki. */
function usePreviewAdmin() {
  useEffect(() => {
    const previous = useAuthStore.getState();
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Administrator Przykładowy",
        role: "admin",
        roles: ["admin"],
        capabilities: ["view_finance", "manage_finance"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
      } as never,
      token: "preview",
    } as never);
    return () => {
      useAuthStore.setState({ user: previous.user, token: previous.token } as never);
    };
  }, []);
}

// ── Strona ──────────────────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Harness() {
  useNetworkBlocked();
  usePreviewAdmin();
  const [wizard, setWizard] = useState<WizardState | null>(null);
  const [signOpen, setSignOpen] = useState<DocumentItem | null>(null);
  const [annexSearch, setAnnexSearch] = useState("");
  const [annexChoice, setAnnexChoice] = useState<AnnexSubjectChoice>({
    ...EMPTY_ANNEX_CHOICE,
    parentId: 102,
    parentLabel: "264A — Piotr Testowy",
    needsContractPick: true,
  });
  const typesByKey = useMemo(() => new Map(TYPES.map((t) => [t.key, t])), []);
  const noop = () => undefined;
  const stateProps = {
    typesByKey,
    onRetry: noop,
    onMore: noop,
    onEdit: noop,
    hasMore: false,
    loadingMore: false,
    moreFailed: false,
  };
  const annexStateProps = {
    onRetry: noop,
    onMore: noop,
    onEdit: noop,
    hasMore: false,
    loadingMore: false,
    moreFailed: false,
  };
  return (
    <div className="mx-auto max-w-6xl space-y-10 bg-background p-6">
      <header>
        <h1 className="text-2xl font-semibold">Dokumenty do umów — harness</h1>
        <p className="text-sm text-muted-foreground">
          Dane fikcyjne, bez zapytań do API.
        </p>
      </header>

      <Section title="Lista dokumentów">
        <DocumentsTabContent
          wizard={wizard}
          onOpenWizard={(next) => setWizard({ key: Date.now(), ...next })}
          onCloseWizard={() => setWizard(null)}
        />
      </Section>

      <Section title="Lista — wczytywanie, błąd, 403, pustka">
        <DocumentsListView {...stateProps} rows={[]} state="loading" filtered={false} />
        <DocumentsListView
          {...stateProps}
          rows={[]}
          state="error"
          filtered={false}
          error={{ response: { status: 500, data: { detail: "Błąd serwera." } } }}
        />
        <DocumentsListView
          {...stateProps}
          rows={[]}
          state="error"
          filtered={false}
          error={{ response: { status: 403, data: { detail: "Brak dostępu." } } }}
        />
        <DocumentsListView {...stateProps} rows={[]} state="empty" filtered={false} />
        <DocumentsListView {...stateProps} rows={[]} state="empty" filtered />
      </Section>

      <Section title="Rejestr aneksów">
        <AnnexRegister search={annexSearch} onSearch={setAnnexSearch} onEdit={noop} />
      </Section>

      <Section title="Rejestr aneksów — wczytywanie, błąd, 403, pustka">
        <AnnexRegisterTable {...annexStateProps} rows={[]} state="loading" filtered={false} />
        <AnnexRegisterTable
          {...annexStateProps}
          rows={[]}
          state="error"
          filtered={false}
          error={{ response: { status: 500, data: { detail: "Błąd serwera." } } }}
        />
        <AnnexRegisterTable
          {...annexStateProps}
          rows={[]}
          state="error"
          filtered={false}
          error={{ response: { status: 403, data: { detail: "Brak dostępu." } } }}
        />
        <AnnexRegisterTable {...annexStateProps} rows={[]} state="empty" filtered={false} />
        <AnnexRegisterTable {...annexStateProps} rows={[]} state="empty" filtered />
      </Section>

      <Section title="Nowy aneks — dla kogo (umowa z rejestru, umowa z Excela z dwoma kontraktami, kontrakt bez umowy)">
        <div className="rounded-lg border border-border bg-card p-4">
          <AnnexSubjectPicker
            type={typesByKey.get("annex_rate_change")!}
            choice={annexChoice}
            onChoice={setAnnexChoice}
            initialQuery={SUBJECT_QUERY}
          />
        </div>
      </Section>

      <Section title="Kontrakt → zakładka Aneksy (aneks czeka na podpis, zmiany zapisane, anulowany)">
        <ContractAmendmentsTab
          contractId={CONTRACT_ID}
          clientId={2}
          personName="Piotr Testowy"
        />
      </Section>

      <Section title="Generator aneksów — wybór typu aneksu">
        <DocumentWizard mode="annexes" typesData={TYPES_RESPONSE} onClose={noop} />
      </Section>

      <Section title="Generator aneksów — zmiana stawki (umowa z rejestru, dwie pozycje)">
        <DocumentWizard
          mode="annexes"
          typesData={TYPES_RESPONSE}
          initialType="annex_rate_change"
          initialParentId={PARENT_ID}
          onClose={noop}
        />
      </Section>

      <Section title="Kreator — wybór rodzaju dokumentu">
        <DocumentWizard typesData={TYPES_RESPONSE} onClose={noop} />
      </Section>

      <Section title="Kreator — porozumienie bez zwolnienia z zakazu konkurencji">
        <DocumentWizard
          typesData={TYPES_RESPONSE}
          initialType="termination_agreement"
          initialParentId={PARENT_ID}
          initialValues={{ release_non_compete: false }}
          onClose={noop}
        />
      </Section>

      <Section title="Kreator — porozumienie ze zwolnieniem z zakazu konkurencji">
        <DocumentWizard
          typesData={TYPES_RESPONSE}
          initialType="termination_agreement"
          initialParentId={PARENT_ID}
          initialValues={{ release_non_compete: true }}
          onClose={noop}
        />
      </Section>

      <Section title="Oznacz jako podpisany — skutki">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border border-border bg-card p-4">
            <EffectsView effects={EFFECTS_OK} />
          </div>
          <div className="rounded-lg border border-border bg-card p-4">
            <EffectsView effects={EFFECTS_BLOCKED} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setSignOpen(ROWS[0])}>
            Otwórz okno (bez blokad)
          </Button>
          <Button variant="outline" onClick={() => setSignOpen(ROWS[1])}>
            Otwórz okno (z blokadą)
          </Button>
          <Button variant="outline" onClick={() => setSignOpen(ANNEX_ROWS[0])}>
            Otwórz okno (aneks ze skanem)
          </Button>
        </div>
        {signOpen ? (
          <ConfirmSignedDialog item={signOpen} onClose={() => setSignOpen(null)} />
        ) : null}
      </Section>
    </div>
  );
}

export default function B2BDocumentsPreviewPage() {
  const [client] = useState(seededClient);
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <Harness />
      </ToastProvider>
    </QueryClientProvider>
  );
}
