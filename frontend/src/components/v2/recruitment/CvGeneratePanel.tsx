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
 *
 * 21.10.2026 (zgłoszenie zespołu, decyzja Artura): ruch na „Zweryfikowany” nie
 * generuje już CV. Przed „Generuj” rekruter potwierdza trzy rzeczy
 * (`CvGenerateConfirm`): plik CV (domyślnie kopia „Oryginał CV” rekrutacji, do
 * wyboru każdy plik CV osoby), odpowiedzi ze screeningu i dodatkowe notatki do
 * CV (pole z okna generatora — zapisuje się w rekrutacji przed generacją).
 * „Napisz od nowa” potwierdzeń nie ma: poprawia CV, które już powstało.
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
import { CvGenerateConfirm } from "@/components/v2/recruitment/CvGenerateConfirm";
import {
  aiSourceRows,
  CV_AI_SOURCE_KEYS,
  type CvAiSourceKey,
  type CvAiSources,
  type CvAiSourceToggles,
} from "@/lib/cv-ai-sources";
import { CV_CONTENT_MODES } from "@/lib/cv-generator";
import {
  confirmationsLeft,
  confirmedCountLabel,
  confirmLeftSentence,
  cvFileChoices,
  NO_CONFIRMATIONS,
  rewriteSourceFileId,
  type CvConfirmations,
} from "@/lib/cv-generate-confirm";
import { canMutateSection } from "@/lib/section-access";
import { cn } from "@/lib/utils";
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
  // „Napisz od nowa” poprawia CV, które już powstało — z jego pliku (audyt 22.10).
  const startId = (rewrite !== undefined ? rewriteSourceFileId(g.aiSourcesQuery.data) : null) ?? originalId;
  // Plik CV do generacji: na start ten z „Z czego powstało” (kopia „Oryginał CV”
  // rekrutacji), potem wybór rekrutera w kroku „Plik CV”.
  const [chosenFile, setChosenFile] = useState<number | null>(null);
  // Bez `…/ai-sources` (awaria) plik domyślny i lista idą z generatora.
  const fileChoices = g.aiSourcesQuery.data
    ? cvFileChoices(g.aiSourcesQuery.data)
    : g.sources.map((source) => ({
        document_id: source.id,
        filename: source.filename,
        uploaded_at: source.uploaded_at,
        is_primary: source.is_primary,
        outdated: false,
        stage_original: false,
      }));
  const fileId = chosenFile ?? startId ?? (g.aiSourcesQuery.isError ? g.cvDocumentId : null);
  useEffect(() => {
    if (fileId != null) setSourceChoice(fileId);
  }, [fileId, setSourceChoice]);

  // Potwierdzenia (21.10.2026) — tylko przy generacji, nie przy „Napisz od nowa”.
  const confirming = rewrite === undefined;
  const [confirmed, setConfirmed] = useState<CvConfirmations>(NO_CONFIRMATIONS);
  const left = confirming ? confirmationsLeft(confirmed, { fileId, noteDraft: g.noteDraft }) : [];

  // Karta należy do JEDNEJ rekrutacji. Osoba z jednym innym procesem dostałaby
  // go z automatu — tu generujemy wyłącznie do tej rekrutacji.
  const listed = g.recruitmentsQuery.isSuccess && !g.recruitmentsQuery.isPlaceholderData;
  const notListed = listed && !g.recruitments.some((r) => r.job_id === jobId);
  const otherProcess = g.recruitment != null && g.recruitment.job_id !== jobId;
  const missing = notListed
    ? ["Rekrutacja — tej rekrutacji nie ma na liście procesów osoby (karta zamknięta?)"]
    : g.missing;
  // Żądanie idzie z pliku z kroku „Plik CV” — lista generatora mogła jeszcze go nie znać.
  const fileInRequest = fileId == null || g.cvDocumentId === fileId;
  // Plik z „…/ai-sources”, którego lista generatora nie zna (np. świeżo wgrany
  // Oryginał CV): pytamy ją raz od nowa, a gdy dalej go nie ma, mówimy to
  // zamiast cicho wyłączać „Generuj” (audyt 22.10).
  const { refetch: refetchSources } = g.sourcesQuery;
  const fileUnknown =
    fileId != null && g.sourcesQuery.isSuccess && !g.sources.some((source) => source.id === fileId);
  const refetchedFor = useRef<number | null>(null);
  useEffect(() => {
    if (!fileUnknown || fileId == null || refetchedFor.current === fileId) return;
    refetchedFor.current = fileId;
    void refetchSources();
  }, [fileUnknown, fileId, refetchSources]);
  const ready = missing.length === 0 && !otherProcess && !g.generating && left.length === 0 && fileInRequest;

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

  // Wiersz „Oryginalne CV” mówi o pliku wybranym w kroku „Plik CV”.
  const sourcesData = g.aiSourcesQuery.data;
  const chosenFileRow = fileChoices.find((file) => file.document_id === fileId) ?? null;
  const shownSources =
    sourcesData && chosenFileRow
      ? {
          ...sourcesData,
          original_cv: {
            document_id: chosenFileRow.document_id,
            filename: chosenFileRow.filename,
            uploaded_at: chosenFileRow.uploaded_at,
          },
        }
      : sourcesData;
  const sourcesRows = (
    <AiSourcesRows
      title="Z czego powstało"
      data={shownSources}
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
      {confirming ? (
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-foreground">Z czego zrobić CV?</p>
          <span
            data-testid="cv-confirm-count"
            className={cn(
              "rounded-full px-2 py-0.5 text-[11px] font-semibold",
              left.length === 0 ? "bg-success-muted text-success-muted-foreground" : "bg-primary/10 text-primary",
            )}
          >
            {confirmedCountLabel(left)}
          </span>
        </div>
      ) : null}
      {confirming && (g.aiSourcesQuery.data || g.aiSourcesQuery.isError) ? (
        <CvGenerateConfirm
          candidateId={candidateId}
          jobId={jobId}
          files={fileChoices}
          answers={g.aiSourcesQuery.data?.answers ?? null}
          existingNotes={g.aiSourcesQuery.data?.notes.count ?? 0}
          fileId={fileId}
          onFileChange={setChosenFile}
          noteDraft={g.noteDraft}
          onNoteDraftChange={g.setNoteDraft}
          confirmed={confirmed}
          onConfirm={setConfirmed}
          left={left}
          disabled={g.generating}
        />
      ) : null}
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
      {rewrite !== undefined ? <RewriteInstruction text={rewrite} /> : null}
      <p className="text-[11px] text-muted-foreground">
        {rewrite !== undefined
          ? "Ok. 40 s. Ręcznie poprawione części zostaną, a poprzednią wersję przywrócisz jednym kliknięciem."
          : replaces
            ? "Ok. 40 s. Nowa wersja zastąpi bieżący szkic, gdy będzie gotowa — zatwierdzone wersje zostają."
            : "Ok. 40 s. Gotowe CV pojawi się tutaj jako CV do klienta."}
      </p>
      {confirmLeftSentence(left) ? (
        <p className="text-xs text-muted-foreground" data-testid="cv-confirm-left">
          {confirmLeftSentence(left)}
        </p>
      ) : null}
      {fileUnknown ? (
        <p className="text-xs text-muted-foreground" data-testid="cv-file-not-in-generator">
          {g.sourcesQuery.isFetching
            ? "Wczytuję listę plików…"
            : "Generator nie widzi tego pliku CV. Odśwież stronę albo wybierz inny plik."}
        </p>
      ) : null}
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

/**
 * Lista poprawek „Napisz od nowa” z podziałem na linie; długa zwinięta do
 * 3 linii, żeby panel nie wypychał przycisków z widoku (15.10.2026).
 */
function RewriteInstruction({ text }: { text: string }) {
  const [all, setAll] = useState(false);
  const value = text.trim();
  const long = value.split("\n").length > 3 || value.length > 240;
  return (
    <div className="text-xs text-foreground" data-testid="cv-rewrite-instruction">
      <p className={cn("whitespace-pre-line [overflow-wrap:anywhere]", long && !all && "line-clamp-3")}>
        {value ? <>Napisz od nowa: „{value}”</> : "Napisz od nowa"}
      </p>
      {long ? (
        <button
          type="button"
          aria-expanded={all}
          className="font-medium text-primary hover:underline"
          onClick={() => setAll((shown) => !shown)}
        >
          {all ? "Zwiń" : "Pokaż całość"}
        </button>
      ) : null}
    </div>
  );
}
