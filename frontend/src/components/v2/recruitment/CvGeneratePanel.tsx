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
 *
 * 14.10.2026 (Edytor CV 3, „Ekran 5”): panel jest zwinięty do jednego zdania
 * — „Z oryginału CV, Championa, screeningu i notatek · Pod rekrutację · polski
 * · Zmień” — liczonego z tych samych przełączników, które pójdą w żądaniu.
 * „Zmień” rozwija przełączniki, obróbkę, język i opcje zaawansowane. Panel
 * rozwija się sam, gdy czegoś brakuje albo serwer odmówił; zgoda RODO, lista
 * braków, błąd i „Generuj” są widoczne zawsze.
 */

import { useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ConsentScreenshotField } from "@/components/v2/cv/ConsentScreenshotField";
import { AdvancedOptions } from "@/components/v2/cv-generator/AdvancedOptions";
import { AiSourcesRows } from "@/components/v2/cv-generator/AiSourcesRows";
import { LanguageChoice } from "@/components/v2/cv-generator/LanguageChoice";
import { ProcessingTiles } from "@/components/v2/cv-generator/ProcessingTiles";
import {
  advancedNeedsAttention,
  type CvLanguageChoice,
} from "@/components/v2/cv-generator/cv-generator-form";
import { useCvGenerator } from "@/components/v2/cv-generator/useCvGenerator";
import {
  aiSourceRows,
  CV_AI_SOURCE_KEYS,
  type CvAiSourceKey,
  type CvAiSources,
  type CvAiSourceToggles,
} from "@/lib/cv-ai-sources";
import { CV_CONTENT_MODES } from "@/lib/cv-generator";
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
  /**
   * „Napisz od nowa” (Edytor CV 3, PR 5): uwaga rekrutera (może być pusta).
   * Panel rusza sam, gdy nic nie czeka na decyzję — jedno kliknięcie w karcie.
   */
  rewrite?: string;
}

const PANEL_CLASS = "space-y-3 rounded-lg border border-primary/30 bg-primary/5 p-3";

/** Źródło w dopełniaczu: „Z oryginału CV, Championa, screeningu i notatek”. */
const SOURCE_IN_SENTENCE: Record<string, string> = {
  original: "oryginału CV",
  champion: "Championa",
  answers: "screeningu",
  notes: "notatek",
  transcripts: "transkryptów",
  prep: "prepu",
};

const LANGUAGE_IN_SENTENCE: Record<CvLanguageChoice, string> = {
  pl: "polski",
  en: "angielski",
  both: "polski i angielski",
};

function isToggleKey(id: string): id is CvAiSourceKey {
  return (CV_AI_SOURCE_KEYS as readonly string[]).includes(id);
}

/**
 * Z czego model naprawdę zrobi CV: źródła „zawsze” i włączone przełączniki
 * z materiałem (pusty przełącznik nic nie zmienia, więc go nie wymieniamy).
 */
