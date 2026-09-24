"use client";

// Publiczny harness generatora CV v3 (makiety „Generator CV — start od osoby”).
// Stany z `?state=` renderowane z propsów komponentów prezentacyjnych, dane
// fikcyjne, ZERO zapytań: lista klientów jest zasiana pod tym samym kluczem co
// w `ProcessStep`, a interceptor odcina sieć (pilnuje `harness-seeds.test.ts`).

import { Suspense, useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { AxiosError } from "axios";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { ClientSinglePicker } from "@/components/clients/ClientSinglePicker";
import { AdvancedOptions } from "@/components/v2/cv-generator/AdvancedOptions";
import { CvGeneratorLayout, languageSummary } from "@/components/v2/cv-generator/CvGenerator";
import { CvResultView } from "@/components/v2/cv-generator/CvResult";
import { ClientRulesCard, GenerateBar } from "@/components/v2/cv-generator/GenerateBar";
import { StepCard } from "@/components/v2/cv-generator/GeneratorParts";
import { LanguageChoice } from "@/components/v2/cv-generator/LanguageChoice";
import { MyCvListView } from "@/components/v2/cv-generator/MyCvList";
import { PersonStep } from "@/components/v2/cv-generator/PersonStep";
import { CV_GENERATOR_CLIENTS_QUERY_KEY, ProcessStep } from "@/components/v2/cv-generator/ProcessStep";
import { ProcessingTiles } from "@/components/v2/cv-generator/ProcessingTiles";
import { ProcessSources, UploadSources } from "@/components/v2/cv-generator/SourcesPanel";
import { UploadIdentityStep } from "@/components/v2/cv-generator/UploadIdentityStep";
import type { CvLanguageChoice, CvProcessingMode, LanguagePolicy } from "@/components/v2/cv-generator/cv-generator-form";
import type { CvCandidateOption } from "@/components/v2/cv-generator/useCvGenerator";
import { CvToClientCard } from "@/components/v2/recruitment/CvToClientCard";
import { api, type GeneratedCvItem } from "@/lib/api";
import {
  cvToClientRowsQueryKey,
  stageBrandedQueryKey,
  type StageGeneratedCvRow,
} from "@/lib/cv-to-client";
import { BACKGROUND_EVENTS_STEP, jobBackgroundEventsQueryKey } from "@/lib/job-background-events";
import type { RecruitmentOption } from "@/lib/cv-generator";

const NOW = new Date("2026-09-23T14:00:00+02:00");
const noop = () => undefined;

const STATES = [
  ["start", "Start"],
  ["process", "Proces z Championem (PKO BP)"],
  ["missing-sources", "Proces bez Championa"],
  ["no-process", "Inny klient (bez procesu)"],
  ["upload", "Osoba spoza bazy"],
  ["upload-client", "Spoza bazy — bez dodawania"],
  ["result", "Wynik"],
  ["my-cv", "Moje CV"],
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

const PKO = recruitment({ stage_id: 11, job_id: 501, job_title: "Senior Java Developer", stage: "verified", client_id: 7, client_name: "PKO BP" });
const NORDEA = recruitment({ stage_id: 12, job_id: 502, job_title: "Java Tech Lead", stage: "cv_sent", client_id: 8, client_name: "Nordea" });
const BANK_POCZTOWY = recruitment({
  stage_id: 21, job_id: 601, job_title: "Java Developer", stage: "new", client_id: 9, client_name: "Bank Pocztowy",
  has_champion: false, has_notes: false, notes_chars: 0,
});

const SOURCES_JAN = [
  { id: 1, filename: "Jan_Kowalski_CV_2026.pdf", is_primary: true, uploaded_at: "2026-09-12T09:00:00Z" },
  { id: 2, filename: "Jan_Kowalski_CV_EN.docx", is_primary: false, uploaded_at: "2025-03-04T09:00:00Z" },
];
const SOURCES_MARTA = [{ id: 3, filename: "Marta_Zielinska_CV.pdf", is_primary: false, uploaded_at: "2026-09-19T09:00:00Z" }];
const SOURCES_TOMASZ = [{ id: 4, filename: "Tomasz_Dabrowski_CV.pdf", is_primary: true, uploaded_at: "2026-08-02T09:00:00Z" }];

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
  "WERYFIKUJ: nakładające się okresy zatrudnienia: 'Freelance' (06.2021 – 03.2023) i 'mBank' (01.2023 – obecnie)",
  "WERYFIKUJ: domknięto politykę prezentacji klienta w kodzie: skrócono 3 punktów obowiązków do 160 znaków.",
  "NICE-TO-HAVE: Terraform",
];

const RESULT_DOCS: GeneratedCvItem[] = [
  cvItem({ id: 900, candidate_name: "Jan Kowalski", candidate_id: 1, job_id: 501, client_name: "PKO BP", position: "Senior Java Developer", language: "en", filename: "CV_Kowalski_ZOB-2026-114_EN.docx", warnings: RESULT_WARNINGS, consent_required: true, consent_missing: true }),
  cvItem({ id: 901, package_id: 900, candidate_name: "Jan Kowalski", candidate_id: 1, job_id: 501, client_name: "PKO BP", position: "Senior Java Developer", language: "pl", filename: "CV_Kowalski_ZOB-2026-114_PL.docx", warnings: RESULT_WARNINGS, consent_required: true, consent_missing: true }),
];

const MY_CV: GeneratedCvItem[] = [
  ...RESULT_DOCS,
  cvItem({ id: 880, candidate_name: "Marta Zielińska", candidate_id: 2, job_id: 601, client_name: "Bank Pocztowy", position: "Java Developer", content_mode: "polished", status: "processing", job_status: "running", created_at: "2026-09-23T12:52:00+02:00" }),
  cvItem({ id: 870, candidate_name: "Piotr Wiśniewski", candidate_id: 3, job_id: 502, client_name: "Nordea", position: "DevOps Engineer", language: "en", created_at: "2026-09-23T10:15:00+02:00" }),
  cvItem({ id: 860, candidate_name: "Katarzyna Lewandowska", candidate_id: 4, job_id: 503, client_name: "Alior Bank", position: "Analityk biznesowy", origin: "auto", needs_review: true, warnings: ["MUST-HAVE: BPMN"], created_at: "2026-09-22T16:02:00+02:00" }),
  cvItem({ id: 850, candidate_name: "Tomasz Dąbrowski", candidate_id: 5, job_id: null, client_name: "Polkomtel", content_mode: "polished", created_at: "2026-09-22T11:30:00+02:00" }),
  cvItem({ id: 840, candidate_name: "Agnieszka Mazur", candidate_id: 6, job_id: 504, client_name: "BIK", position: "Scrum Master", warnings: ["MUST-HAVE: SAFe", "MUST-HAVE: Jira Align", "BRAK POKRYCIA: liczba '12 zespołów' (BIK) nie występuje w CV ani notatkach — „prowadziła 12 zespołów”"], created_at: "2026-09-19T09:00:00+02:00" }),
  cvItem({ id: 830, candidate_name: "Paweł Wójcik", candidate_id: 7, job_id: 505, client_name: "Nordea", position: "Frontend Developer", language: "en", content_mode: "polished", status: "failed", job_status: "failed", error_message: "Model przerwał odpowiedź.", created_at: "2026-09-18T09:00:00+02:00" }),
];

const PKO_POLICY: LanguagePolicy = { forced: null, requiresBoth: false };
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
      variant="process" jobId={501} hasChampion championOverride={null} championBusy={false} championMessage={null}
      onChampionFile={noop} onChampionError={noop} hasNotes notesChars={1240} noteDraft="" onNoteDraftChange={noop}
      sources={SOURCES_JAN} sourcesLoading={false} sourcesError={false} cvDocumentId={1} onSourceChange={noop}
      {...props}
    />
  );
}

