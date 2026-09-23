"use client";

// Publiczny harness okna QC CV (Rekrutacja v5). Dane fikcyjne, ZERO zapytań:
// wynik QC idzie do okna propsem (`CvQcDialogView`), propozycje AI są
// zasiane w cache pod tym samym kluczem, którego używa komponent
// (`cvQcFixesQueryKey`), a interceptor odcina sieć — przyciski poprawek
// kończą się komunikatem o błędzie, nic nie trafia do API (pilnuje
// `harness-seeds.test.ts`). `?state=pass` — CV przechodzi, `?state=external`
// — plik Word/PDF spoza NEXUSA.

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { CvQcDialogView } from "@/components/v2/recruitment/CvQcDialog";
import { api } from "@/lib/api";
import { cvQcFixesQueryKey, type QcFixesResponse, type QcResult } from "@/lib/api/cvQc";
import { useAuthStore } from "@/store/auth";

const STAGE_ID = 1;

const FAILING: QcResult = {
  stage_id: STAGE_ID,
  candidate_id: 1,
  candidate_name: "Anna Przykładowa",
  job_id: 1,
  job_title: "Senior Java Developer",
  client_name: "Bank Przykładowy",
  passed: false,
  blocking_failed: 3,
  warnings_count: 2,
  override: null,
  run_id: 10,
  computed_at: "2026-09-24T10:00:00Z",
  cv: {
    source: "branded_draft",
    editable: true,
    stage_id: STAGE_ID,
    generated_document_id: 5,
    document_id: null,
    filename: null,
    bold_known: true,
    updated_at: "2026-09-23T10:42:00Z",
    blocks: [
      { kind: "h", section: "summary", runs: [{ t: "Podsumowanie", b: false }] },
      {
        kind: "p",
        section: null,
        runs: [
          { t: "Backend developer specjalizująca się w systemach płatniczych. Na co dzień ", b: false },
          { t: "Java 17", b: true },
          { t: ", ", b: false },
          { t: "Spring Boot", b: true },
          { t: ", Kafka, ", b: false },
          { t: "PostgreSQL", b: true },
          { t: "; zna też Docker i GraphQL.", b: false },
        ],
      },
      { kind: "h", section: "skills", runs: [{ t: "Technologie", b: false }] },
      {
        kind: "p",
        section: null,
        runs: [
          { t: "Java 17", b: true },
          { t: " · ", b: false },
          { t: "Spring Boot", b: true },
          { t: " · Kafka · ", b: false },
          { t: "PostgreSQL", b: true },
          { t: " · Kubernetes · Docker · GraphQL · Postgres", b: false },
        ],
      },
      { kind: "h", section: "experience", runs: [{ t: "Doświadczenie", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Firma Alfa — Senior Java Developer", b: true }, { t: "  03.2022 – obecnie", b: false }] },
      {
        kind: "li",
        section: null,
        runs: [
          { t: "Projektowała usługi rozliczeń sprzedawców w ", b: false },
          { t: "Java 17", b: true },
          { t: " i ", b: false },
          { t: "Spring Boot", b: true },
          { t: ", obsługujące 2 mln transakcji dziennie.", b: false },
        ],
      },
      { kind: "li", section: null, runs: [{ t: "Odpowiadała za integracje asynchroniczne między zespołami.", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Firma Beta — Java Developer", b: true }, { t: "  06.2019 – 02.2022", b: false }] },
      { kind: "li", section: null, runs: [{ t: "Rozwijała moduł przelewów SEPA w zespole 8 osób.", b: false }] },
      { kind: "li", section: null, runs: [{ t: "Wdrażała testy kontraktowe i CI w GitLabie.", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Firma Gamma — Junior Developer", b: true }, { t: "  09.2017 – 05.2019", b: false }] },
      {
        kind: "li",
        section: null,
        runs: [
          { t: "Utrzymanie systemu obiegu dokumentów w ", b: false },
          { t: "Java 8", b: true },
          { t: ", poprawki i raporty SQL.", b: false },
        ],
      },
    ],
  },
  original_cv: { source: "snapshot", filename: "anna_cv.pdf", text: "…" },
  client_request: { must: ["Java", "Spring Boot", "Kafka", "PostgreSQL"], nice: ["Kubernetes", "GraphQL"] },
  checks: [
    {
      key: "must_in_cv",
      label: "Wszystkie must-have są w CV",
      severity: "blocking",
      status: "pass",
      summary: "4/4",
      items: [],
    },
    {
      key: "must_bolded",
      label: "Must-have pogrubione wszędzie, gdzie występują",
      severity: "blocking",
      status: "fail",
      summary: "2 miejsca",
      items: [
        { requirement: "Kafka", term: "Kafka", detail: "Niepogrubiona w podsumowaniu i technologiach.", fix: "bold_all" },
      ],
    },
    {
      key: "must_in_roles",
      label: "Must-have opisane w każdym stanowisku, w którym były używane",
      severity: "blocking",
      status: "fail",
      summary: "3 braki",
      items: [
        { requirement: "Java", role: "Firma Beta — Java Developer", detail: "W oryginale: „SEPA transfers module (Java 11, Spring Boot)”.", fix: "ai" },
        { requirement: "Spring Boot", role: "Firma Beta — Java Developer", detail: null, fix: "ai" },
        { requirement: "Kafka", role: "Firma Alfa — Senior Java Developer", detail: "Kafka używana tu wg notatki ze screeningu.", fix: "ai" },
      ],
    },
    {
      key: "no_unsupported",
      label: "Nic bez pokrycia w oryginale",
      severity: "blocking",
      status: "fail",
      summary: "1 pozycja",
      items: [
        { term: "Docker", role: "Podsumowanie", detail: "W oryginale Docker nie występuje w żadnym stanowisku.", fix: "remove_term" },
        { term: "Docker", role: "Podsumowanie", detail: "Albo zapytaj kandydatkę.", fix: "ask_candidate" },
      ],
    },
    { key: "years_header", label: "Lata doświadczenia zgodne z datami", severity: "blocking", status: "pass", summary: "8 lat", items: [] },
    { key: "dates", label: "Daty kompletne, bez nakładania, format klienta", severity: "blocking", status: "pass", summary: "OK", items: [] },
    { key: "client_rules", label: "Reguły klienta", severity: "blocking", status: "pass", summary: "4/4", items: [] },
    {
      key: "nice_bolded",
      label: "Nice-to-have pogrubione",
      severity: "warning",
      status: "fail",
      summary: "1 miejsce",
      items: [{ requirement: "GraphQL", term: "GraphQL", detail: null, fix: "bold_all" }],
    },
    {
      key: "spelling",
      label: "Pisownia technologii",
      severity: "warning",
      status: "fail",
      summary: "1 miejsce",
      items: [{ term: "Postgres", detail: "„Postgres” → „PostgreSQL”", fix: "spelling" }],
    },
    { key: "title_matches_role", label: "Stanowisko w nagłówku = rola z rekrutacji", severity: "warning", status: "pass", summary: "OK", items: [] },
  ],
};

const PASSING: QcResult = {
  ...FAILING,
  passed: true,
  blocking_failed: 0,
  warnings_count: 0,
  checks: FAILING.checks.map((c) => ({ ...c, status: "pass", items: [], summary: c.summary && /\d/.test(c.summary) ? c.summary : "OK" })),
};

const EXTERNAL: QcResult = {
  ...FAILING,
  cv: {
    ...FAILING.cv!,
    source: "document",
    editable: false,
    filename: "Anna_B2B_Bank.pdf",
    bold_known: false,
    generated_document_id: null,
    document_id: 9,
  },
  checks: FAILING.checks.map((c) =>
    c.key === "must_bolded" || c.key === "nice_bolded" ? { ...c, status: "manual", items: [], summary: null } : c,
  ),
  blocking_failed: 2,
};

const FIXES: QcFixesResponse = {
  status: "ok",
  cached: false,
  fixes: [
    {
      id: "f1",
      check_key: "must_in_roles",
      requirement: "Java, Spring Boot",
      role: "Firma Beta — Java Developer",
      current_text: "Rozwijała moduł przelewów SEPA w zespole 8 osób.",
      proposed_text: "Rozwijała moduł przelewów SEPA w **Java 11** i **Spring Boot** — nowe typy zleceń i walidacje zgodne z EPC.",
      source: "original",
      source_quote: "SEPA transfers module (Java 11, Spring Boot), new order types",
    },
    {
      id: "f2",
      check_key: "must_in_roles",
      requirement: "Kafka",
      role: "Firma Alfa — Senior Java Developer",
      current_text: "Odpowiadała za integracje asynchroniczne między zespołami.",
      proposed_text: "Budowała integracje asynchroniczne między zespołami na **Kafce** (zdarzenia rozliczeń, ok. 40 tematów).",
      source: "notes",
      source_quote: "Kafka: producent/konsument, ~40 topiców w rozliczeniach",
    },
  ],
};

const STATES = { fail: FAILING, pass: PASSING, external: EXTERNAL } as const;
type HarnessState = keyof typeof STATES;

export default function CvQcPreviewPage() {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(true);
  const [state, setState] = useState<HarnessState>("fail");
  const [queryClient] = useState(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false } },
    });
    qc.setQueryData<QcFixesResponse>(cvQcFixesQueryKey(STAGE_ID), FIXES);
    return qc;
  });

  useEffect(() => {
    const requested = new URLSearchParams(window.location.search).get("state");
    if (requested && requested in STATES) setState(requested as HarnessState);
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Preview Delivery Lead",
        role: "delivery_lead",
        roles: ["delivery_lead"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
      } as never,
      token: "preview",
    } as never);
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
          <h1 className="text-lg font-semibold">Podgląd: okno QC CV</h1>
          <div className="flex flex-wrap gap-2 text-sm">
            {(Object.keys(STATES) as HarnessState[]).map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={state === key}
                onClick={() => {
                  setState(key);
                  setOpen(true);
                }}
                className={state === key ? "font-semibold text-primary" : "text-foreground"}
              >
                {key === "fail" ? "Nie przechodzi" : key === "pass" ? "Przechodzi" : "Plik spoza NEXUSA"}
              </button>
            ))}
            <button type="button" className="ml-auto text-primary underline" onClick={() => setOpen(true)}>
              Otwórz okno
            </button>
          </div>
        </main>
        <CvQcDialogView
          key={state}
          stageId={STAGE_ID}
          open={open}
          onClose={() => setOpen(false)}
          data={STATES[state]}
          loading={false}
          fetching={false}
          state="ready"
          refreshFailed={false}
          onRecheck={() => undefined}
        />
      </ToastProvider>
    </QueryClientProvider>
  );
}
