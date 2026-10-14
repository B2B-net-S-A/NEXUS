"use client";

// Publiczny harness karty „CV do klienta” w procesie (PR 4, 13.10.2026).
// Dane fikcyjne, ZERO zapytań: interceptor odcina sieć, a każdy klucz karty,
// panelu „Z czego powstało” i liczby rzeczy do sprawdzenia jest zasiany tymi
// samymi funkcjami kluczy co komponenty (pilnuje `harness-seeds.test.ts`).
//
// Pięć osób, każda w swoim stanie karty:
//  - brak CV, panel „Z czego powstało” otwarty (domyślne przełączniki),
//  - „Wygeneruj ponownie” przy gotowym CV — przełączniki z ostatniej wersji,
//  - gotowe CV z jedną liczbą rzeczy do sprawdzenia i „Sprawdź i popraw”,
//  - gotowe CV bez uwag („Nic do sprawdzenia”),
//  - QC nie odpowiada (klucz QC celowo niezasiany — karta nie udaje zera),
//  - po „Zapisz i przekaż dalej” (14.10.2026): blok postępu screening → CV →
//    QC; automat „generuje” CV, po 12 s karta dostaje gotowe CV z liczbą QC,
//    a „Następna w Screeningu” tylko pisze na stronie, kogo by otworzyła,
//  - po przekazaniu, gdy automat pominął osobę (powód z „Pracy w tle”).
//
// Karta po przekazaniu pyta serwer co 4 s. Te odczyty (lista generacji, CV
// etapu, „Praca w tle”) odpowiada pamięć harnessu — dane z cache, bez sieci.
//
// Edytor CV 3, „Ekran 5” (14.10.2026): gotowe CV ma miniaturę pierwszej strony
// (przykładowy PDF z `public/`, nie z API) i menu „⋯”, a panel „Z czego
// powstało” jest zwinięty do jednego zdania z „Zmień”.

