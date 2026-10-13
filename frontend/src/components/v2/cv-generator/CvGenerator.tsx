"use client";

import { useState, type ReactNode } from "react";

import { Alert } from "@/components/ui/alert";
import { ChampionImportReview } from "@/components/ChampionIntake";
import { ConsentScreenshotField } from "@/components/v2/cv/ConsentScreenshotField";
import { canMutateSection } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

import { AdvancedOptions } from "./AdvancedOptions";
import type { CvLanguageChoice, LanguagePolicy } from "./cv-generator-form";
import { CvResultLive } from "./CvResult";
import { ClientRulesCard, GenerateBar } from "./GenerateBar";
import { StepCard } from "./GeneratorParts";
import { LanguageChoice } from "./LanguageChoice";
import { PersonStep } from "./PersonStep";
import { ProcessStep } from "./ProcessStep";
import { ProcessingTiles } from "./ProcessingTiles";
import { ProcessSources } from "./SourcesPanel";
import { useCvGenerator, type CvGeneratorState } from "./useCvGenerator";

export interface CvGeneratorProps {
  /** Osoba ustalona z góry — generator żyje tylko w oknie (profil, panel osoby, QC). */
  prefillCandidateId: number;
  prefillCandidateName?: string;
  prefillJobId?: number | null;
  onEnqueued?: (generatedId: number) => void;
}

/** Dwie kolumny: kroki po lewej, reguły klienta i „Generuj CV” po prawej. */
export function CvGeneratorLayout({ main, aside }: { main: ReactNode; aside: ReactNode }) {
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
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
 * Generator CV v3 — jeden formularz w oknie z profilu kandydata, panelu osoby
 * i okna QC. Od 13.10.2026 CV powstaje wyłącznie w rekrutacji: osoba z góry,
 * klient z procesu, Champion i notatki uzupełniane w miejscu.
 */
export function CvGenerator(props: CvGeneratorProps) {
  // „Nowe CV” po wyniku = czysty formularz (klucz zeruje cały stan).
  const [formKey, setFormKey] = useState(0);
  return <CvGeneratorForm key={formKey} {...props} onNew={() => setFormKey((k) => k + 1)} />;
}

function CvGeneratorForm({ prefillCandidateId, prefillCandidateName, prefillJobId, onEnqueued, onNew }: CvGeneratorProps & { onNew: () => void }) {
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  const canWrite = canMutateSection(user, "sourcing", impersonating);
  const g = useCvGenerator({ prefillCandidateId, prefillCandidateName, prefillJobId, onEnqueued });

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
        candidateId={g.candidate.id}
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
      <CvGeneratorLayout main={<GeneratorSteps g={g} />} aside={<GeneratorAside g={g} />} />
      {g.championPreview ? (
        <ChampionImportReview
          initial={g.championPreview.data}
          sourceIsDocument
          onClose={g.closeChampionPreview}
          onApply={(profile) => void g.applyChampion(profile)}
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

function GeneratorSteps({ g }: { g: CvGeneratorState }) {
  // Osoba bez rekrutacji: wyjaśnienie w kroku „Proces”, bez reszty formularza.
  const noRecruitment =
    g.recruitmentsQuery.isSuccess && !g.recruitmentsQuery.isPlaceholderData && g.recruitments.length === 0;
  return (
    <>
      <PersonStep candidate={g.candidate} />
      <ProcessStep
        recruitments={g.recruitments}
        loading={g.recruitmentsQuery.isPending}
        error={g.recruitmentsQuery.isError}
        value={g.processChoice}
        onChange={g.chooseProcess}
      >
        {g.recruitment ? (
          <ProcessSources
            jobId={g.recruitment.job_id}
            hasChampion={!!g.recruitment.has_champion}
            championOverride={g.championOverride}
            championBusy={g.championBusy}
            championMessage={g.championMessage}
            onChampionFile={(file) => void g.readChampionFile(file)}
            onChampionError={g.setChampionMessage}
            hasNotes={!!g.recruitment.has_notes}
            notesChars={g.recruitment.notes_chars ?? 0}
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
      {noRecruitment ? null : <ContentStep g={g} />}
    </>
  );
}

function GeneratorAside({ g }: { g: CvGeneratorState }) {
  const consentContext = g.recruitment
    ? { candidateId: g.candidate.id, stageId: g.recruitment.stage_id, clientId: g.clientId, projectRef: g.projectRef }
    : null;
  const hint = [
    "Ok. 40 s. Gotowe CV trafi do procesu jako „CV do klienta”.",
    g.recruitment && !g.hasChampion && !g.recruitment.has_notes && !g.recruitment.required_champion
      ? "Champion i notatki nie są wymagane. Bez nich powstanie Redakcja."
      : null,
  ].filter(Boolean).join(" ");

  return (
    <>
      <ClientRulesCard
        clientName={g.clientName}
        clientSource={g.clientName ? "process" : null}
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
