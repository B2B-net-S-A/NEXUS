"use client";

// Publiczny harness edytora CV (Edytor CV 2, 12.10.2026). Dane fikcyjne, ZERO
// zapytań: stan, zapis i zatwierdzenie CV idą przez `editorApi` z pamięci,
// pliki Word przez `editorFiles` (statyczny plik z `/preview/cv-search/`),
// panel źródeł czyta klucze zasiane w cache tymi samymi funkcjami co
// komponenty, a interceptor odcina sieć (pilnuje `harness-seeds.test.ts`).
//
// `?state=` — `draft` (domyślnie), `finalized` (zatwierdzona wersja: pierwsza
// zmiana zakłada szkic), `conflict` (szkic łamie regułę klienta), `nosources`
// (wynik generatora bez rekrutacji — panel źródeł mówi, czemu jest pusty,
// a „Do poprawy” ma same uwagi generatora), `clean` (CV bez uwag), `qcdown`
// (QC nie odpowiada — panel nie udaje, że uwag nie ma), `aidown` (asystent
// niedostępny — edytor działa dalej).
//
// Asystent (Edytor CV 3, PR 4) dostaje odpowiedzi z `command-fixture.ts`:
// „dopisz terraform” pyta o źródło, „pogrub …” pogrubia, „stanowisko: X”
// zmienia „Rozważany na stanowisko”, „Skróć do 2 stron” usuwa i łączy.
//
// Panel „Do poprawy” dostaje QC, uwagi i poprawki z `issues-fixture.ts`:
// lista liczy się z ostatnio zapisanej treści, więc widać cały obieg
// poprawka → autozapis → świeża lista.
//
// „Historia” dostaje dwie zatwierdzone wersje i treść „z pliku Word”
// z `history-fixture.ts` (dowolny plik .docx; `uszkodzony.docx` pokazuje błąd).
//
// `handoff` / `handoff-blocking` (14.10.2026, D6): karta stoi na
// „Zweryfikowany”, więc stopka ma „Uwaga dla Delivery Leada” i „Zapisz
// i przekaż do DL →”. Ruch karty jest w pamięci (pół sekundy, potem „przeszło”)
// i strona pisze, z jaką uwagą. `handoff-blocking` ma blokady QC — przycisk to
// „Przekaż mimo uwag…”, które otwiera okno obejścia QC; jego zapis idzie przez
// API, więc w harnessie kończy się komunikatem o wyłączonej sieci.

import { useEffect, useMemo, useState } from "react";
import { AxiosError, type AxiosResponse } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import type { CandidateDocument } from "@/components/v2/files/FilePreviewModal";
import { jobNotesQueryKey, type JobNoteItem } from "@/components/v2/jobs/workbench-chrome";
import {
  CVBrandedEditModal,
  type CvEditorApi,
  type CvEditorFiles,
} from "@/components/v2/modals/CVBrandedEditModal";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import {
  api,
  type ChampionProfileResponse,
  type CVBrandedFinalizeResponseT,
  type CVBrandedState,
  type CVOriginalSnapshot,
} from "@/lib/api";
import { plainBriefQueryKey, type PlainBrief } from "@/lib/api/plainKnowledge";
import { stageBrandedQueryKey } from "@/lib/cv-to-client";
import { useAuthStore } from "@/store/auth";

import { memoryCommandApi } from "./command-fixture";
import { memoryHistoryApi } from "./history-fixture";
import { GENERATOR_ONLY_WARNINGS, memoryIssuesApi, withoutBlocking, withoutIssues } from "./issues-fixture";

const JOB_ID = 201;
const CANDIDATE_ID = 101;
const STAGE_ID = 901;
const GENERATED_ID = 77;
const DAY_MS = 86_400_000;
const SEED_FRESH = { updatedAt: Date.now() + DAY_MS };

type HarnessState =
  | "draft"
  | "finalized"
  | "conflict"
  | "nosources"
  | "clean"
  | "qcdown"
  | "aidown"
  | "handoff"
  | "handoff-blocking";
