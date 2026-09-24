"use client";

/**
 * Harness wizualny generatora dokumentów pochodnych (zakładka „Dokumenty”
 * Generatora Umów B2B): lista w czterech stanach, kreator porozumienia
 * o rozwiązaniu umowy bez i ze zwolnieniem z zakazu konkurencji, wybór
 * rodzaju dokumentu i okno „Oznacz jako podpisany” (skutki i blokada).
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

import { ToastProvider } from "@/components/Toast";
import { Button } from "@/components/ui/button";
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
  type DocumentTypeDef,
  type DocumentTypesResponse,
} from "@/lib/api/b2bDocuments";

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

const TYPES: DocumentTypeDef[] = [
  {
    key: "annex_rate_change",
    label: "Aneks — zmiana stawki",
    family: "annex",
    languages: ["pl", "en"],
    parent: "b2b",
    description: "Zmiana wynagrodzenia godzinowego Partnera.",
    effect_label: "Nowa stawka wejdzie do harmonogramu stawek kontraktu.",
    signatories: "both",
    uses_refs: true,
    fields: [
      DOCUMENT_DATE,
      ...PARTNER,
      field("effective_date", "Nowa stawka obowiązuje od", { kind: "date", required: true }),
      field("new_rate", "Nowa stawka godzinowa netto", { kind: "money", required: true }),
      field("currency", "Waluta", {
        kind: "select",
        required: true,
        options: [
          ["PLN", "PLN"],
          ["EUR", "EUR"],
        ],
      }),
    ],
  },
  {
    key: "annex_party_data",
    label: "Aneks — uzupełnienie danych firmy",
    family: "annex",
    languages: ["pl", "en"],
    parent: "b2b",
    description:
      "Umowa zawarta przed założeniem działalności: od dnia aneksu Partnerem jest firma.",
    effect_label: "Dane firmy trafią do profilu kandydata i do rejestru umów.",
    signatories: "both",
    uses_refs: true,
    fields: [DOCUMENT_DATE],
  },
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
    fields: [DOCUMENT_DATE],
  },
  {
    key: "preliminary_cez",
    label: "Umowa przedwstępna — Centrum e-Zdrowia",
    family: "preliminary",
    languages: ["pl"],
    parent: "none",
    description:
      "Umowa przedwstępna z kandydatem przed rozstrzygnięciem rekrutacji w Centrum e-Zdrowia.",
    effect_label: "Brak zmian w kontraktach.",
    signatories: "partner_and_company",
    uses_refs: false,
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

const ROWS: DocumentItem[] = [
  doc(),
  doc({
    id: 2,
    document_type: "annex_rate_change",
    type_label: "Aneks — zmiana stawki",
    family: "annex",
    label: "Aneks — zmiana stawki z dnia 01.09.2026 do umowy 0987/2026",
    document_date: "2026-09-01",
    parent_contract_number: "0987/2026",
    partner_name: "Piotr Testowy",
    client_name: "Ubezpieczenia Przykład",
    status: "signed",
    signature_status: "signed_both",
    signed_at: "2026-09-05T12:00:00Z",
    can_edit: false,
    can_delete: false,
    can_confirm_signed: false,
  }),
  doc({
    id: 3,
    document_type: "preliminary_cez",
    type_label: "Umowa przedwstępna — Centrum e-Zdrowia",
    family: "preliminary",
    label: "Umowa przedwstępna — Centrum e-Zdrowia z dnia 20.09.2026",
    document_date: "2026-09-20",
    parent_generated_contract_id: null,
    parent_contract_number: null,
    partner_name: "Maria Fikcyjna",
    client_name: "Centrum e-Zdrowia",
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

const FUTURE = Date.now() + 365 * 24 * 3600 * 1000;

function seededClient(): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  const opts = { updatedAt: FUTURE };
  qc.setQueryData(b2bDocumentsKeys.types(), TYPES_RESPONSE, opts);
  qc.setQueryData<InfiniteData<DocumentItem[], number>>(
    b2bDocumentsKeys.list({ documentType: "", status: "", q: "" }),
    { pages: [ROWS], pageParams: [0] },
    opts,
  );
  qc.setQueryData(
    b2bDocumentsKeys.prefill("termination_agreement", PARENT_ID, null),
    PREFILL,
    opts,
  );
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
  const [wizard, setWizard] = useState<WizardState | null>(null);
  const [signOpen, setSignOpen] = useState<DocumentItem | null>(null);
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
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setSignOpen(ROWS[0])}>
            Otwórz okno (bez blokad)
          </Button>
          <Button variant="outline" onClick={() => setSignOpen(ROWS[2])}>
            Otwórz okno (z blokadą)
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
