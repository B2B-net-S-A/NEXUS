"use client";

/**
 * Harness wizualny wzorów własnych Generatora Umów B2B (asystent prawny,
 * część B): „Nowy wzór z asystentem” w trzech krokach (opis, szkic i pola,
 * zapis i zatwierdzenie), lista wzorów, sekcja „Wzory własne” w „Nowy
 * dokument” i formularz dokumentu ze wzoru.
 *
 * Dane WYŁĄCZNIE fikcyjne. ZERO zapytań: cache react-query zasiany tymi samymi
 * kluczami co komponenty, interceptor odrzuca każde żądanie.
 */

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { DocumentWizard } from "@/components/v2/b2b-generator/documents/DocumentWizard";
import { CustomTemplatesPanelView } from "@/components/v2/b2b-generator/documents/custom-templates/CustomTemplatesPanel";
import { TemplateStudio } from "@/components/v2/b2b-generator/documents/custom-templates/TemplateStudio";
import { api } from "@/lib/api";
import { b2bDocumentsKeys, type DocumentTypesResponse } from "@/lib/api/b2bDocuments";
import {
  customTemplatesKeys,
  type CustomCheck,
  type CustomDocumentType,
  type CustomFieldDef,
  type CustomTemplateDetail,
  type CustomTemplatesList,
  type CustomVersion,
} from "@/lib/api/customTemplates";

// ── Dane fikcyjne ───────────────────────────────────────────────────────────