const STATES: Record<HarnessState, string> = {
  draft: "Szkic",
  finalized: "Zatwierdzona wersja",
  conflict: "Szkic łamie regułę klienta",
  nosources: "Wynik generatora bez rekrutacji",
  clean: "Bez uwag",
  qcdown: "QC niedostępne",
  aidown: "AI niedostępne",
  handoff: "Przekazanie do DL",
  "handoff-blocking": "Przekazanie mimo uwag",
};
const HANDOFF_STATES: ReadonlySet<HarnessState> = new Set(["handoff", "handoff-blocking"]);

const RODO =
  "Wyrażam zgodę na przetwarzanie moich danych osobowych zawartych w przekazanych przeze mnie " +
  "dokumentach przez Firmę Przykładową S.A. w celach związanych z moim udziałem w niniejszym " +
  "procesie rekrutacyjnym.";

// Kształt CV z generatora po zapisie w edytorze: bez klas, ze znacznikami sekcji.
const CV_HTML =
  "<h1>Senior Java Developer – Anna Przykładowa</h1>" +
  "<p><strong>Rozważany na stanowisko:</strong> Senior Java Developer — płatności kartowe</p><hr>" +
  '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>' +
  "<ul><li><p>Ponad 7 lat doświadczenia w <strong>Javie</strong>, w tym 3 lata w bankowości.</p></li>" +
  "<li><p>Projektowała mikroserwisy płatności w <strong>Spring Boot</strong>.</p></li></ul>" +
  '<h2 data-cv-section="education">EDUKACJA</h2>' +
  "<p>2012 – 2017 <strong>Politechnika Przykładowa</strong> — Informatyka, mgr inż.</p>" +
  '<h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2>' +
  "<p><strong>Języki programowania: </strong>Java 17, Kotlin, SQL</p>" +
  "<p><strong>Narzędzia: </strong>Docker, Jenkins, Github</p>" +
  '<h2 data-cv-section="languages">JĘZYKI</h2><p>polski – ojczysty · angielski – B2</p>' +
  '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>' +
  '<p data-cv-section="role"><strong>Senior Java Developer</strong> 03.2021 – 06.2024</p>' +
  '<p data-cv-section="employer">Bank Przykładowy S.A. · Bankowość</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Rozwój mikroserwisów płatności w <strong>Java 17</strong> i <strong>Spring Boot</strong>.</p></li>" +
  "<li><p>Optymalizacja zapytań w PostgreSQL.</p></li>" +
  "<li><p>Przeglądy kodu i wdrażanie młodszych programistów.</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java 17, Spring Boot, PostgreSQL, Docker, Jenkins</p>' +
  '<p data-cv-section="role"><strong>Java Developer</strong> 01.2017 – 02.2021</p>' +
  '<p data-cv-section="employer">Software House Przykład sp. z o.o. · IT</p>' +
  '<p data-cv-section="duties_label">Zakres zadań:</p>' +
  "<ul><li><p>Tworzenie usług REST w Javie 11 i <strong>Spring Boot</strong>.</p></li>" +
  "<li><p>Integracje z systemami zewnętrznymi przez kolejki komunikatów.</p></li>" +
  "<li><p>Testy jednostkowe i integracyjne (JUnit, Testcontainers).</p></li></ul>" +
  '<p data-cv-section="technologies">Technologie: Java 11, Spring Boot, JUnit, Jenkins</p>' +
  `<p data-cv-section="rodo" style="font-size: 8pt; line-height: 1.35">${RODO}</p>`;