import { useEffect, useState } from "react";
import { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { CvToClientCard } from "@/components/v2/recruitment/CvToClientCard";
import { api } from "@/lib/api";
import type { CvEditorIssuesData } from "@/lib/api/cvEditorIssues";
import type { QcCheck } from "@/lib/api/cvQc";
import { cvAiSourcesQueryKey, type CvAiSources } from "@/lib/cv-ai-sources";
import type { RecruitmentOption } from "@/lib/cv-generator";
import {
  cvToClientIssuesQueryKey,
  cvToClientQcQueryKey,
  cvToClientRowsQueryKey,
  stageBrandedQueryKey,
  stageCvSourcesQueryKey,
  type StageGeneratedCvRow,
} from "@/lib/cv-to-client";
import { BACKGROUND_EVENTS_STEP, jobBackgroundEventsQueryKey } from "@/lib/job-background-events";
import { useAuthStore } from "@/store/auth";

const JOB_ID = 88;

// Miniatura, okno stron i „Pobierz PDF” karty pokazują strony PDF z pliku Word
// (zapas okna stron: sam plik Word).
// W harnessie nie ma serwera, który złożyłby je z treści, a POST-y są
// blokowane — przykładowe pliki w szablonie firmowym z fikcyjnym CV (Word
// z kodu `cv_approved_docx`, PDF z niego przez LibreOffice z Montserrat).
const PREVIEW_FILE = "/preview/cv-to-client/cv-firmowe-przyklad.docx";
const PREVIEW_PAGES = "/preview/cv-to-client/cv-firmowe-przyklad.pdf";
async function loadStatic(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return { blob: await response.blob(), filename: path.slice(path.lastIndexOf("/") + 1) };
}
const loadPreviewFile = () => loadStatic(PREVIEW_FILE);
const loadPreviewPages = () => loadStatic(PREVIEW_PAGES);
const CLIENT_ID = 7;
const REVISION = 2;
const FRESH = { updatedAt: Date.now() + 86_400_000 };

type Variant =
  | "sources"
  | "regenerate"
  | "counter"
  | "clean"
  | "qcdown"
  | "forwarded"
  | "skipped"
  | "rewrite"
  | "sent";

interface Person {
  stageId: number;
  candidateId: number;
  name: string;
  label: string;
  variant: Variant;
}

const PEOPLE: readonly Person[] = [
  { stageId: 701, candidateId: 31, name: "Anna Przykładowa", label: "Brak CV — „Generuj CV” w karcie", variant: "sources" },
  { stageId: 702, candidateId: 32, name: "Jan Kowalski", label: "„Wygeneruj ponownie” — wybór z ostatniej wersji", variant: "regenerate" },
  { stageId: 703, candidateId: 33, name: "Marta Zielińska", label: "Jedna liczba rzeczy do sprawdzenia", variant: "counter" },
  { stageId: 704, candidateId: 34, name: "Piotr Wiśniewski", label: "Gotowe, nic do sprawdzenia", variant: "clean" },
  { stageId: 705, candidateId: 35, name: "Tomasz Wzorcowy", label: "QC nie odpowiada", variant: "qcdown" },
  { stageId: 706, candidateId: 36, name: "Ewa Testowa", label: "Po przekazaniu — CV się generuje", variant: "forwarded" },
  { stageId: 707, candidateId: 37, name: "Olga Wzorcowa", label: "Po przekazaniu — automat pominął osobę", variant: "skipped" },
  { stageId: 708, candidateId: 39, name: "Lena Przykładowa", label: "„Napisz od nowa” — Twoje poprawki zostają", variant: "rewrite" },
  // D3 (14.10.2026): osoba już u klienta — karta bez podmiany CV.
  { stageId: 709, candidateId: 40, name: "Karol Przykładowy", label: "Po „CV wysłane” — bez podmiany CV", variant: "sent" },
];

/** „Napisz od nowa” (PR 5): nowa generacja i podmiana szkicu odpowiadają z pamięci. */
const REWRITE = PEOPLE.find((person) => person.variant === "rewrite")!;
const REWRITTEN_ID = 9990;

/** Bez gotowego CV na starcie: brak, przekazanie w toku, pominięcie automatu. */
const NO_CV_AT_START: ReadonlySet<Variant> = new Set(["sources", "forwarded", "skipped"]);
const FORWARDED: ReadonlySet<Variant> = new Set(["forwarded", "skipped"]);
/** Po tylu ms automat „kończy” CV osoby po przekazaniu. */
const AUTO_CV_READY_MS = 12_000;
const NEXT_IN_SCREENING = { candidateId: 38, name: "Kamil Przykładowy", detail: "czeka 2 dni" };

function recruitment(person: Person): RecruitmentOption {
  return {
    stage_id: person.stageId,
    job_id: JOB_ID,
    job_title: "Senior Java Developer",
    stage: "verified",
    has_champion: true,
    has_notes: true,
    has_cv: true,
    notes_chars: 1240,
    ready: true,
    client_id: CLIENT_ID,
    client_name: "Bank Przykładowy",
    required_champion: false,
    required_notes_min_chars: 0,
    missing_inputs: [],
  };
}

function aiSources(person: Person): CvAiSources {
  return {
    original_cv: {
      document_id: 900 + person.candidateId,
      filename: `${person.name.replace(" ", "_")}_CV.pdf`,
      uploaded_at: "2026-09-12T10:00:00Z",
    },
    champion: true,
    answers: { count: 6, excluded: 2 },
    notes: { count: 4, excluded: 0 },
    transcripts: { count: 3, excluded: 1 },
    prep: { count: 1, excluded: 0 },
    rate_notes: { count: 2, excluded: 0 },
    defaults: { answers: true, notes: true, transcripts: false, prep: false },
    last_used: person.variant === "regenerate" ? { answers: true, notes: true, transcripts: true, prep: false } : null,
  };
}

const failing = (partial: Partial<QcCheck> & Pick<QcCheck, "key" | "label">): QcCheck => ({
  severity: "warning",
  status: "fail",
  summary: null,
  items: [],
  ...partial,
});

/** QC karty: blokada, uwaga i wyciszona uwaga (ta się nie liczy). */
function qcChecks(person: Person): QcCheck[] {
  if (person.variant === "forwarded") {
    return [
      failing({ key: "must_bolded", label: "Must-have pogrubione", items: [{ requirement: "Kafka", term: "Kafka", fix: "bold_all" }] }),
      failing({ key: "spelling", label: "Pisownia technologii", items: [{ term: "Github", fix: "spelling" }] }),
    ];
  }
  if (person.variant !== "counter") return [];
  return [
    failing({
      key: "no_unsupported",
      label: "CV nie twierdzi niczego spoza oryginału",
      severity: "blocking",
      items: [{ term: "Jenkins", fix: "remove_term" }],
    }),
    failing({ key: "must_in_cv", label: "Pozostałe wymagania klienta są w CV", items: [{ requirement: "Kafka", fix: "ai" }] }),
    failing({ key: "dates", label: "Każda rola ma daty", muted: true, items: [{ detail: "Brak miesiąca zakończenia" }] }),
  ];
}

function issues(person: Person): CvEditorIssuesData {
  if (person.variant !== "counter") {
    return { generated_document_id: null, generator_warnings: [], content_review: { status: null, version: null, findings: [] } };
  }
  return {
    generated_document_id: 9000 + person.stageId,
    generator_warnings: [
      // Ta sama rzecz co pozycja QC o Kafce — nie liczy się drugi raz.
      "MUST-HAVE: Kafka",
      "WERYFIKUJ: usunięto „OpenTelemetry” z umiejętności — jest tylko w pytaniu screeningu.",
      "Wyróżnienia: pogrubiono 4 wystąpienia wymagań must-have.",
    ],
    content_review: {
      status: "reviewed",
      version: 1,
      findings: [{ text: "Przeglądy kodu i wdrażanie młodszych programistów.", status: "unsupported" }],
    },
  };
}

/** CV etapu: szkic z generatora albo brak. */
function branded(person: Person, hasCv: boolean) {
  const generatedId = 9000 + person.stageId;
  return {
    status: hasCv ? "draft" : "none",
    from_generator: hasCv,
    generated_document_id: hasCv ? generatedId : null,
    source: hasCv ? "generator" : null,
    origin: null,
    edit_revision: hasCv ? REVISION : 0,
    version: 1,
    candidate_stage_id: person.stageId,
    content_html: hasCv ? "<h2>Podsumowanie</h2><p>Java Developer z 8-letnim doświadczeniem w bankowości.</p>" : null,
    template: null,
    language: "pl",
    updated_at: null,
    updated_by: null,
    updated_by_name: null,
    finalized_at: null,
    finalized_by: null,
    finalized_by_name: null,
    snapshot_filename: null,
    rendered_from_default: false,
  };
}

function readyRow(person: Person, origin: "manual" | "auto"): StageGeneratedCvRow {
  return {
    id: 9000 + person.stageId,
    status: "ready",
    origin,
    content_mode: "tailored",
    language: "pl",
    created_at: "2026-10-13T09:40:00Z",
  };
}

/** Automat skończył CV osoby po przekazaniu — karta zobaczy je przy następnym odczycie. */
function finishAutoCv(qc: QueryClient) {
  for (const person of PEOPLE) {
    if (person.variant !== "forwarded") continue;
    qc.setQueryData(cvToClientRowsQueryKey(person.candidateId, JOB_ID), [readyRow(person, "auto")]);
    qc.setQueryData(stageBrandedQueryKey(person.stageId), branded(person, true));
  }
}

function seed(qc: QueryClient) {
  for (const person of PEOPLE) {
    const hasCv = !NO_CV_AT_START.has(person.variant);
    // Karta: CV etapu, generacje pary, oryginał, „Praca w tle”.
    const rows: StageGeneratedCvRow[] = hasCv
      ? [readyRow(person, "manual")]
      : person.variant === "forwarded"
        ? [{ id: 9000 + person.stageId, status: "processing", origin: "auto", created_at: new Date().toISOString() }]
        : [];
    qc.setQueryData(cvToClientRowsQueryKey(person.candidateId, JOB_ID), rows, FRESH);
    qc.setQueryData(stageBrandedQueryKey(person.stageId), branded(person, hasCv), FRESH);
    qc.setQueryData(
      ["cv-original", person.stageId],
      {
        candidate_stage_id: person.stageId,
        candidate_id: person.candidateId,
        job_id: JOB_ID,
        has_snapshot: true,
        original_cv_filename: `${person.name.replace(" ", "_")}_CV.pdf`,
        original_cv_language: "pl",
        original_snapshot_at: "2026-09-12T10:00:00Z",
        original_snapshot_source: "profile",
        download_url: null,
      },
      FRESH,
    );
    // „Użyj innego CV” — osoba nie ma innych gotowych CV.
    qc.setQueryData(stageCvSourcesQueryKey(person.stageId), [], FRESH);
    qc.setQueryData(candidateQueryKeys.cvDocuments(person.candidateId), [], FRESH);
    qc.setQueryData(["candidate-generated-cvs", person.candidateId], [], FRESH);
    qc.setQueryData(["central-cv-policy", null, person.stageId, false], {}, FRESH);

    // Panel „Z czego powstało”: proces osoby, pliki CV, źródła dla AI, reguły klienta.
    for (const mode of ["polished", "tailored"]) {
      qc.setQueryData(["cv-gen-recruitments", person.candidateId, mode], [recruitment(person)], FRESH);
    }
    qc.setQueryData(
      ["cv-gen-sources", person.candidateId],
      [{ id: 900 + person.candidateId, filename: `${person.name.replace(" ", "_")}_CV.pdf`, is_primary: true, uploaded_at: "2026-09-12T10:00:00Z" }],
      FRESH,
    );
    qc.setQueryData(cvAiSourcesQueryKey(person.stageId), aiSources(person), FRESH);
    qc.setQueryData(["central-cv-policy", null, null, false], {}, FRESH);
    qc.setQueryData(["central-cv-policy", CLIENT_ID, person.stageId, false], {}, FRESH);
    qc.setQueryData(["client-cv-rule", CLIENT_ID], { is_active: false }, FRESH);

    // Jedna liczba rzeczy do sprawdzenia. „QC nie odpowiada” — klucz QC niezasiany.
    // Osoba po przekazaniu ma zasiane QC wersji, którą „dostanie” od automatu.
    const willHaveCv = hasCv || person.variant === "forwarded";
    if (willHaveCv && person.variant !== "qcdown") {
      qc.setQueryData(
        cvToClientQcQueryKey(person.stageId, REVISION),
        { stage_id: person.stageId, cv: { stage_id: person.stageId }, checks: qcChecks(person) },
        FRESH,
      );
    }
    if (willHaveCv) qc.setQueryData(cvToClientIssuesQueryKey(person.stageId, REVISION), issues(person), FRESH);
    // Po „Napisz od nowa” i „Wróć do poprzedniej” szkic ma kolejne wersje.
    if (person.variant === "rewrite") {
      for (const revision of [REVISION + 1, REVISION + 2]) {
        qc.setQueryData(
          cvToClientQcQueryKey(person.stageId, revision),
          { stage_id: person.stageId, cv: { stage_id: person.stageId }, checks: [] },
          FRESH,
        );
        qc.setQueryData(cvToClientIssuesQueryKey(person.stageId, revision), issues(person), FRESH);
      }
    }
  }
  qc.setQueryData(
    jobBackgroundEventsQueryKey(JOB_ID, BACKGROUND_EVENTS_STEP),
    {
      job_id: JOB_ID,
      // Automat pominął osobę po przekazaniu — powód stoi w karcie.
      items: PEOPLE.filter((person) => person.variant === "skipped").map((person) => ({
        id: person.stageId,
        kind: "cv_auto_generate_skipped",
        created_at: new Date().toISOString(),
        reason: "consent_screenshot_required",
        candidate: { id: person.candidateId, name: person.name },
      })),
      limit: BACKGROUND_EVENTS_STEP,
    },
    FRESH,
  );
}

/**
 * Odczyty, o które karta pyta sama po przekazaniu (co 4 s) — odpowiedź z cache
 * harnessu, bez sieci. `undefined` = to nie jest odczyt z pamięci.
 */
/** Zapisy „Napisz od nowa” osoby z harnessu: notatka, generacja, podmiana, powrót. */
function rewriteAnswer(qc: QueryClient, config: InternalAxiosRequestConfig): unknown {
  const url = config.url ?? "";
  const body = (typeof config.data === "string" ? JSON.parse(config.data) : config.data) ?? {};
  const base = `/api/candidates/stages/${REWRITE.stageId}/cv/branded`;
  if (url === "/api/notes" && body.candidate_id === REWRITE.candidateId) return { id: 1 };
  if (url === "/api/cv-generator/generate" && body.stage_id === REWRITE.stageId) {
    qc.setQueryData(cvToClientRowsQueryKey(REWRITE.candidateId, JOB_ID), [
      readyRow(REWRITE, "manual"),
      { ...readyRow(REWRITE, "manual"), id: REWRITTEN_ID, created_at: new Date().toISOString() },
    ]);
    return { id: REWRITTEN_ID, status: "processing", candidate_name: REWRITE.name };
  }
  if (url === `${base}/select-generated`) {
    const next = {
      ...branded(REWRITE, true),
      generated_document_id: REWRITTEN_ID,
      edit_revision: REVISION + 1,
      rewrite: { kept: ["Logistyka Przykład"], recognized: true, can_restore: true },
    };
    qc.setQueryData(stageBrandedQueryKey(REWRITE.stageId), next);
    return next;
  }
  if (url === `${base}/restore-previous`) {
    const next = { ...branded(REWRITE, true), edit_revision: REVISION + 2 };
    qc.setQueryData(stageBrandedQueryKey(REWRITE.stageId), next);
    return next;
  }
  return undefined;
}

function memoryAnswer(qc: QueryClient, config: InternalAxiosRequestConfig): unknown {
  if ((config.method ?? "get").toLowerCase() === "post") return rewriteAnswer(qc, config);
  if ((config.method ?? "get").toLowerCase() !== "get") return undefined;
  const url = config.url ?? "";
  if (url === "/api/cv-generator/generated" && config.params?.job_id === JOB_ID) {
    return qc.getQueryData(cvToClientRowsQueryKey(Number(config.params.candidate_id), JOB_ID));
  }
  const brandedMatch = /^\/api\/candidates\/stages\/(\d+)\/cv\/branded$/.exec(url);
  if (brandedMatch) return qc.getQueryData(stageBrandedQueryKey(Number(brandedMatch[1])));
  if (url === `/api/jobs/${JOB_ID}/background-events`) {
    return qc.getQueryData(jobBackgroundEventsQueryKey(JOB_ID, BACKGROUND_EVENTS_STEP));
  }
  return undefined;
}

function Harness() {
  const [opened, setOpened] = useState<string | null>(null);
  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold text-foreground">CV do klienta — w procesie</h1>
        <p className="text-sm text-muted-foreground">
          Karta z panelu osoby: „Generuj CV” rozwija w karcie zdanie „Z czego powstało” z „Zmień” (bez okna
          generatora), a gotowe CV to miniatura pierwszej strony z liczbą stron, jedna liczba rzeczy do sprawdzenia,
          „Otwórz i popraw”, „Pobierz Word” i menu „⋯”. Po „Zapisz i przekaż dalej” karta pokazuje postęp CV → QC
          i „Następna w Screeningu”.
        </p>
        {opened ? (
          <p role="status" data-testid="harness-opened" className="text-sm text-muted-foreground">
            Panel otworzyłby teraz: {opened}.
          </p>
        ) : null}
      </header>
      <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
        {PEOPLE.map((person) => (
          <section key={person.stageId} aria-label={person.label} className="space-y-2">
            <h2 className="text-sm font-semibold text-foreground">{person.label}</h2>
            <CvToClientCard
              stageId={person.stageId}
              candidateId={person.candidateId}
              candidateName={person.name}
              jobId={JOB_ID}
              jobTitle="Senior Java Developer"
              readOnly={false}
              initialGenerateOpen={person.variant === "sources" || person.variant === "regenerate"}
              forwarded={FORWARDED.has(person.variant)}
              nextInScreening={person.variant === "forwarded" ? NEXT_IN_SCREENING : null}
              onOpenPerson={() => setOpened(NEXT_IN_SCREENING.name)}
              lockedAfterSend={person.variant === "sent"}
              loadStageCvFile={loadPreviewFile}
              loadStageCvPdf={loadPreviewPages}
            />
          </section>
        ))}
      </div>
    </main>
  );
}

export default function CvToClientPreviewPage() {
  const [ready, setReady] = useState(false);
  const [queryClient] = useState(() => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false } },
    });
    seed(qc);
    return qc;
  });

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) => {
      const data = memoryAnswer(queryClient, config);
      if (data !== undefined) {
        config.adapter = async () => ({ data, status: 200, statusText: "OK", headers: {}, config });
        return config;
      }
      return Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config));
    });
    const autoCv = setTimeout(() => finishAutoCv(queryClient), AUTO_CV_READY_MS);
    // Panel generacji jest dla osób z prawem zapisu w Sourcing — fikcyjny rekruter.
    useAuthStore.setState({
      user: {
        id: 1,
        email: "preview@example.com",
        name: "Preview Rekruter",
        role: "recruiter",
        roles: ["recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        effective_section_access: { sourcing: "write", pipeline: "write" },
      } as never,
      realUser: null,
    } as never);
    setReady(true);
    return () => {
      clearTimeout(autoCv);
      api.interceptors.request.eject(blocker);
    };
  }, [queryClient]);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <Harness />
      </ToastProvider>
    </QueryClientProvider>
  );
}
