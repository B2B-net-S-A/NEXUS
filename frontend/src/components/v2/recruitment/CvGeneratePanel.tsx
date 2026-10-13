"use client";

/**
 * Generowanie CV w karcie „CV do klienta” (PR 4 „CV w procesie”, 13.10.2026).
 *
 * Decyzja Artura: CV powstaje w procesie, więc „Generuj CV”, „Wygeneruj
 * ponownie” i „Spróbuj ponownie” nie otwierają już okna generatora — pod kartą
 * rozwija się panel „Z czego powstało” (D4): oryginalne CV i Champion zawsze,
 * przełączniki odpowiedzi, notatek, transkryptów i prepu, notatki ze stawką
 * zawsze wycinane, do tego obróbka i język. Reguły, braki i żądanie liczy ten
 * sam hook co okno (`useCvGenerator`) — osoba i rekrutacja są ustalone z góry,
 * plik CV to oryginał z „Z czego powstało”.
 */

import { useEffect } from "react";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ConsentScreenshotField } from "@/components/v2/cv/ConsentScreenshotField";
import { AdvancedOptions } from "@/components/v2/cv-generator/AdvancedOptions";
import { AiSourcesRows } from "@/components/v2/cv-generator/AiSourcesRows";
import { LanguageChoice } from "@/components/v2/cv-generator/LanguageChoice";
import { ProcessingTiles } from "@/components/v2/cv-generator/ProcessingTiles";
import { useCvGenerator } from "@/components/v2/cv-generator/useCvGenerator";
import { canMutateSection } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

export interface CvGeneratePanelProps {
  candidateId: number;
  candidateName: string;
  jobId: number;
  /** Etap ma już CV — nowa wersja zastąpi szkic, gdy będzie gotowa. */
  replaces: boolean;
  onEnqueued: (generatedId: number) => void;
  onCancel: () => void;
}

const PANEL_CLASS = "space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-3";

export function CvGeneratePanel(props: CvGeneratePanelProps) {
  const user = useAuthStore((state) => state.user);
  const impersonating = useAuthStore((state) => state.realUser !== null);
  if (!canMutateSection(user, "sourcing", impersonating)) {
    return (
      <section aria-label="Generowanie CV" className={PANEL_CLASS} data-testid="cv-generate-panel">
        <p className="text-xs text-muted-foreground">
          Generowanie CV wymaga prawa zapisu w Sourcing. Gotowe CV możesz obejrzeć i pobrać.
        </p>
        <Button size="sm" variant="ghost" onClick={props.onCancel}>
          Zamknij
        </Button>
      </section>
    );
  }
  return <CvGeneratePanelForm {...props} />;
}

function CvGeneratePanelForm({
  candidateId,
  candidateName,
  jobId,
  replaces,
  onEnqueued,
  onCancel,
}: CvGeneratePanelProps) {
  const g = useCvGenerator({
    prefillCandidateId: candidateId,
    prefillCandidateName: candidateName,
    prefillJobId: jobId,
    onEnqueued,
  });
  const { setSourceChoice } = g;
  const originalId = g.aiSourcesQuery.data?.original_cv?.document_id ?? null;
  // Plik CV do generacji = oryginał z „Z czego powstało” (plik główny osoby).
  useEffect(() => {
    if (originalId != null) setSourceChoice(originalId);
  }, [originalId, setSourceChoice]);

  // Karta należy do JEDNEJ rekrutacji. Osoba z jednym innym procesem dostałaby
  // go z automatu — tu generujemy wyłącznie do tej rekrutacji.
  const listed = g.recruitmentsQuery.isSuccess && !g.recruitmentsQuery.isPlaceholderData;
  const notListed = listed && !g.recruitments.some((r) => r.job_id === jobId);
  const otherProcess = g.recruitment != null && g.recruitment.job_id !== jobId;
  const missing = notListed
    ? ["Rekrutacja — tej rekrutacji nie ma na liście procesów osoby (karta zamknięta?)"]
    : g.missing;
  const ready = missing.length === 0 && !otherProcess && !g.generating;

  return (
    <section aria-label="Generowanie CV" className={PANEL_CLASS} data-testid="cv-generate-panel">
      <AiSourcesRows
        title="Z czego powstało"
        data={g.aiSourcesQuery.data}
        loading={!notListed && (g.recruitmentsQuery.isPending || (g.recruitment != null && g.aiSourcesQuery.isPending))}
        error={g.aiSourcesQuery.isError}
        onRetry={() => void g.aiSourcesQuery.refetch()}
        value={g.aiSources}
        onChange={g.setAiSource}
        disabled={g.generating}
      />
      <div className="space-y-3">
        <ProcessingTiles
          value={g.contentMode}
          onChange={g.setContentMode}
          hasChampion={g.hasChampion}
          capBasic={g.capBasic}
          disabled={g.generating}
          canAddChampion={false}
          compact
        />
        <LanguageChoice
          value={g.languageChoice}
          onChange={g.setLanguageChoice}
          policy={g.languagePolicy}
          clientName={g.clientName}
          disabled={g.generating}
          compact
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
      {g.recruitment && g.consentBlocksGeneration ? (
        <ConsentScreenshotField
          context={{
            candidateId,
            stageId: g.recruitment.stage_id,
            clientId: g.clientId,
            projectRef: g.projectRef,
          }}
          value={g.consentToken}
          onChange={(token) => g.setConsentToken(token)}
          required
          requiredForSending={false}
          disabled={g.generating}
        />
      ) : g.consentRequired ? (
        <p className="text-[11px] text-muted-foreground">
          {g.clientName ?? "Klient"} wymaga zrzutu zgody RODO — dołączysz go na karcie po generacji. Bez
          niego CV się nie pobierze.
        </p>
      ) : null}
      {missing.length > 0 ? (
        <p className="text-xs font-medium text-warning-muted-foreground" data-testid="cvgen-missing">
          Brakuje: {missing.join("; ")}
        </p>
      ) : null}
      {g.lastError ? (
        <p role="alert" className="text-xs text-destructive-muted-foreground">
          {g.lastError}
        </p>
      ) : null}
      <p className="text-[11px] text-muted-foreground">
        {replaces
          ? "Ok. 40 s. Nowa wersja zastąpi bieżący szkic, gdy będzie gotowa — zatwierdzone wersje zostają."
          : "Ok. 40 s. Gotowe CV pojawi się tutaj jako CV do klienta."}
      </p>
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" onClick={g.submit} disabled={!ready} loading={g.generating}>
          <Sparkles className="h-3.5 w-3.5" aria-hidden /> Generuj
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={g.generating}>
          Anuluj
        </Button>
      </div>
    </section>
  );
}