function brandedState(state: HarnessState): CVBrandedState {
  const finalized = state === "finalized";
  return {
    presentation_review:
      state === "conflict"
        ? { status: "conflict", message: "Przekroczono limit punktów obowiązków klienta." }
        : { status: "checked", checked_fields: ["max_bullets_per_role"], manual_fields: [] },
    docx_available: finalized,
    docx_filename: "CV_Anna_P_Bank_Przykladowy.docx",
    generated_document_id: GENERATED_ID,
    from_generator: true,
    source: "generator",
    edit_revision: 4,
    version: finalized ? 2 : 3,
    candidate_stage_id: state === "nosources" ? null : STAGE_ID,
    status: finalized ? "finalized" : "draft",
    content_html:
      state === "clean" ? withoutIssues(CV_HTML) : state === "handoff" ? withoutBlocking(CV_HTML) : CV_HTML,
    template: "standard",
    language: "pl",
    updated_at: "2026-10-12T12:32:00Z",
    updated_by: 31,
    updated_by_name: "Marta Testowa",
    finalized_at: finalized ? "2026-10-10T09:00:00Z" : null,
    finalized_by: finalized ? 31 : null,
    finalized_by_name: finalized ? "Marta Testowa" : null,
    snapshot_filename: finalized ? "cv-v2.html" : null,
    rendered_from_default: false,
  };
}

function respond<T>(data: T): Promise<AxiosResponse<T>> {
  return Promise.resolve({ data } as AxiosResponse<T>);
}

/** Edytor na stanie z pamięci: zapis podbija wersję roboczą, nic nie idzie do API. */
function memoryApi(initial: CVBrandedState): { api: CvEditorApi; savedHtml: () => string } {
  let current = initial;
  const api: CvEditorApi = {
    get: () => respond(current),
    update: (_id, payload) => {
      if ("content_html" in payload) {
        current = { ...current, content_html: payload.content_html, edit_revision: current.edit_revision + 1 };
      }
      return respond(current);
    },
    newDraft: () => {
      current = {
        ...current,
        status: "draft",
        docx_available: false,
        version: current.version + 1,
        edit_revision: current.edit_revision + 1,
      };
      return respond(current);
    },
    finalize: (_id, payload) => {
      current = {
        ...current,
        status: "finalized",
        docx_available: true,
        content_html: payload.content_html,
        edit_revision: current.edit_revision + 1,
      };
      return respond<CVBrandedFinalizeResponseT>({
        edit_revision: current.edit_revision,
        version: current.version,
        document_version_id: 1,
        candidate_stage_id: current.candidate_stage_id,
        status: "finalized",
        snapshot_filename: "cv.html",
        snapshot_size_bytes: 1,
        content_review_status: "verified",
        content_review_findings: 0,
      });
    },
  };
  return { api, savedHtml: () => current.content_html ?? "" };
}

async function staticFile(path: string): Promise<Blob> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.blob();
}

// To samo fikcyjne CV w szablonie firmowym (Montserrat, wyjustowana treść)
// i jego strony PDF („Jak u klienta”; na serwerze z LibreOffice).
const WORD_FILE = "/preview/cv-to-client/cv-firmowe-przyklad.docx";
const PAGES_FILE = "/preview/cv-to-client/cv-firmowe-przyklad.pdf";
const PDF_FILE = "/preview/cv-search/cv-tekst.pdf";

// Statyczny plik zamiast renderu z treści: w harnessie nie ma serwera, który
// złożyłby Word. Układ podglądu i przełącznik widać, treść jest przykładowa.
const MEMORY_FILES: CvEditorFiles = {
  draftDocx: async () => ({ blob: await staticFile(WORD_FILE), filename: "SZKIC_CV_przyklad.docx" }),
  downloadApproved: async () => undefined,
  previewApproved: () => staticFile(WORD_FILE),
  draftPdf: async () => ({ blob: await staticFile(PAGES_FILE), filename: "SZKIC_CV_przyklad.pdf" }),
  approvedPdf: async () => ({ blob: await staticFile(PAGES_FILE), filename: "CV_przyklad.pdf" }),
  print: async () => undefined,
};