const JAN = { id: 1, name: "Jan", lastname: "Kowalski", full_name: "Jan Kowalski", position: "Senior Java Developer", email: "jan.kowalski@example.com" };
const MARTA = { id: 2, name: "Marta", lastname: "Zielińska", full_name: "Marta Zielińska", position: "Java Developer", email: null };
const TOMASZ = { id: 5, name: "Tomasz", lastname: "Dąbrowski", full_name: "Tomasz Dąbrowski", position: "DevOps Engineer", email: null };

function renderState(state: HarnessState): ReactNode {
  const person = (candidate: CvCandidateOption | null) => (
    <PersonStep
      candidate={candidate} query="" onQueryChange={noop} results={[]} searching={false}
      searchError={null} onChoose={noop} onStartUpload={noop}
    />
  );
  switch (state) {
    case "process":
      return (
        <CvGeneratorLayout
          main={<>
            {person(JAN)}
            <ProcessStep recruitments={[PKO, NORDEA]} loading={false} error={false} value="11" onChange={noop} otherClient={null} onOtherClientChange={noop}>
              <ProcessSourcesFixture />
            </ProcessStep>
            <Content mode="tailored" hasChampion language="en" policy={PKO_POLICY} clientName="PKO BP" position="Senior Java Developer" />
          </>}
          aside={<>
            <Rules clientName="PKO BP" clientSource="process" languageLabel={languageSummary("en", PKO_POLICY)}
              filename="CV_Kowalski_ZOB-2026-114_EN.docx" projectRef="ZOB/2026/114" projectRefFromJob
              consentRequired consentSlot={<Button type="button" variant="outline" size="sm">Wgraj zrzut maila</Button>} />
            <GenerateBar missing={[]} pending={false} onGenerate={noop}
              hint="Ok. 40 s. Gotowe CV trafi do procesu jako „CV do klienta” i na listę Moje CV." />
          </>}
        />
      );
    case "missing-sources":
      return (
        <CvGeneratorLayout
          main={<>
            {person(MARTA)}
            <ProcessStep recruitments={[BANK_POCZTOWY]} loading={false} error={false} value="21" onChange={noop} otherClient={null} onOtherClientChange={noop}>
              <ProcessSourcesFixture jobId={601} hasChampion={false} hasNotes={false} notesChars={0} sources={SOURCES_MARTA} cvDocumentId={3} />
            </ProcessStep>
            <Content mode="polished" hasChampion={false} language="pl" policy={PLAIN_POLICY} clientName="Bank Pocztowy" advancedOpen position="Java Developer" />
          </>}
          aside={<>
            <Rules clientName="Bank Pocztowy" clientSource="process" languageLabel="PL" filename="Zielinska_Java_Developer.docx" />
            <GenerateBar missing={[]} pending={false} onGenerate={noop}
              hint="Ok. 40 s. Gotowe CV trafi do procesu jako „CV do klienta” i na listę Moje CV. Champion i notatki nie są wymagane. Bez nich powstanie Redakcja." />
          </>}
        />
      );
    case "no-process":
      return (
        <CvGeneratorLayout
          main={<>
            {person(TOMASZ)}
            <ProcessStep recruitments={[]} loading={false} error={false} value="other" onChange={noop}
              otherClient={{ id: 15, name: "Polkomtel" }} onOtherClientChange={noop}>
              <ProcessSourcesFixture variant="no-process" jobId={null} hasChampion={false} hasNotes={false} notesChars={0} sources={SOURCES_TOMASZ} cvDocumentId={4} />
            </ProcessStep>
            <Content mode="polished" hasChampion={false} language="pl" policy={PLAIN_POLICY} clientName="Polkomtel" position="" />
          </>}
          aside={<>
            <Rules clientName="Polkomtel" clientSource="manual" languageLabel="PL" filename="Dabrowski_CV.docx" />
            <GenerateBar missing={[]} pending={false} onGenerate={noop} hint="Ok. 40 s. Gotowe CV trafi na listę Moje CV." />
          </>}
        />
      );
    case "upload":
    case "upload-client": {
      const file = new File([new Uint8Array(212 * 1024)], "Anna_Nowak_CV.pdf", { type: "application/pdf" });
      const withMatch = state === "upload";
      return (
        <CvGeneratorLayout
          main={<>
            <UploadIdentityStep
              file={file} fileError={null} onPick={noop} onFileError={noop} onBack={noop} identifying={false}
              matches={withMatch ? [{ candidate_id: 44, full_name: "Anna Nowak", match_reasons: ["phone_exact"] }] : []}
              identifyError={null} onUseMatch={noop} canAddToBase onAddToBase={noop} addingToBase={false}
              decision={withMatch ? "pending" : "without-adding"} onGenerateWithoutAdding={noop}
            />
            {!withMatch ? (
              <>
                <StepCard step={2} title="Klient i źródła">
                  <p className="mb-2 text-sm font-semibold text-foreground">Klient <span className="text-destructive" aria-hidden>*</span></p>
                  <ClientSinglePicker value={null} onChange={noop} queryKey={CV_GENERATOR_CLIENTS_QUERY_KEY} placeholder="Wybierz klienta…" />
                  <p className="mt-2 text-xs text-muted-foreground">Wybierz klienta. Od niego zależą język, nazwa pliku i zgoda RODO.</p>
                  <div className="mt-4 divide-y divide-border rounded-lg border border-border">
                    <UploadSources championFile={null} championError={null} championNotice={null} onChampionFile={noop} onChampionError={noop} notes="" onNotesChange={noop} />
                  </div>
                </StepCard>
                <Content mode="polished" hasChampion={false} language="pl" policy={PLAIN_POLICY} clientName={null} position="" />
              </>
            ) : null}
          </>}
          aside={<>
            <Rules />
            <GenerateBar missing={withMatch ? ["Decyzja: dodać osobę do bazy czy generować bez dodawania"] : ["Klient"]} pending={false} onGenerate={noop} hint="Ok. 40 s. Gotowe CV trafi na listę Moje CV." />
          </>}
        />
      );
    }
    case "result":
      return (
        <CvResultView
          mainId={900} documents={RESULT_DOCS} attachedStage="verified" jobHref="#" canWrite
          onPreview={noop} onEdit={noop} onDownload={noop} onRegenerate={noop} onNew={noop}
        />
      );
    case "my-cv":
      return (
        <MyCvListView
          items={MY_CV} loading={false} error={false} scope="mine" onScopeChange={noop} days={30} onDaysChange={noop}
          query="" onQueryChange={noop} hasMore onLoadMore={noop} loadingMore={false} onOpen={noop} onRetry={noop} now={NOW}
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
    case "start":
    default:
      return (
        <CvGeneratorLayout
          main={person(null)}
          aside={<>
            <Rules />
            <GenerateBar missing={["Kandydat"]} pending={false} onGenerate={noop} hint="Ok. 40 s. Gotowe CV trafi do procesu jako „CV do klienta” i na listę Moje CV." />
          </>}
        />
      );
  }
}

// Karta „CV do klienta” z panelu osoby w rekrutacji — trzy stany z makiety:
// gotowe (auto-CV), brak CV i gotowe bez zgody RODO. Zasiew tymi samymi
// funkcjami kluczy co karta.
const CARD_JOB_ID = 77;
const CARD_PEOPLE = [
  { stageId: 501, candidateId: 11, name: "Jan Kowalski", label: "Gotowe (auto-CV)", variant: "ready" },
  { stageId: 502, candidateId: 12, name: "Piotr Wiśniewski", label: "Brak CV", variant: "none" },
  { stageId: 503, candidateId: 13, name: "Marta Zielińska", label: "Gotowe, brak zgody RODO", variant: "consent" },
] as const;

function seedCardStates(qc: QueryClient) {
  for (const person of CARD_PEOPLE) {
    const generatedId = 9000 + person.stageId;
    const rows: StageGeneratedCvRow[] =
      person.variant === "none"
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
      from_generator: person.variant !== "none",
      generated_document_id: person.variant === "none" ? null : generatedId,
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
  const state: HarnessState = STATES.some(([key]) => key === raw) ? (raw as HarnessState) : "start";
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
        <h1 className="text-2xl font-bold text-foreground">{state === "my-cv" ? "Moje CV" : "Generator CV"}</h1>
        <p className="text-sm text-muted-foreground">
          {state === "my-cv"
            ? "Wygenerowane przez Ciebie w ostatnich 30 dniach."
            : state.startsWith("upload")
              ? "Osoba spoza bazy: dodamy ją przy generacji, żeby CV miało właściciela w NEXUSIE."
              : "Wybierz osobę i proces. Klienta, Championa, notatki i plik CV weźmiemy z NEXUSA."}
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
    qc.setQueryData([CV_GENERATOR_CLIENTS_QUERY_KEY], [
      { id: 7, name: "PKO BP" },
      { id: 15, name: "Polkomtel" },
      { id: 8, name: "Nordea" },
    ]);
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
