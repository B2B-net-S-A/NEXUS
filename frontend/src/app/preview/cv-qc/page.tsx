"use client";

// Publiczny harness okna QC CV (Rekrutacja v5). Dane fikcyjne, ZERO zapytań:
// wynik QC idzie do okna propsem (`CvQcDialogView`), propozycje AI są
// zasiane w cache pod tym samym kluczem, którego używa komponent
// (`cvQcFixesQueryKey`), a interceptor odcina sieć — przyciski poprawek
// kończą się komunikatem o błędzie, nic nie trafia do API (pilnuje
// `harness-seeds.test.ts`).
//
// `?state=` — `fail` (domyślnie: umiejętność krytyczna bez opisu + treść spoza
// oryginału), `pass`, `nocv`, `overridden`, `nocritical`, `external` (plik
// Word/PDF spoza NEXUSA). `?as=recruiter` — bez „Przepuść mimo QC”.

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { CvQcDialogView } from "@/components/v2/recruitment/CvQcDialog";
import { api } from "@/lib/api";
import { cvQcFixesQueryKey, type QcCheck, type QcFixesResponse, type QcResult } from "@/lib/api/cvQc";
import { useAuthStore } from "@/store/auth";

const STAGE_ID = 1;

const ok = (key: string, label: string, severity: QcCheck["severity"], summary = "OK"): QcCheck => ({
  key,
  label,
  severity,
  status: "pass",
  summary,
  items: [],
});