const SOURCE_LOADERS = {
  loadDocumentBlob: () => staticFile(PDF_FILE),
  loadOriginalBlob: () => staticFile(PDF_FILE),
};

const SNAPSHOT: CVOriginalSnapshot = {
  candidate_stage_id: STAGE_ID,
  candidate_id: CANDIDATE_ID,
  job_id: JOB_ID,
  has_snapshot: true,
  original_cv_filename: "Anna Przykładowa — CV.pdf",
  original_cv_language: "pl",
  original_snapshot_at: "2026-10-05T08:00:00Z",
  original_snapshot_source: "application",
  download_url: null,
};

const DOCUMENTS: CandidateDocument[] = [
  {
    id: 1,
    filename: "Anna Przykładowa — CV.pdf",
    content_type: "application/pdf",
    size_bytes: null,
    document_kind: "cv",
    is_primary: true,
    uploaded_at: "2026-09-01T08:00:00Z",
    external_source: null,
    created_at: "2026-09-01T08:00:00Z",
  },
];

const PROFILE: ChampionProfileResponse = {
  job_id: JOB_ID,
  job_title: "Senior Java Developer — płatności kartowe",
  champion_profile: {
    basics: { role_name: "Senior Java Developer", rate_value: 150, work_mode: "hybrydowo" },
    stack: {
      must: [{ name: "Java 17" }, { name: "Spring Boot" }, { name: "Kafka" }, { name: "PostgreSQL" }],
      nice: [{ name: "Kubernetes" }],
      notes: "",
    },
    screening_questions: [],
  } as never,
  critical_resolution: {
    stored: ["Kafka"],
    decided: true,
    effective: ["Kafka"],
    source: "dl",
    suggested: ["Kafka"],
  } as never,
};

const BRIEF: PlainBrief = {
  job_id: JOB_ID,
  status: "ready",
  stale: false,
  is_open: true,
  can_refresh: false,
  can_change_role: false,
  generated_at: new Date(Date.now() - DAY_MS).toISOString(),
  message: null,
  one_liner:
    "Szukamy programisty Javy, który rozwija system płatności kartą w Banku Przykładowym.",
  example: "Gdy płacisz kartą w sklepie, terminal pyta bank, czy masz środki. Ta osoba pisze program, który odpowiada.",
  day_to_day: ["Dopisuje nowe funkcje do systemu płatności.", "Poprawia błędy zgłoszone przez wsparcie."],
  pitch: "Stabilny projekt na lata, dwa dni w biurze w tygodniu.",
  candidate_qa: [],
  screening_plain: [],
  glossary: [
    {
      term_key: "kafka",
      display_name: "Kafka",
      level: "must",
      level_label: "wymagane",
      status: "ready",
      summary: "Kolejka zdarzeń: systemy wysyłają sobie komunikaty i nie czekają na odpowiedź.",
      does: null,
      cv_hints: [],
      confused_with: null,
      in_this_project: null,
      sources: [],
      origin: null,
    },
  ],
  role: null,
  client: { id: 1, name: "Bank Przykładowy", about: "Średni bank detaliczny.", origin: "manual", sources: [] },
};

const NOTES: JobNoteItem[] = [
  {
    id: 1,
    content: "Screening 02.10: Kafka w projekcie płatności przez około 3 lata. O chmurze nie rozmawialiśmy.",
    author_name: "Marta Testowa",
    created_at: "2026-10-02T10:00:00Z",
  },
  {
    id: 2,
    content: "Dostępna od listopada, praca zdalna z wizytami w biurze raz w miesiącu.",
    author_name: "Marta Testowa",
    created_at: "2026-10-06T09:00:00Z",
  },
];