function f(
  key: string,
  label: string,
  extra: Partial<CustomFieldDef> = {},
): CustomFieldDef {
  return {
    key,
    label,
    kind: "text",
    group: "Dokument",
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

const FIELDS: CustomFieldDef[] = [
  f("agreement_date", "Data umowy", { kind: "date", required: true }),
  f("partner.gender", "Płeć Partnera (formy Pan/Pani)", {
    kind: "gender",
    group: "Partner",
    source: "candidate",
    source_label: "kandydat",
    required: true,
  }),
  f("partner.name_instrumental", "Imię i nazwisko — narzędnik", {
    group: "Partner",
    source: "candidate",
    source_label: "kandydat",
    required: true,
  }),
  f("partner.company", "Firma (CEIDG)", { group: "Partner", source: "ceidg", source_label: "CEIDG", required: true }),
  f("partner.nip", "NIP", { group: "Partner", source: "ceidg", source_label: "CEIDG", required: true }),
  f("client.name", "Klient i miejsce szkolenia", {
    group: "Szkolenie",
    source: "clients",
    source_label: "lista klientów",
    required: true,
  }),
  f("t.schedule", "Termin(y) szkolenia", { kind: "textarea", group: "Szkolenie", required: true }),
  f("agenda", "Agenda (moduły)", {
    kind: "list",
    group: "Szkolenie",
    item_keys: [
      { key: "no", label: "Nr" },
      { key: "text", label: "Treść" },
    ],
  }),
  f("fees.total", "Wynagrodzenie ryczałtowe netto", { kind: "money", group: "Pieniądze", required: true }),
  f("travel_limit", "Limit zwrotu kosztów dojazdu", { kind: "money", group: "Pieniądze" }),
];

const CHECKS: CustomCheck[] = [
  {
    key: "art22_kp",
    state: "ok",
    text: "Bez znamion etatu: brak kierownictwa, czasu i miejsca pracy wyznaczanych przez spółkę",
    cite: "art. 22 § 1 KP",
    cite_kind: "law",
    cite_state: "unverified",
  },
  {
    key: "art53_pr_aut",
    state: "block",
    text: "Wzór przenosi prawa autorskie — ustaw podpis „na papierze albo kwalifikowany”, inaczej przeniesienie jest nieważne",
    cite: "art. 53 pr. aut.",
    cite_kind: "law",
    cite_state: "unverified",
  },
  {
    key: "art13_rodo",
    state: "ok",
    text: "Klauzula informacyjna dla Partnera jest we wzorze",
    cite: "art. 13 RODO",
    cite_kind: "law",
    cite_state: "unverified",
  },
];

const F = (key: string, label: string) => `<span class="tpl-field" data-field="${key}">${label}</span>`;

const PREVIEW_HTML = [
  `<h1>Umowa o współpracę B2B w zakresie usług szkoleniowych — szkolenie stacjonarne</h1>`,
  `<p>zawarta w dniu ${F("agreement_date", "Data umowy")} roku w Warszawie pomiędzy ${F("company.name", "dane B2B.net")} (…), a ${F("g.pan", "forma Pan/Pani")} ${F("partner.name_instrumental", "Imię i nazwisko — narzędnik")} prowadzącym działalność gospodarczą pod firmą ${F("partner.company", "Firma (CEIDG)")}, NIP ${F("partner.nip", "NIP")}.</p>`,
  `<h2>§ 2</h2>`,
  `<p>1. Przedmiotem Umowy jest przygotowanie oraz przeprowadzenie przez Partnera szkolenia w formie stacjonarnej w siedzibie ${F("client.name", "Klient i miejsce szkolenia")}, zgodnie z agendą określoną w Załączniku nr 1.</p>`,
  `<h2>§ 3</h2>`,
  `<p>2. Szkolenie odbędzie się w ustalonych przez strony terminach: ${F("t.schedule", "Termin(y) szkolenia")}.</p>`,
  `<p>8. Salę szkoleniową i wyposażenie zapewnia Zamawiający albo Klient. Zamawiający zwraca Partnerowi udokumentowane koszty dojazdu do kwoty ${F("travel_limit", "Limit zwrotu kosztów dojazdu")} zł netto.</p>`,
  `<p>9. Przebywając w siedzibie Klienta, Partner przestrzega przekazanych mu zasad bezpieczeństwa, poufności i dostępu obowiązujących u Klienta.</p>`,
  `<h2>§ 5</h2>`,
  `<p>Wynagrodzenie ryczałtowe wynosi ${F("fees.total", "Wynagrodzenie ryczałtowe netto")} zł netto (słownie: ${F("fees.total_words", "Wynagrodzenie ryczałtowe netto — słownie")}).</p>`,
].join("\n");

const DRAFT: CustomVersion = {
  id: 11,
  version_no: 1,
  status: "draft",
  status_label: "szkic",
  name: "Umowa o szkolenie stacjonarne u klienta",
  kind: "contract",
  kind_label: "Umowa",
  description: "Trener z działalnością, szkolenie w siedzibie klienta, ryczałt i zwrot kosztów dojazdu.",
  client_scope: "all",
  client_ids: [],
  signatories: "both",
  signature_form: "any",
  origin: "base",
  base_key: "training_agreement",
  instruction:
    "Szkolenie stacjonarne w siedzibie klienta: sala po stronie klienta, zwrot kosztów dojazdu do limitu, trener przestrzega zasad bezpieczeństwa klienta. Reszta jak w obecnej umowie szkoleniowej.",
  ai_used: true,
  created_by_name: "Osoba Przykładowa",
  created_at: "2026-11-25T10:12:00Z",
  submitted_by_name: null,
  submitted_at: null,
  reviewed_by_name: null,
  reviewed_at: null,
  review_note: null,
  fields: FIELDS,
  changes: [
    {
      op: "replace",
      i: 14,
      before: "1. Przedmiotem Umowy jest przygotowanie oraz przeprowadzenie przez Partnera szkolenia w formie zdalnej, zgodnie z agendą określoną w Załączniku nr 1.",
      after: "1. Przedmiotem Umowy jest przygotowanie oraz przeprowadzenie przez Partnera szkolenia w formie stacjonarnej w siedzibie {{ client.name }}, zgodnie z agendą określoną w Załączniku nr 1.",
      context: "",
      reason: "forma stacjonarna u klienta",
    },
    {
      op: "insert_after",
      i: 22,
      before: "",
      after: "8. Salę szkoleniową i wyposażenie zapewnia Zamawiający albo Klient. Zamawiający zwraca Partnerowi udokumentowane koszty dojazdu do kwoty {{ travel_limit }} zł netto.",
      context: "7. …",
      reason: "zwrot kosztów dojazdu do limitu",
    },
    {
      op: "insert_after",
      i: 22,
      before: "",
      after: "9. Przebywając w siedzibie Klienta, Partner przestrzega przekazanych mu zasad bezpieczeństwa, poufności i dostępu obowiązujących u Klienta.",
      context: "7. …",
      reason: "zasady bezpieczeństwa klienta",
    },
  ],
  warnings: [],
  checks: CHECKS,
  problems: [],
  unused_fields: [],
  preview_html: PREVIEW_HTML,
};

const DETAIL_DRAFT: CustomTemplateDetail = {
  id: 5,
  withdrawn_at: null,
  withdrawn_by_name: null,
  withdrawn_reason: null,
  working: DRAFT,
  active: null,
  history: [],
  can_edit: true,
  can_review: false,
  can_withdraw: false,
  can_new_version: false,
};

const DETAIL_PENDING: CustomTemplateDetail = {
  ...DETAIL_DRAFT,
  working: {
    ...DRAFT,
    status: "pending",
    status_label: "do zatwierdzenia",
    signature_form: "written",
    checks: CHECKS.map((c) => (c.key === "art53_pr_aut" ? { ...c, state: "ok", text: "Wzór przenosi prawa autorskie: podpis na papierze albo kwalifikowany jest ustawiony" } : c)),
    submitted_by_name: "Osoba Przykładowa",
    submitted_at: "2026-11-25T10:40:00Z",
  },
  can_edit: false,
  can_review: true,
};

const LIST: CustomTemplatesList = {
  is_admin: true,
  templates: [
    {
      id: 5,
      name: "Umowa o szkolenie stacjonarne u klienta",
      kind: "contract",
      kind_label: "Umowa",
      description: "",
      withdrawn: false,
      active_version_no: null,
      active_approved_at: null,
      working_status: "pending",
      working_status_label: "do zatwierdzenia",
      working_version_no: 1,
      author_name: "Osoba Przykładowa",
    },
    {
      id: 3,
      name: "Umowa o udziale w rekrutacji (klient przykładowy)",
      kind: "preliminary",
      kind_label: "Umowa przedwstępna",
      description: "",
      withdrawn: false,
      active_version_no: 2,
      active_approved_at: "2026-11-20T09:00:00Z",
      working_status: null,
      working_status_label: null,
      working_version_no: null,
      author_name: "Administrator Przykładowy",
    },
  ],
};

const CUSTOM_TYPE: CustomDocumentType = {
  key: "custom:3",
  template_id: 3,
  version_id: 31,
  version_no: 2,
  label: "Umowa o szkolenie stacjonarne u klienta",
  description: "Trener z działalnością, szkolenie w siedzibie klienta, ryczałt i zwrot kosztów dojazdu.",
  kind: "contract",
  kind_label: "Umowa",
  client_scope: "all",
  client_ids: [],
  signatories: "both",
  signature_form: "written",
  approved_at: "2026-11-25T11:00:00Z",
  fields: FIELDS,
};

const TYPES_RESPONSE: DocumentTypesResponse = {
  types: [],
  ref_labels: {},
  ref_defaults: {},
  mandate_forms: [],
  custom_types: [CUSTOM_TYPE],
};

// ── Zasiew ──────────────────────────────────────────────────────────────────

const FUTURE = Date.now() + 365 * 24 * 3600 * 1000;

function seededClient(): QueryClient {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  const opts = { updatedAt: FUTURE };
  qc.setQueryData(b2bDocumentsKeys.types(), TYPES_RESPONSE, opts);
  qc.setQueryData(customTemplatesKeys.list(), LIST, opts);
  qc.setQueryData(
    customTemplatesKeys.bases(),
    {
      bases: [
        {
          key: "training_agreement",
          label: "Umowa B2B — szkolenia",
          description: "Umowa o współpracę B2B w zakresie usług szkoleniowych z agendą i klauzulą RODO. Dziś: szkolenie zdalne.",
        },
      ],
      model_available: true,
    },
    opts,
  );
  qc.setQueryData(customTemplatesKeys.prefill(3, null, null), { values: { agreement_date: "2026-11-25", "partner.gender": "m" } }, opts);
  qc.setQueryData(["custom-document-clients"], [], opts);
  return qc;
}

function useNetworkBlocked() {
  const [interceptorId] = useState(() =>
    api.interceptors.request.use(() =>
      Promise.reject(
        Object.assign(new Error("Harness /preview/custom-templates nie wysyła zapytań."), {
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

type View = "brief" | "draft" | "pending" | "list" | "wizard";

const VIEWS: { key: View; label: string }[] = [
  { key: "brief", label: "1. Opis" },
  { key: "draft", label: "2. Szkic i pola" },
  { key: "pending", label: "3. Zatwierdzenie (admin)" },
  { key: "list", label: "Lista wzorów" },
  { key: "wizard", label: "Nowy dokument → Wzory własne" },
];

export default function CustomTemplatesPreviewPage() {
  useNetworkBlocked();
  const [client] = useState(seededClient);
  const [view, setView] = useState<View>("draft");
  // `?view=` po montażu — ten sam pierwszy render na serwerze i w przeglądarce.
  useEffect(() => {
    const v = new URLSearchParams(window.location.search).get("view");
    const found = VIEWS.find((x) => x.key === v);
    if (found) setView(found.key);
  }, []);
  return (
    <QueryClientProvider client={client}>
      <ToastProvider>
        <main className="mx-auto max-w-[1280px] space-y-4 bg-background p-4">
          <div className="flex flex-wrap gap-2">
            {VIEWS.map((v) => (
              <Button key={v.key} size="sm" variant={view === v.key ? "primary" : "outline"} onClick={() => setView(v.key)}>
                {v.label}
              </Button>
            ))}
          </div>
          {view === "brief" ? (
            <TemplateStudio templateId={null} onTemplate={() => undefined} onClose={() => undefined} />
          ) : null}
          {view === "draft" ? (
            <TemplateStudio
              templateId={5}
              initialDetail={DETAIL_DRAFT}
              onTemplate={() => undefined}
              onClose={() => undefined}
            />
          ) : null}
          {view === "pending" ? (
            <TemplateStudio
              templateId={5}
              initialDetail={DETAIL_PENDING}
              onTemplate={() => undefined}
              onClose={() => undefined}
            />
          ) : null}
          {view === "list" ? (
            <div className="rounded-xl border border-border bg-card p-4">
              <CustomTemplatesPanelView
                state="ready"
                data={LIST}
                onRetry={() => undefined}
                onOpen={() => undefined}
                onNew={() => undefined}
                canGenerate
              />
            </div>
          ) : null}
          {view === "wizard" ? (
            <DocumentWizard typesData={TYPES_RESPONSE} onClose={() => undefined} onNewTemplate={() => undefined} />
          ) : null}
        </main>
      </ToastProvider>
    </QueryClientProvider>
  );
}
