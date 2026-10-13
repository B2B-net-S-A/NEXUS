"use client";

// Publiczny harness generatora CV v3 — okno generatora z panelu osoby
// i profilu kandydata (od 13.10.2026 jedyne miejsce generacji). Stany z
// `?state=` renderowane z propsów komponentów prezentacyjnych, dane fikcyjne,
// ZERO zapytań: interceptor odcina sieć (pilnuje `harness-seeds.test.ts`).

import { Suspense, useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { AdvancedOptions } from "@/components/v2/cv-generator/AdvancedOptions";
import { CvGeneratorLayout, languageSummary } from "@/components/v2/cv-generator/CvGenerator";
import { CvResultView } from "@/components/v2/cv-generator/CvResult";
import { ClientRulesCard, GenerateBar } from "@/components/v2/cv-generator/GenerateBar";
import { StepCard } from "@/components/v2/cv-generator/GeneratorParts";
import { LanguageChoice } from "@/components/v2/cv-generator/LanguageChoice";
import { PersonStep } from "@/components/v2/cv-generator/PersonStep";
import { ProcessStep } from "@/components/v2/cv-generator/ProcessStep";
import { ProcessingTiles } from "@/components/v2/cv-generator/ProcessingTiles";
import { ProcessSources } from "@/components/v2/cv-generator/SourcesPanel";
import {
  NO_RECRUITMENT_MISSING,
  type CvLanguageChoice,
  type CvProcessingMode,
  type LanguagePolicy,
} from "@/components/v2/cv-generator/cv-generator-form";
import type { CvCandidateOption } from "@/components/v2/cv-generator/useCvGenerator";
import { CvToClientCard } from "@/components/v2/recruitment/CvToClientCard";
import { api, type GeneratedCvItem } from "@/lib/api";
import {
  cvToClientRowsQueryKey,
  stageBrandedQueryKey,
  stageCvSourcesQueryKey,
  type StageGeneratedCvRow,
} from "@/lib/cv-to-client";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { BACKGROUND_EVENTS_STEP, jobBackgroundEventsQueryKey } from "@/lib/job-background-events";
import type { RecruitmentOption } from "@/lib/cv-generator";

const noop = () => undefined;
const HINT = "Ok. 40 s. Gotowe CV trafi do procesu jako „CV do klienta”.";

const STATES = [
  ["process", "Proces z Championem (Bank Kappa)"],
  ["missing-sources", "Proces bez Championa"],
  ["no-recruitment", "Osoba bez rekrutacji"],
  ["result", "Wynik"],
  ["card", "Rekrutacja — CV do klienta"],
] as const;
type HarnessState = (typeof STATES)[number][0];

function recruitment(partial: Partial<RecruitmentOption> & Pick<RecruitmentOption, "stage_id" | "job_id" | "job_title" | "stage">): RecruitmentOption {
  return {
    has_champion: true,
    has_notes: true,
    has_cv: true,
    notes_chars: 1240,
    ready: true,
    required_champion: false,
    required_notes_min_chars: 0,
    missing_inputs: [],
    ...partial,
  };
}

const KAPPA = recruitment({ stage_id: 11, job_id: 501, job_title: "Senior Java Developer", stage: "verified", client_id: 7, client_name: "Bank Kappa" });
const POLNOCNY = recruitment({ stage_id: 12, job_id: 502, job_title: "Java Tech Lead", stage: "cv_sent", client_id: 8, client_name: "Bank Północny" });
const BANK_SIGMA = recruitment({
  stage_id: 21, job_id: 601, job_title: "Java Developer", stage: "new", client_id: 9, client_name: "Bank Sigma",
  has_champion: false, has_notes: false, notes_chars: 0,
});

const SOURCES_JAN = [
  { id: 1, filename: "Jan_Kowalski_CV_2026.pdf", is_primary: true, uploaded_at: "2026-09-12T09:00:00Z" },
  { id: 2, filename: "Jan_Kowalski_CV_EN.docx", is_primary: false, uploaded_at: "2025-03-04T09:00:00Z" },
];
const SOURCES_MARTA = [{ id: 3, filename: "Marta_Zielinska_CV.pdf", is_primary: false, uploaded_at: "2026-09-19T09:00:00Z" }];

function cvItem(partial: Partial<GeneratedCvItem> & Pick<GeneratedCvItem, "id" | "candidate_name">): GeneratedCvItem {
  return {
    language: "pl",
    blind: false,
    mode: "new",
    content_mode: "tailored",
    filename: `CV_${partial.id}.docx`,
    status: "ready",
    warnings: [],
    can_download: true,
    can_delete: true,
    created_at: "2026-09-23T12:40:00+02:00",
    ...partial,
  };
}

const RESULT_WARNINGS = [
  "BRAK POKRYCIA (kontrola AI): Doświadczenie — „bankowość” (branża przy stanowisku w Allegro nie wynika z CV źródłowego)",
  "MUST-HAVE: Kafka",
  "MUST-HAVE: Kubernetes",
  "WERYFIKUJ: nakładające się okresy zatrudnienia: 'Allegro' (01.2020 – 12.2022) i 'Freelance' (06.2021 – 03.2023)",
  "WERYFIKUJ: nakładające się okresy zatrudnienia: 'Freelance' (06.2021 – 03.2023) i 'Bank Iota' (01.2023 – obecnie)",
  "WERYFIKUJ: domknięto politykę prezentacji klienta w kodzie: skrócono 3 punktów obowiązków do 160 znaków.",
  "NICE-TO-HAVE: Terraform",
];

const RESULT_DOCS: GeneratedCvItem[] = [
  cvItem({ id: 900, candidate_name: "Jan Kowalski", candidate_id: 1, job_id: 501, client_name: "Bank Kappa", position: "Senior Java Developer", language: "en", filename: "CV_Kowalski_ZOB-2026-114_EN.docx", warnings: RESULT_WARNINGS, consent_required: true, consent_missing: true }),
  cvItem({ id: 901, package_id: 900, candidate_name: "Jan Kowalski", candidate_id: 1, job_id: 501, client_name: "Bank Kappa", position: "Senior Java Developer", language: "pl", filename: "CV_Kowalski_ZOB-2026-114_PL.docx", warnings: RESULT_WARNINGS, consent_required: true, consent_missing: true }),
];

const KAPPA_POLICY: LanguagePolicy = { forced: null, requiresBoth: false };
const PLAIN_POLICY: LanguagePolicy = { forced: null, requiresBoth: false };

function Content({ mode, hasChampion, language, policy, clientName, advancedOpen = false, projectRefFromJob = null, position }: {
  mode: CvProcessingMode; hasChampion: boolean; language: CvLanguageChoice; policy: LanguagePolicy;
  clientName: string | null; advancedOpen?: boolean; projectRefFromJob?: string | null; position: string;
}) {
  return (
    <StepCard step={3} title="Treść CV">
      <div className="space-y-5">
        <ProcessingTiles value={mode} onChange={noop} hasChampion={hasChampion} />
        <LanguageChoice value={language} onChange={noop} policy={policy} clientName={clientName} />
      </div>
      <AdvancedOptions
        open={advancedOpen} onOpenChange={noop} blind={false} onBlindChange={noop}
        position={position} onPositionChange={noop} positionRequired={false} positionFromJob={!!position}
        projectRef={projectRefFromJob ?? ""} onProjectRefChange={noop}
        projectRefVisible={!!projectRefFromJob || advancedOpen} projectRefRequired={false} projectRefFromJob={projectRefFromJob}
      />
    </StepCard>
  );
}

function Rules(props: Partial<Parameters<typeof ClientRulesCard>[0]>) {
  return (
    <ClientRulesCard
      clientName={null} clientSource={null} loading={false} error={false} languageLabel="PL"
      filename={null} projectRef={null} projectRefFromJob={false} consentRequired={false} consentAttached={false}
      {...props}
    />
  );
}

function ProcessSourcesFixture(props: Partial<Parameters<typeof ProcessSources>[0]>) {
  return (
    <ProcessSources
      jobId={501} hasChampion championOverride={null} championBusy={false} championMessage={null}
      onChampionFile={noop} onChampionError={noop} hasNotes notesChars={1240} noteDraft="" onNoteDraftChange={noop}
      sources={SOURCES_JAN} sourcesLoading={false} sourcesError={false} cvDocumentId={1} onSourceChange={noop}
      {...props}
    />
  );
}

const JAN = { id: 1, name: "Jan", lastname: "Kowalski", full_name: "Jan Kowalski" };
const MARTA = { id: 2, name: "Marta", lastname: "Zielińska", full_name: "Marta Zielińska" };
const TOMASZ = { id: 5, name: "Tomasz", lastname: "Dąbrowski", full_name: "Tomasz Dąbrowski" };

function renderState(state: HarnessState): ReactNode {
  const person = (candidate: CvCandidateOption) => <PersonStep candidate={candidate} />;
  switch (state) {
    case "process":
      return (
        <CvGeneratorLayout
          main={<>
            {person(JAN)}
            <ProcessStep recruitments={[KAPPA, POLNOCNY]} loading={false} error={false} value="11" onChange={noop}>
              <ProcessSourcesFixture />
            </ProcessStep>
            <Content mode="tailored" hasChampion language="en" policy={KAPPA_POLICY} clientName="Bank Kappa" position="Senior Java Developer" />
          </>}
          aside={<>
            <Rules clientName="Bank Kappa" clientSource="process" languageLabel={languageSummary("en", KAPPA_POLICY)}
              filename="CV_Kowalski_ZOB-2026-114_EN.docx" projectRef="ZOB/2026/114" projectRefFromJob
              consentRequired consentSlot={<Button type="button" variant="outline" size="sm">Wgraj zrzut maila</Button>} />
            <GenerateBar missing={[]} pending={false} onGenerate={noop}
              hint={HINT} />
          </>}
        />
      );
    case "missing-sources":
      return (
        <CvGeneratorLayout
          main={<>
            {person(MARTA)}
            <ProcessStep recruitments={[BANK_SIGMA]} loading={false} error={false} value="21" onChange={noop}>
              <ProcessSourcesFixture jobId={601} hasChampion={false} hasNotes={false} notesChars={0} sources={SOURCES_MARTA} cvDocumentId={3} />
            </ProcessStep>
            <Content mode="polished" hasChampion={false} language="pl" policy={PLAIN_POLICY} clientName="Bank Sigma" advancedOpen position="Java Developer" />
          </>}
          aside={<>
            <Rules clientName="Bank Sigma" clientSource="process" languageLabel="PL" filename="Zielinska_Java_Developer.docx" />
            <GenerateBar missing={[]} pending={false} onGenerate={noop}
              hint={`${HINT} Champion i notatki nie są wymagane. Bez nich powstanie Redakcja.`} />
          </>}
        />
      );
    case "no-recruitment":
      return (
        <CvGeneratorLayout
          main={<>
            {person(TOMASZ)}
            <ProcessStep recruitments={[]} loading={false} error={false} value="" onChange={noop} />
          </>}
          aside={<>
            <Rules />
            <GenerateBar missing={[NO_RECRUITMENT_MISSING]} pending={false} onGenerate={noop} hint={HINT} />
          </>}
        />
      );
    case "result":
      return (
        <CvResultView
          mainId={900} documents={RESULT_DOCS} attachedStage="verified" jobHref="#" canWrite
          onPreview={noop} onEdit={noop} onDownload={noop} onRegenerate={noop} onNew={noop}
        />
      );
    case "card":
      return (
        <div className="grid gap-4 md:grid-cols-3">
          {CARD_PEOPLE.map((person) => (
            <section key={person.stageId} className="space-y-2">
              <h2 className="text-sm font-semibold text-foreground">{person.label}</h2>
              <div className="rounded-lg border border-border bg-card p-4">
                <CvToClientCard
                  stageId={person.stageId} candidateId={person.candidateId} candidateName={person.name}
                  jobId={CARD_JOB_ID} jobTitle="Senior Java Developer" readOnly={false}
                />
              </div>
            </section>
          ))}
        </div>
      );
    default:
      return null;
  }
}

// Karta „CV do klienta” z panelu osoby w rekrutacji — stany z makiet:
// gotowe (auto-CV), brak CV i gotowe bez zgody RODO, a od 12.10.2026 także
// „Użyj innego CV”: podpowiedź gotowego CV (auto-CV obok CV z innej
// rekrutacji, brak CV obok pliku Word), kopia z pliku bez zgody i CV
// przeniesione przy przepięciu. Zasiew tymi samymi funkcjami kluczy co karta.
const CARD_JOB_ID = 77;
const CARD_PEOPLE = [
  { stageId: 501, candidateId: 11, name: "Jan Kowalski", label: "Auto-CV, a osoba ma gotowe CV", variant: "ready" },
  { stageId: 502, candidateId: 12, name: "Piotr Wiśniewski", label: "Brak CV, plik Word w profilu", variant: "none" },
  { stageId: 503, candidateId: 13, name: "Marta Zielińska", label: "Gotowe, brak zgody RODO", variant: "consent" },
  { stageId: 504, candidateId: 14, name: "Anna Przykładowa", label: "Z pliku Word, zgoda do dołączenia", variant: "copy" },
  { stageId: 505, candidateId: 15, name: "Tomasz Wzorcowy", label: "Przeniesione przy przepięciu", variant: "carried" },
] as const;

/** Gotowe CV osoby spoza tej rekrutacji — źródła okna „Użyj innego CV”. */
function seedReadyCvSources(qc: QueryClient, person: (typeof CARD_PEOPLE)[number]) {
  const hasOtherJobCv = person.variant === "ready" || person.variant === "carried";
  qc.setQueryData(
    stageCvSourcesQueryKey(person.stageId),
    hasOtherJobCv
      ? [
          {
            job_id: 9000,
            stage_id: 590,
            job_title: "Java Developer",
            reference_number: "REQ-9000",
            client_name: "Bank Kappa",
            status: "finalized",
            version: 2,
            language: "pl",
            updated_at: "2026-10-02T09:00:00Z",
            updated_by_name: "Ewa Rekruterska",
            consent_carried: false,
          },
        ]
      : [],
  );
  qc.setQueryData(
    candidateQueryKeys.cvDocuments(person.candidateId),
    person.variant === "ready"
      ? []
      : [
          {
            id: 700 + person.candidateId,
            filename: `${person.name.replace(" ", "_")}_B2B_Java.docx`,
            content_type: null,
            size_bytes: 48_000,
            document_kind: "cv",
            is_primary: false,
            uploaded_at: "2026-09-28T10:00:00Z",
            external_source: null,
            created_at: "2026-09-28T10:00:00Z",
            uploaded_by_name: "Ewa Rekruterska",
          },
        ],
  );
  qc.setQueryData(["candidate-generated-cvs", person.candidateId], []);
  qc.setQueryData(["central-cv-policy", null, person.stageId, false], {
    effective_policy: { requires_rodo_consent_block: person.variant === "copy" },
  });
  // Podgląd CV z innej rekrutacji w oknie wyboru.
  qc.setQueryData(stageBrandedQueryKey(590), {
    status: "finalized",
    from_generator: true,
    generated_document_id: null,
    edit_revision: 4,
    version: 2,
    candidate_stage_id: 590,
    content_html:
      "<h1>Java Developer – kandydat</h1><h2>Podsumowanie</h2><p>Wersja po poprawkach rekrutera: 8 lat w bankowości, ostatnio migracja usług do chmury.</p>",
    template: "standard",
    language: "pl",
    updated_at: "2026-10-02T09:00:00Z",
    updated_by: null,
    updated_by_name: null,
    finalized_at: "2026-10-02T09:00:00Z",
    finalized_by: null,
    finalized_by_name: null,
    snapshot_filename: null,
    rendered_from_default: false,
  });
}

function seedCardStates(qc: QueryClient) {
  for (const person of CARD_PEOPLE) {
    const generatedId = 9000 + person.stageId;
    seedReadyCvSources(qc, person);
    // CV wybrane zamiast generacji nie ma wiersza generatora.
    const detached = person.variant === "copy" || person.variant === "carried";
    const rows: StageGeneratedCvRow[] =
      person.variant === "none" || detached
        ? []
        : [
            {
              id: generatedId,
              status: "ready",
              origin: person.variant === "ready" ? "auto" : "manual",
              needs_review: person.variant === "ready",
              content_mode: "tailored",
              language: "pl",
              created_at: "2026-09-23T12:40:00Z",
              consent_required: person.variant === "consent",
              consent_missing: person.variant === "consent",
              factual_review: { status: "advisory", findings: person.variant === "ready" ? 2 : 0 },
            },
          ];
    qc.setQueryData(cvToClientRowsQueryKey(person.candidateId, CARD_JOB_ID), rows);
    qc.setQueryData(stageBrandedQueryKey(person.stageId), {
      status: person.variant === "none" ? "none" : "draft",
      from_generator: person.variant !== "none" && person.variant !== "copy",
      generated_document_id: person.variant === "none" || detached ? null : generatedId,
      source: person.variant === "copy" ? "document" : person.variant === "none" ? null : "generator",
      origin:
        person.variant === "copy"
          ? { kind: "upload", label: "Anna_Przykladowa_B2B_Java.docx", selected_at: "2026-10-12T10:00:00Z" }
          : person.variant === "carried"
            ? { kind: "reassign", label: "REQ-9000", job_id: 9000, selected_at: "2026-10-12T10:00:00Z" }
            : null,
      consent_required: person.variant === "copy",
      consent_attached: false,
      consent_missing: person.variant === "copy",
      edit_revision: 1,
      version: 1,
      candidate_stage_id: person.stageId,
      content_html:
        person.variant === "none" ? null : "<h2>Podsumowanie</h2><p>Java Developer z 8-letnim doświadczeniem w bankowości.</p>",
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
    });
    qc.setQueryData(["cv-original", person.stageId], {
      candidate_stage_id: person.stageId,
      candidate_id: person.candidateId,
      job_id: CARD_JOB_ID,
      has_snapshot: true,
      original_cv_filename: `${person.name.split(" ")[1]}_CV.pdf`,
      original_cv_language: "pl",
      original_snapshot_at: "2026-09-12T10:00:00Z",
      original_snapshot_source: "profile",
      download_url: null,
    });
  }
  qc.setQueryData(jobBackgroundEventsQueryKey(CARD_JOB_ID, BACKGROUND_EVENTS_STEP), {
    job_id: CARD_JOB_ID,
    items: [],
    limit: BACKGROUND_EVENTS_STEP,
  });
}

function Harness() {
  const params = useSearchParams();
  const raw = params.get("state");
  const state: HarnessState = STATES.some(([key]) => key === raw) ? (raw as HarnessState) : "process";
  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6">
      <nav aria-label="Stany harnessu" className="flex flex-wrap gap-2 text-xs">
        {STATES.map(([key, label]) => (
          <a
            key={key}
            href={`?state=${key}`}
            aria-current={key === state ? "page" : undefined}
            className={key === state ? "rounded-full bg-primary px-3 py-1 text-primary-foreground" : "rounded-full border border-border px-3 py-1 text-muted-foreground hover:bg-muted"}
          >
            {label}
          </a>
        ))}
      </nav>
      <header>
        <h1 className="text-2xl font-bold text-foreground">Generator CV</h1>
        <p className="text-sm text-muted-foreground">
          Okno generatora z panelu osoby i profilu kandydata. Osoba z góry, klient z procesu.
        </p>
      </header>
      {renderState(state)}
    </main>
  );
}

export default function CvGeneratorPreviewPage() {
  const [ready, setReady] = useState(false);
  const [queryClient] = useState(() => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    seedCardStates(qc);
    return qc;
  });

  useEffect(() => {
    const blocker = api.interceptors.request.use((config) =>
      Promise.reject(new AxiosError("preview: sieć wyłączona", "ECONNABORTED", config)),
    );
    setReady(true);
    return () => api.interceptors.request.eject(blocker);
  }, []);

  if (!ready) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>}>
          <Harness />
        </Suspense>
      </ToastProvider>
    </QueryClientProvider>
  );
}
