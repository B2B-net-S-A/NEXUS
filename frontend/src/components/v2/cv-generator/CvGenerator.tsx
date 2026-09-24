"use client";

import { useState, type ReactNode } from "react";

import { Alert } from "@/components/ui/alert";
import { ChampionImportReview, ChampionValidationPanel } from "@/components/ChampionIntake";
import { ClientSinglePicker } from "@/components/clients/ClientSinglePicker";
import { ConsentScreenshotField } from "@/components/v2/cv/ConsentScreenshotField";
import { useCapability } from "@/hooks/useCapability";
import { canMutateSection } from "@/lib/section-access";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

import { AdvancedOptions } from "./AdvancedOptions";
import { OTHER_CLIENT_CHOICE, type CvLanguageChoice, type LanguagePolicy } from "./cv-generator-form";
import { CvResultLive } from "./CvResult";
import { ClientRulesCard, GenerateBar } from "./GenerateBar";
import { StepCard } from "./GeneratorParts";
import { LanguageChoice } from "./LanguageChoice";
import { PersonStep } from "./PersonStep";
import { CV_GENERATOR_CLIENTS_QUERY_KEY, ProcessStep } from "./ProcessStep";
import { ProcessingTiles } from "./ProcessingTiles";
import { ProcessSources, UploadSources } from "./SourcesPanel";
import { UploadIdentityStep } from "./UploadIdentityStep";
import { useCvGenerator, type CvGeneratorState } from "./useCvGenerator";

export interface CvGeneratorProps {
  /** W oknie (profil kandydata, panel osoby) — osoba ustalona z góry. */
  embedded?: boolean;
  prefillCandidateId?: number;
  prefillCandidateName?: string;
  prefillJobId?: number | null;
  onEnqueued?: (generatedId: number) => void;
}

/** Dwie kolumny: kroki po lewej, reguły klienta i „Generuj CV” po prawej. */
export function CvGeneratorLayout({ main, aside, embedded = false }: { main: ReactNode; aside: ReactNode; embedded?: boolean }) {
  return (
    <div
      className={cn(
        "grid items-start gap-4",
        embedded ? "lg:grid-cols-[minmax(0,1fr)_300px]" : "lg:grid-cols-[minmax(0,1fr)_340px]",
      )}
    >
      <div className="min-w-0 space-y-4">{main}</div>
      <aside className="space-y-4 lg:sticky lg:top-4">{aside}</aside>
    </div>
  );
}

/** Etykieta języka w karcie reguł klienta. */
export function languageSummary(choice: CvLanguageChoice, policy: LanguagePolicy): string {
  if (policy.forced) return policy.forced.toUpperCase();
  return choice === "both" ? "PL + EN" : choice.toUpperCase();
}

/**
 * Generator CV v3 — jeden formularz we wszystkich miejscach: strona
 * `/cv-generator`, okno z profilu kandydata i z panelu osoby. Start od osoby,
 * klient zawsze wymagany, Champion i notatki uzupełniane w miejscu.
 */
export function CvGenerator(props: CvGeneratorProps) {
  // „Nowe CV” po wyniku = czysty formularz (klucz zeruje cały stan).
  const [formKey, setFormKey] = useState(0);
  return <CvGeneratorForm key={formKey} {...props} onNew={() => setFormKey((k) => k + 1)} />;
}

function CvGeneratorForm({ embedded = false, prefillCandidateId, prefillCandidateName, prefillJobId, onEnqueued, onNew }: CvGeneratorProps & { onNew: () => void }) {
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  const canWrite = canMutateSection(user, "sourcing", impersonating);
  const canAddToBase = useCapability("candidate.create");
  const g = useCvGenerator({ prefillCandidateId, prefillCandidateName, prefillJobId, onEnqueued });
  const locked = embedded && prefillCandidateId != null;

  if (!canWrite) {
    return (
      <Alert
        variant="info"
        title="Tryb tylko do odczytu"
        description="Możesz przeglądać i pobierać wygenerowane CV, ale generowanie wymaga prawa zapisu w Sourcing."
      />
    );
  }

  if (g.result) {
    return (
      <CvResultLive
        mainId={g.result.id}
        candidateId={g.flow === "person" ? (g.candidate?.id ?? null) : null}
        jobId={g.result.jobId}
        fallbackTitle={{ candidateName: g.result.candidateName, jobTitle: g.result.jobTitle, clientName: g.result.clientName }}
        attachedStage={g.result.attachedToStage ? g.result.stageLabel : null}
        canWrite={canWrite}
        onRegenerate={g.backToForm}
        onNew={onNew}
      />
    );
  }

  return (
    <>
      <CvGeneratorLayout
        embedded={embedded}
        main={<GeneratorSteps g={g} locked={locked} canAddToBase={canAddToBase} />}
        aside={<GeneratorAside g={g} />}
      />
      {g.championPreview ? (
        <ChampionImportReview
          initial={g.championPreview.data}
          sourceIsDocument
          onClose={g.closeChampionPreview}
          onApply={(profile, validation) =>
            g.flow === "upload" ? g.applyUploadChampion(profile, validation) : void g.applyChampion(profile)
          }
        />
      ) : null}
    </>
  );
}

