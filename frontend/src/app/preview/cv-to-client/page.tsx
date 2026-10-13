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
//  - QC nie odpowiada (klucz QC celowo niezasiany — karta nie udaje zera).

import { useEffect, useState } from "react";
import { AxiosError } from "axios";
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
const CLIENT_ID = 7;
const REVISION = 2;
const FRESH = { updatedAt: Date.now() + 86_400_000 };

type Variant = "sources" | "regenerate" | "counter" | "clean" | "qcdown";

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
];

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

function seed(qc: QueryClient) {
  for (const person of PEOPLE) {
    const hasCv = person.variant !== "sources";
    const generatedId = 9000 + person.stageId;
    // Karta: CV etapu, generacje pary, oryginał, „Praca w tle”.
    const rows: StageGeneratedCvRow[] = hasCv
      ? [{ id: generatedId, status: "ready", origin: "manual", content_mode: "tailored", language: "pl", created_at: "2026-10-13T09:40:00Z" }]
      : [];
    qc.setQueryData(cvToClientRowsQueryKey(person.candidateId, JOB_ID), rows, FRESH);
    qc.setQueryData(
      stageBrandedQueryKey(person.stageId),
      {
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
      },
      FRESH,
    );
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
    if (hasCv && person.variant !== "qcdown") {
      qc.setQueryData(
        cvToClientQcQueryKey(person.stageId, REVISION),
        { stage_id: person.stageId, cv: { stage_id: person.stageId }, checks: qcChecks(person) },
        FRESH,
      );
    }
    if (hasCv) qc.setQueryData(cvToClientIssuesQueryKey(person.stageId, REVISION), issues(person), FRESH);
  }
  qc.setQueryData(
    jobBackgroundEventsQueryKey(JOB_ID, BACKGROUND_EVENTS_STEP),
    { job_id: JOB_ID, items: [], limit: BACKGROUND_EVENTS_STEP },
    FRESH,
  );
}

function Harness() {
  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold text-foreground">CV do klienta — w procesie</h1>
        <p className="text-sm text-muted-foreground">
          Karta z panelu osoby: „Generuj CV” rozwija „Z czego powstało” w karcie (bez okna generatora), a gotowe CV
          ma jedną liczbę rzeczy do sprawdzenia przed wysłaniem.
        </p>
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
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
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
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <Harness />
      </ToastProvider>
    </QueryClientProvider>
  );
}