const FAILING: QcResult = {
  stage_id: STAGE_ID,
  candidate_id: 1,
  candidate_name: "Anna Przykładowa",
  job_id: 1,
  job_title: "Senior Java Developer",
  client_name: "Bank Przykładowy",
  passed: false,
  blocking_failed: 2,
  warnings_count: 4,
  override: null,
  run_id: 10,
  computed_at: "2026-10-02T10:00:00Z",
  cv: {
    source: "branded_draft",
    editable: true,
    stage_id: STAGE_ID,
    generated_document_id: 5,
    document_id: null,
    filename: null,
    bold_known: true,
    updated_at: "2026-10-02T09:42:00Z",
    blocks: [
      { kind: "h", section: "summary", runs: [{ t: "Podsumowanie", b: false }] },
      {
        kind: "p",
        section: null,
        runs: [
          { t: "Programistka backendu w systemach płatniczych, 9 lat doświadczenia. Na co dzień ", b: false },
          { t: "Java", b: true },
          { t: " 17 i ", b: false },
          { t: "Spring Boot", b: true },
          { t: "; zna też GraphQL i Postgres.", b: false },
        ],
      },
      { kind: "h", section: "experience", runs: [{ t: "Doświadczenie", b: false }] },
      { kind: "p", section: "role", runs: [{ t: "Senior Java Developer", b: true }, { t: "  03.2021 – 06.2024", b: false }] },
      { kind: "p", section: "employer", runs: [{ t: "Firma Alfa", b: false }] },
      {
        kind: "li",
        section: null,
        runs: [
          { t: "Rozwijała moduł rozliczeń kart w ", b: false },
          { t: "Java", b: true },
          { t: " 17 i ", b: false },
          { t: "Spring Boot", b: true },
          { t: ", obsługujący 2 mln transakcji dziennie.", b: false },
        ],
      },
      { kind: "li", section: null, runs: [{ t: "Projektowała integracje z systemem transakcyjnym banku.", b: false }] },
      {
        kind: "p",
        section: "technologies",
        runs: [
          { t: "Technologie: ", b: false },
          { t: "Java", b: true },
          { t: ", ", b: false },
          { t: "Spring Boot", b: true },
          { t: ", ", b: false },
          { t: "Hibernate", b: true },
          { t: ", JAXB", b: false },
        ],
      },
      { kind: "p", section: "role", runs: [{ t: "Java Developer", b: true }, { t: "  01.2018 – 02.2021", b: false }] },
      { kind: "p", section: "employer", runs: [{ t: "Firma Beta", b: false }] },
      {
        kind: "li",
        section: null,
        runs: [
          { t: "Utrzymywała system sprzedaży kuponów w ", b: false },
          { t: "Java", b: true },
          { t: " 11.", b: false },
        ],
      },
      {
        kind: "p",
        section: "technologies",
        runs: [
          { t: "Technologie: ", b: false },
          { t: "Java", b: true },
          { t: ", ", b: false },
          { t: "Hibernate", b: true },
          { t: ", Spring MVC", b: false },
        ],
      },
      { kind: "p", section: "role", runs: [{ t: "Java Developer", b: true }, { t: "  06.2015 – 12.2017", b: false }] },
      { kind: "p", section: "employer", runs: [{ t: "Firma Gamma", b: false }] },
      {
        kind: "li",
        section: null,
        runs: [
          { t: "Budowała usługi ", b: false },
          { t: "REST API", b: true },
          { t: " w ", b: false },
          { t: "Java", b: true },
          { t: " dla systemu billingowego.", b: false },
        ],
      },
      {
        kind: "p",
        section: "rodo",
        runs: [
          {
            t: "Wyrażam zgodę na przetwarzanie moich danych osobowych zawartych w przekazanych przeze mnie dokumentach w celach związanych z moim udziałem w niniejszym procesie rekrutacyjnym.",
            b: false,
          },
        ],
      },
    ],
  },
  original_cv: { source: "snapshot", filename: "anna_cv.pdf", text: "…" },
  client_request: {
    must: ["Java 17", "Hibernate", "Spring Boot 3.4+", "Kafka w mikroserwisach", "JUnit 5", "Liquibase", "Confluence"],
    nice: ["Kubernetes", "GraphQL"],
    critical: ["Java 17", "Hibernate"],
    critical_source: "suggested",
  },
  checks: [
    ok("cv_present", "CV firmowe jest przygotowane", "blocking"),
    {
      key: "critical_skills",
      label: "Umiejętności krytyczne są w CV i opisane w rolach",
      severity: "blocking",
      status: "fail",
      summary: "1/2",
      items: [
        {
          requirement: "Hibernate",
          role: "Senior Java Developer · Firma Alfa",
          detail: "Jest tylko na liście technologii — dopisz zdanie, co kandydat w tej roli z tym robił.",
          fix: "ai",
          role_index: 0,
        },
        {
          requirement: "Hibernate",
          role: "Java Developer · Firma Beta",
          detail: "Jest tylko na liście technologii — dopisz zdanie, co kandydat w tej roli z tym robił.",
          fix: "ai",
          role_index: 1,
        },
      ],
    },
    {
      key: "no_unsupported",
      label: "CV nie twierdzi niczego spoza oryginału",
      severity: "blocking",
      status: "fail",
      summary: "1 do wyjaśnienia",
      items: [
        {
          requirement: "GraphQL",
          term: "GraphQL",
          detail: "Jest w CV, a nie ma tego w oryginale ani w notatkach — usuń albo potwierdź.",
          fix: "remove_term",
        },
      ],
    },
    ok("client_rules", "Reguły klienta (stawki, kontakt, zgoda RODO)", "blocking"),
    {
      key: "must_in_cv",
      label: "Pozostałe wymagania klienta są w CV",
      severity: "warning",
      status: "fail",
      summary: "1/5",
      items: [
        { requirement: "Kafka w mikroserwisach", detail: "Brak w CV — w oryginale jest, dopisz w roli.", fix: "ai" },
        { requirement: "JUnit 5", detail: "Brak w CV i w oryginale — zapytaj kandydata.", fix: "ask_candidate" },
        { requirement: "Liquibase", detail: "Brak w CV i w oryginale — zapytaj kandydata.", fix: "ask_candidate" },
        { requirement: "Confluence", detail: "Brak w CV i w oryginale — zapytaj kandydata.", fix: "ask_candidate" },
      ],
    },
    ok("must_bolded", "Must-have są pogrubione", "warning", "3/3"),
    {
      key: "must_in_roles",
      label: "Pozostałe wymagania opisane w rolach z oryginału",
      severity: "warning",
      status: "fail",
      summary: "1 do uzupełnienia",
      items: [
        {
          requirement: "Kafka w mikroserwisach",
          role: "Senior Java Developer · Firma Alfa",
          detail: "Brak w tej roli, a w oryginale jest.",
          fix: "ai",
          role_index: 0,
        },
      ],
    },
    {
      key: "years_header",
      label: "Lata doświadczenia zgodne z historią",
      severity: "warning",
      status: "manual",
      summary: "„9 lat doświadczenia” — historia bez pełnych dat, sprawdź ręcznie",
      items: [],
    },
    ok("dates", "Każda rola ma daty", "warning", "3/3"),
    {
      key: "nice_bolded",
      label: "Nice-to-have są pogrubione",
      severity: "warning",
      status: "fail",
      summary: "0/1",
      items: [{ requirement: "GraphQL", term: "GraphQL", detail: "Jest w CV, ale nie jest pogrubione.", fix: "bold_all" }],
    },
    {
      key: "spelling",
      label: "Pisownia technologii",
      severity: "warning",
      status: "fail",
      summary: "1 do poprawy",
      items: [{ term: "Postgres", detail: "„Postgres” → „PostgreSQL”", fix: "spelling" }],
    },
    ok("title_matches_role", "Tytuł CV zgodny ze stanowiskiem", "warning"),
    ok("bold_unsupported", "Pogrubienia mają pokrycie w oryginale", "warning"),
  ],
};

const PASSING: QcResult = {
  ...FAILING,
  passed: true,
  blocking_failed: 0,
  checks: FAILING.checks.map((c) =>
    c.severity === "blocking" ? { ...c, status: "pass", items: [], summary: c.key === "critical_skills" ? "2/2" : "OK" } : c,
  ),
};