function ContentStep({ g }: { g: CvGeneratorState }) {
  return (
    <StepCard step={3} title="Treść CV">
      <div className="space-y-5">
        <ProcessingTiles
          value={g.contentMode}
          onChange={g.setContentMode}
          hasChampion={g.hasChampion}
          capBasic={g.capBasic}
        />
        <LanguageChoice
          value={g.languageChoice}
          onChange={g.setLanguageChoice}
          policy={g.languagePolicy}
          clientName={g.clientName}
        />
      </div>
      <AdvancedOptions
        open={g.advancedOpen}
        onOpenChange={g.setAdvancedOpen}
        blind={g.blind}
        onBlindChange={g.setBlind}
        position={g.position}
        onPositionChange={g.setPosition}
        positionRequired={g.positionRequired}
        positionFromJob={!!g.recruitment && g.position === g.recruitment.job_title}
        projectRef={g.projectRef}
        onProjectRefChange={g.setProjectRef}
        projectRefVisible={g.projectRefVisible}
        projectRefRequired={g.projectRefRequired}
        projectRefFromJob={g.projectRefFromJob}
      />
    </StepCard>
  );
}

function GeneratorSteps({ g, locked, canAddToBase }: { g: CvGeneratorState; locked: boolean; canAddToBase: boolean }) {
  if (g.flow === "upload") {
    return (
      <>
        <UploadIdentityStep
          file={g.uploadFile}
          fileError={g.uploadError}
          onPick={g.pickUploadFile}
          onFileError={g.setUploadError}
          onBack={g.backToSearch}
          identifying={g.identifyPending}
          matches={g.identifyMatches}
          identifyError={g.identifyError}
          onUseMatch={g.pickMatchedCandidate}
          canAddToBase={canAddToBase}
          onAddToBase={g.addToBase}
          addingToBase={g.addToBasePending}
          decision={g.uploadDecision}
          onGenerateWithoutAdding={g.generateWithoutAdding}
        />
        {g.uploadDecision === "without-adding" && g.uploadFile ? (
          <>
            <StepCard step={2} title="Klient i źródła">
              <div className="space-y-2">
                <p className="text-sm font-semibold text-foreground">
                  Klient <span className="text-destructive" aria-hidden>*</span>
                </p>
                <ClientSinglePicker
                  value={g.uploadClient}
                  onChange={g.setUploadClient}
                  queryKey={CV_GENERATOR_CLIENTS_QUERY_KEY}
                  placeholder="Wybierz klienta…"
                />
                <p className="text-xs text-muted-foreground">
                  Wybierz klienta. Od niego zależą język, nazwa pliku i zgoda RODO.
                </p>
              </div>
              <div className="mt-4 divide-y divide-border rounded-lg border border-border">
                <UploadSources
                  championFile={g.uploadChampionFile}
                  championError={g.uploadChampionError}
                  championNotice={g.uploadChampionNotice}
                  onChampionFile={(file) => void g.pickUploadChampion(file)}
                  onChampionError={g.setUploadChampionError}
                  notes={g.uploadNotes}
                  onNotesChange={g.setUploadNotes}
                />
              </div>
              <ChampionValidationPanel validation={g.uploadChampionValidation} />
            </StepCard>
            <ContentStep g={g} />
          </>
        ) : null}
      </>
    );
  }

  return (
    <>
      <PersonStep
        candidate={g.candidate}
        query={g.candidateQuery}
        onQueryChange={g.setCandidateQuery}
        results={g.candidatesQuery.data ?? []}
        searching={g.candidatesQuery.isFetching}
        searchError={g.candidateSearchError}
        onChoose={g.chooseCandidate}
        onStartUpload={locked ? undefined : g.startUpload}
        locked={locked}
      />
      {g.candidate ? (
        <>
          <ProcessStep
            recruitments={g.recruitments}
            loading={g.recruitmentsQuery.isPending}
            error={g.recruitmentsQuery.isError}
            value={g.processChoice}
            onChange={g.chooseProcess}
            otherClient={g.otherClient}
            onOtherClientChange={g.setOtherClient}
          >
            {g.processChoice ? (
              <ProcessSources
                variant={g.processChoice === OTHER_CLIENT_CHOICE ? "no-process" : "process"}
                jobId={g.recruitment?.job_id ?? null}
                hasChampion={!!g.recruitment?.has_champion}
                championOverride={g.championOverride}
                championBusy={g.championBusy}
                championMessage={g.championMessage}
                onChampionFile={(file) => void g.readChampionFile(file)}
                onChampionError={g.setChampionMessage}
                hasNotes={!!g.recruitment?.has_notes}
                notesChars={g.recruitment?.notes_chars ?? 0}
                noteDraft={g.noteDraft}
                onNoteDraftChange={g.setNoteDraft}
                sources={g.sources}
                sourcesLoading={g.sourcesQuery.isPending}
                sourcesError={g.sourcesQuery.isError}
                cvDocumentId={g.cvDocumentId}
                onSourceChange={g.setSourceChoice}
              />
            ) : null}
          </ProcessStep>
          <ContentStep g={g} />
        </>
      ) : null}
    </>
  );
}