function seededClient(state: HarnessState): QueryClient {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, refetchOnWindowFocus: false } },
  });
  qc.setQueryData(stageBrandedQueryKey(STAGE_ID), brandedState(state), SEED_FRESH);
  qc.setQueryData(["cv-generated-editor", GENERATED_ID], brandedState(state), SEED_FRESH);
  qc.setQueryData(["cv-original", STAGE_ID], SNAPSHOT, SEED_FRESH);
  qc.setQueryData(candidateQueryKeys.cvDocuments(CANDIDATE_ID), DOCUMENTS, SEED_FRESH);
  qc.setQueryData(["champion-profile", JOB_ID], PROFILE, SEED_FRESH);
  qc.setQueryData(plainBriefQueryKey(JOB_ID), BRIEF, SEED_FRESH);
  qc.setQueryData(jobNotesQueryKey(CANDIDATE_ID, JOB_ID), { items: NOTES }, SEED_FRESH);
  return qc;
}

function harnessState(value: string | null): HarnessState {
  return value && value in STATES ? (value as HarnessState) : "draft";
}

export default function CvEditorPreviewPage() {
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(true);
  const [state, setState] = useState<HarnessState>("draft");
  // Ruch karty z pamięci: co „przeszło” i z jaką uwagą — strona to wypisuje.
  const [handedOff, setHandedOff] = useState<string | null>(null);
  const queryClient = useMemo(() => seededClient(state), [state]);
  const backend = useMemo(() => {
    const initial = brandedState(state);
    const editor = memoryApi(initial);
    const variant = state === "qcdown" ? "down" : state === "clean" ? "clean" : "issues";
    return {
      editorApi: editor.api,
      issuesApi: memoryIssuesApi(editor.savedHtml, variant),
      commandApi: memoryCommandApi(state === "aidown"),
      historyApi: memoryHistoryApi(initial.content_html ?? ""),
      handoff: HANDOFF_STATES.has(state)
        ? {
            onSaveAndHandOff: async (remark: string) => {
              await new Promise((resolve) => setTimeout(resolve, 500));
              setHandedOff(remark);
              return true;
            },
          }
        : undefined,
    };
  }, [state]);

  useEffect(() => {
    setState(harnessState(new URLSearchParams(window.location.search).get("state")));
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    useAuthStore.setState({
      user: {
        id: 31,
        email: "preview@example.com",
        name: "Marta Testowa",
        role: "recruiter",
        roles: ["recruiter"],
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

  const target = state === "nosources" ? { generatedId: GENERATED_ID } : { stageId: STAGE_ID };
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <main className="mx-auto max-w-3xl space-y-3 px-4 py-6">
          <h1 className="text-lg font-semibold">Podgląd: edytor CV</h1>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
            {(Object.keys(STATES) as HarnessState[]).map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={state === key}
                onClick={() => {
                  setState(key);
                  setHandedOff(null);
                  setOpen(true);
                }}
                className={state === key ? "font-semibold text-primary" : "text-foreground"}
              >
                {STATES[key]}
              </button>
            ))}
            <Button type="button" size="sm" variant="outline" className="ml-auto" onClick={() => setOpen(true)}>
              Otwórz edytor
            </Button>
          </div>
          {handedOff !== null ? (
            <p role="status" data-testid="harness-handed-off" className="text-sm text-muted-foreground">
              Karta przeszła do „QC CV”{handedOff ? ` z uwagą: „${handedOff}”` : " bez uwagi"}.
            </p>
          ) : null}
        </main>
        <CVBrandedEditModal
          key={state}
          open={open}
          onOpenChange={setOpen}
          candidateName="Anna Przykładowa"
          jobTitle="Senior Java Developer"
          sourceContext={state === "nosources" ? null : undefined}
          editorApi={backend.editorApi}
          issuesApi={backend.issuesApi}
          commandApi={backend.commandApi}
          historyApi={backend.historyApi}
          handoff={backend.handoff}
          generatorWarnings={state === "nosources" ? GENERATOR_ONLY_WARNINGS : undefined}
          editorFiles={MEMORY_FILES}
          sourceLoaders={SOURCE_LOADERS}
          {...target}
        />
      </ToastProvider>
    </QueryClientProvider>
  );
}