export function aiSourcesSentence(data: CvAiSources, toggles: CvAiSourceToggles): string {
  const names = aiSourceRows(data)
    .filter((row) => row.mode === "always" || (isToggleKey(row.id) && !row.empty && toggles[row.id]))
    .map((row) => SOURCE_IN_SENTENCE[row.id])
    .filter((name): name is string => !!name);
  if (names.length === 0) return "Bez materiału dla AI";
  const list = names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} i ${names[names.length - 1]}`;
  // „ze screeningu”, ale „z notatek”.
  return `${/^s[^aeiouyąęó]/i.test(list) ? "Ze" : "Z"} ${list}`;
}

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
  rewrite,
}: CvGeneratePanelProps) {
  const g = useCvGenerator({
    prefillCandidateId: candidateId,
    prefillCandidateName: candidateName,
    prefillJobId: jobId,
    onEnqueued,
    instruction: rewrite,
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

  // Dane panelu się ustaliły: proces wybrany, pliki, zasady klienta i źródła
  // wczytane. Wcześniej lista braków niesie „wczytuję…”, a nie decyzje.
  const sourcesLoading =
    !notListed && (g.recruitmentsQuery.isPending || (g.recruitment != null && g.aiSourcesQuery.isPending));
  const settled =
    listed &&
    !g.sourcesQuery.isPending &&
    !(g.clientId != null && g.policyQuery.isPending) &&
    (notListed || (g.recruitment != null && !g.aiSourcesQuery.isPending));
  // Coś czeka na rekrutera — panel rozwija się sam i już się nie zwija
  // (poprawka wpisywana w rozwiniętym panelu nie może go zamknąć pod palcami).
  const attention =
    g.lastError != null ||
    otherProcess ||
    g.recruitmentsQuery.isError ||
    (settled &&
      (missing.length > 0 ||
        g.aiSourcesQuery.isError ||
        advancedNeedsAttention({
          positionRequired: g.positionRequired,
          position: g.position,
          projectRefRequired: g.projectRefRequired,
          projectRef: g.projectRef,
        })));
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (attention) setExpanded(true);
  }, [attention]);
  const open = expanded || attention;

  // „Napisz od nowa” rusza samo, gdy dane się ustaliły i nic nie czeka na
  // rekrutera (braki, zgoda RODO, błąd) — inaczej panel zostaje otwarty.
  // Dwa kroki: domyślne z polityki i reguły (język, numer projektu) hook
  // ustawia w tym samym przebiegu, w którym dane przychodzą — start rusza
  // w następnym, z nimi w `submit`.
  const { submit } = g;
  const quiet = rewrite !== undefined && settled && !attention && ready;
  const [armed, setArmed] = useState(false);
  const started = useRef(false);
  useEffect(() => {
    if (quiet && !armed) setArmed(true);
  }, [quiet, armed]);
  useEffect(() => {
    if (!armed || !quiet || started.current) return;
    started.current = true;
    submit();
  }, [armed, quiet, submit]);

  const sourcesRows = (
    <AiSourcesRows
      title="Z czego powstało"
      data={g.aiSourcesQuery.data}
      loading={sourcesLoading}
      error={g.aiSourcesQuery.isError}
      onRetry={() => void g.aiSourcesQuery.refetch()}
      value={g.aiSources}
      onChange={g.setAiSource}
      disabled={g.generating}
    />
  );
  const modeLabel =
    CV_CONTENT_MODES.find((mode) => mode.value === (g.capBasic ? "basic" : g.contentMode))?.label ?? null;

  let choices: React.ReactNode;
  if (open) {
    choices = (
      <>
        {sourcesRows}
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
      </>
    );
  } else if (settled && g.aiSourcesQuery.data && g.aiSources) {
    const facts = [
      aiSourcesSentence(g.aiSourcesQuery.data, g.aiSources),
      modeLabel,
      LANGUAGE_IN_SENTENCE[g.languageChoice],
    ].filter((fact): fact is string => !!fact);
    choices = (
      <p data-testid="cv-generate-summary" className="text-xs text-foreground [overflow-wrap:anywhere]">
        {facts.join(" · ")} ·{" "}
        <button
          type="button"
          aria-expanded={false}
          className="font-medium text-primary hover:underline"
          onClick={() => setExpanded(true)}
          disabled={g.generating}
        >
          Zmień
        </button>
      </p>
    );
  } else {
    // Wczytywanie: ten sam stan co rozwinięte „Z czego powstało”, nie puste
    // zdanie — i bez mignięcia wierszy, gdy źródła są już, a zasady klienta nie.
    choices = (
      <AiSourcesRows
        title="Z czego powstało"
        data={undefined}
        loading
        error={false}
        onRetry={() => void g.aiSourcesQuery.refetch()}
        value={null}
        onChange={g.setAiSource}
      />
    );
  }

  return (
    <section aria-label="Generowanie CV" className={PANEL_CLASS} data-testid="cv-generate-panel">
      {choices}
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
      {rewrite !== undefined ? (
        <p className="text-xs text-foreground [overflow-wrap:anywhere]" data-testid="cv-rewrite-instruction">
          {rewrite.trim() ? <>Napisz od nowa: „{rewrite.trim()}”</> : "Napisz od nowa"}
        </p>
      ) : null}
      <p className="text-[11px] text-muted-foreground">
        {rewrite !== undefined
          ? "Ok. 40 s. Ręcznie poprawione części zostaną, a poprzednią wersję przywrócisz jednym kliknięciem."
          : replaces
            ? "Ok. 40 s. Nowa wersja zastąpi bieżący szkic, gdy będzie gotowa — zatwierdzone wersje zostają."
            : "Ok. 40 s. Gotowe CV pojawi się tutaj jako CV do klienta."}
      </p>
      <div className="flex flex-wrap gap-1.5">
        <Button size="sm" onClick={g.submit} disabled={!ready} loading={g.generating}>
          <Sparkles className="h-3.5 w-3.5" aria-hidden /> {rewrite !== undefined ? "Napisz od nowa" : "Generuj"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={g.generating}>
          Anuluj
        </Button>
      </div>
    </section>
  );
}