function GeneratorAside({ g }: { g: CvGeneratorState }) {
  const withProcess = g.flow === "person" && !!g.recruitment;
  const consentContext =
    g.flow === "person" && g.candidate && g.recruitment
      ? { candidateId: g.candidate.id, stageId: g.recruitment.stage_id, clientId: g.clientId, projectRef: g.projectRef }
      : g.flow === "person" && g.candidate && g.clientId != null
        ? { candidateId: g.candidate.id, clientId: g.clientId, projectRef: g.projectRef }
        : g.flow === "upload" && g.uploadFile
        ? { cvFile: g.uploadFile, clientId: g.clientId, projectRef: g.projectRef }
        : null;
  const hint = [
    withProcess
      ? "Ok. 40 s. Gotowe CV trafi do procesu jako „CV do klienta” i na listę Moje CV."
      : "Ok. 40 s. Gotowe CV trafi na listę Moje CV.",
    withProcess && !g.hasChampion && !g.recruitment?.has_notes && !g.recruitment?.required_champion
      ? "Champion i notatki nie są wymagane. Bez nich powstanie Redakcja."
      : null,
  ].filter(Boolean).join(" ");

  return (
    <>
      <ClientRulesCard
        clientName={g.clientName}
        clientSource={g.clientName ? (withProcess ? "process" : "manual") : null}
        loading={g.clientId != null && (g.policyQuery.isPending || false)}
        error={g.policyQuery.isError}
        languageLabel={languageSummary(g.languageChoice, g.languagePolicy)}
        filename={g.activeRule?.filename_preview ?? g.policy?.effective_policy?.filename_pattern ?? null}
        projectRef={g.projectRefFromJob ?? (g.projectRef.trim() || null)}
        projectRefFromJob={!!g.projectRefFromJob}
        consentRequired={g.consentRequired}
        consentAttached={!!g.consentToken}
        consentSlot={
          consentContext ? (
            <ConsentScreenshotField
              context={consentContext}
              value={g.consentToken}
              onChange={(token) => g.setConsentToken(token)}
              required={g.consentBlocksGeneration}
              requiredForSending={!g.consentBlocksGeneration}
              disabled={g.generating}
            />
          ) : (
            <p className="text-xs text-muted-foreground">Zrzut dodasz też po generacji — w widoku wyniku.</p>
          )
        }
      />
      <GenerateBar missing={g.missing} pending={g.generating} onGenerate={g.submit} hint={hint} />
    </>
  );
}