const NO_CRITICAL: QcResult = {
  ...PASSING,
  client_request: { ...FAILING.client_request, critical: [], critical_source: "none" },
  checks: PASSING.checks.map((c) =>
    c.key === "critical_skills"
      ? { ...c, status: "skip", summary: "Rekrutacja nie ma umiejętności krytycznych" }
      : c,
  ),
};

const OVERRIDDEN: QcResult = {
  ...FAILING,
  override: {
    reason: "Klient prosił o krótsze CV — wysyłamy bez opisów starszych ról",
    by_name: "Piotr Przykładowy",
    at: "2026-10-02T10:20:00Z",
  },
};

const NO_CV: QcResult = {
  ...FAILING,
  blocking_failed: 1,
  warnings_count: 0,
  cv: null,
  checks: FAILING.checks.map((c) =>
    c.key === "cv_present"
      ? {
          ...c,
          status: "fail",
          summary: "Brak CV firmowego",
          items: [{ detail: "Nie ma jeszcze CV firmowego dla tej rekrutacji.", fix: "generate_cv" }],
        }
      : { ...c, status: "skip", summary: "Brak CV", items: [] },
  ),
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
    c.key === "must_bolded" || c.key === "nice_bolded"
      ? { ...c, status: "manual", items: [], summary: "Pogrubień nie da się odczytać z PDF-a" }
      : c,
  ),
};

const FIXES: QcFixesResponse = {
  status: "ok",
  cached: false,
  fixes: [
    {
      id: "f1",
      check_key: "critical_skills",
      requirement: "Hibernate",
      role: "Senior Java Developer · Firma Alfa",
      cv_role_label: "Senior Java Developer 03.2021 – 06.2024 · Firma Alfa",
      current_text: "Projektowała integracje z systemem transakcyjnym banku.",
      proposed_text:
        "Projektowała integracje z systemem transakcyjnym banku; warstwę zapisu zamówień oparła na **Hibernate** (mapowania, cache drugiego poziomu).",
      source: "original",
      source_quote: "persistence layer in Hibernate (mappings, second-level cache)",
    },
    {
      id: "f2",
      check_key: "must_in_roles",
      requirement: "Kafka w mikroserwisach",
      role: "Senior Java Developer · Firma Alfa",
      cv_role_label: "Senior Java Developer 03.2021 – 06.2024 · Firma Alfa",
      current_text: null,
      proposed_text: "Budowała komunikację między mikroserwisami na **Kafka** (zdarzenia rozliczeń, ok. 40 tematów).",
      source: "notes",
      source_quote: "Kafka: producent/konsument, ok. 40 tematów w rozliczeniach",
    },
  ],
};

const STATES = {
  fail: { label: "Do poprawy", data: FAILING },
  pass: { label: "Przechodzi", data: PASSING },
  nocv: { label: "Bez CV firmowego", data: NO_CV },
  overridden: { label: "Przepuszczone", data: OVERRIDDEN },
  nocritical: { label: "Bez krytycznych", data: NO_CRITICAL },
  external: { label: "Plik spoza NEXUSA", data: EXTERNAL },
} as const;
type HarnessState = keyof typeof STATES;

export default function CvQcPreviewPage() {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(true);
  const [state, setState] = useState<HarnessState>("fail");
  const [moved, setMoved] = useState(false);
  const [queryClient] = useState(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false } },
    });
    qc.setQueryData<QcFixesResponse>(cvQcFixesQueryKey(STAGE_ID), FIXES);
    return qc;
  });

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = params.get("state");
    if (requested && requested in STATES) setState(requested as HarnessState);
    const role = params.get("as") === "recruiter" ? "recruiter" : "delivery_lead";
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: role === "recruiter" ? "Preview Rekruter" : "Preview Delivery Lead",
        role,
        roles: [role],
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
          <div className="flex flex-wrap gap-x-3 gap-y-2 text-sm">
            {(Object.keys(STATES) as HarnessState[]).map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={state === key}
                onClick={() => {
                  setState(key);
                  setMoved(false);
                  setOpen(true);
                }}
                className={state === key ? "font-semibold text-primary" : "text-foreground"}
              >
                {STATES[key].label}
              </button>
            ))}
            <button type="button" className="ml-auto text-primary underline" onClick={() => setOpen(true)}>
              Otwórz okno
            </button>
          </div>
          {moved ? (
            <p role="status" className="text-sm text-muted-foreground">
              „Przesuń dalej” — na Tablicy otwiera się tu okno ruchu na następny etap.
            </p>
          ) : null}
        </main>
        <CvQcDialogView
          key={state}
          stageId={STAGE_ID}
          open={open}
          onClose={() => setOpen(false)}
          onMoveNext={() => {
            setOpen(false);
            setMoved(true);
          }}
          data={STATES[state].data}
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
