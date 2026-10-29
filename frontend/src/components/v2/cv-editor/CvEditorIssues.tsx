"use client";

/**
 * Panel „Do poprawy” w edytorze CV (Edytor CV 2, PR 2, decyzje Artura D2 i D6).
 *
 * Jedno miejsce na to, co system już wie o tym CV: QC CV pary (te same karty
 * co w oknie QC), uwagi generatora i wynik kontroli AI ostatniej zatwierdzonej
 * wersji. Przy każdej uwadze z miejscem w tekście jest „Pokaż w CV”, a same
 * miejsca są zaznaczone na kartce (`lib/cv-editor-issue-marks.ts`).
 *
 * Poprawkę liczy serwer NA TREŚCI Z EDYTORA (`qc/transform`, bez zapisu),
 * a panel nakłada wynik jednym cofalnym krokiem — utrwala go zwykły autozapis.
 * Dzięki temu panel i pisanie nie ścigają się o wersję szkicu. Lista QC dotyczy
 * ostatnio ZAPISANEJ treści i odświeża się po autozapisie; przebieg QC dla
 * Tablicy zapisuje się raz, przy zamknięciu edytora.
 *
 * Panel nie ma obejścia QC ani ruchu karty — przekazanie Delivery Leadowi
 * (z obejściem przez „Przekaż mimo uwag…”) stoi w stopce edytora (D6,
 * 14.10.2026), a panel podaje mu wynik QC przez `onCount`. Edytor wyniku
 * generatora (bez etapu) pokazuje tylko uwagi generatora: QC nie widzi jego
 * edycji.
 *
 * Propozycje AI (D5, 14.10.2026) ładują się same, gdy QC ma pozycję
 * z poprawką AI — serwer liczy je zaraz po automacie, więc zwykle to odczyt
 * z pamięci. „Popraw wszystko” od razu bierze zdania AI.
 *
 * „To nieprawda” (D5, 13.10.2026) jest przy pozycjach QC (te same karty co
 * w oknie QC), uwagach generatora i kontroli AI; pominięte stoją zwinięte
 * w „Pominięte” z „Przywróć”. Bez etapu nie ma pary, więc nie ma pominięć.
 *
 * PR 4 „CV w procesie” (13.10.2026): trzy źródła to JEDNA lista
 * (`buildIssueList`) — grupy sekcji CV w kolejności kartki z etykietą źródła
 * przy każdej pozycji, potem „Zapytaj kandydata”, „Pominięte”, „Informacje”
 * i „W porządku”. Uwaga generatora „MUST-HAVE: X” nie dubluje pozycji QC o X.
 * Ta sama liczba stoi na karcie „CV do klienta” (`cvChecksBeforeSending`).
 *
 * Wariant A (decyzje Artura D1–D7, 17.10.2026): lista idzie po tym, co
 * rekruter ma zrobić — „Blokuje wysyłkę”, „Do poprawy” (z „Popraw
 * wszystkie”), „Poprawione” (z „Cofnij”) i „Do decyzji · nie blokuje”. Jeden
 * wiersz = problem, podgląd zmiany i jeden przycisk (`CvEditorIssueRows`);
 * zdanie AI stoi w wierszu swojej uwagi. Gdy rekruter pisze do asystenta,
 * panel zwija się do paska z liczbami (`summary`), a „Przekaż mimo uwag…”
 * stoi także w nagłówku blokad (`onOverride` — ta sama droga co stopka).
 */

import { useEffect, useId, useImperativeHandle, useMemo, useRef, useState, type ReactNode, type Ref } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Editor } from "@tiptap/core";
import { Check, CheckCircle2, ChevronDown, ChevronRight, Loader2, RefreshCw, Undo2, Wand2 } from "lucide-react";
import type { Node as PMNode } from "@tiptap/pm/model";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IssueRowView, type IssueDismiss, type RowContext } from "@/components/v2/cv-editor/CvEditorIssueRows";
import {
  Confirmations,
  DismissButton,
  DismissForm,
  DismissedSection,
  MutedChecks,
  PassedChecks,
  QcWordFileNote,
  SECTION_TITLE,
  qcDismissedEntries,
  type ActionContext,
  type DismissedEntry,
} from "@/components/v2/recruitment/cv-qc-cards";
import { apiErrorMessage } from "@/lib/api-error";
import {
  cvEditorIssuesQueryKey,
  cvEditorQcQueryKey,
  networkIssuesApi,
  type CvEditorIssuesApi,
  type CvEditorIssuesData,
  type CvIssueDismissBody,
  type CvReviewFinding,
} from "@/lib/api/cvEditorIssues";
import {
  cvQcFixesQueryKey,
  cvQcQueryKey,
  invalidateAfterQcChange,
  type QcDismissBody,
  type QcFix,
  type QcFixAction,
  type QcFixesResponse,
  type QcItem,
  type QcResult,
  type QcTransformSkipped,
} from "@/lib/api/cvQc";
import { copyTextToClipboard } from "@/lib/clipboard";
import { clearIssueFocus, setIssueMarks, showIssueInCv } from "@/lib/cv-editor-issue-marks";
import {
  REVIEW_FINDING_LABEL,
  appliedActions,
  appliedLabel,
  buildIssueList,
  boldRequirements,
  bulkPlan,
  findingsInCv,
  fixAlreadyInCv,
  fixStep,
  issueMarks,
  issueRows,
  locateTarget,
  rowInBulk,
  type IssueRange,
  type IssueRow,
} from "@/lib/cv-editor-issues";
import { classifyCvWarnings, type ClassifiedCvWarning } from "@/lib/cv-generator";
import { humanizeCvWarning } from "@/lib/cv-warning-text";
import { candidateQuestion, countForm, qcDismissedMessage, type IssueTarget } from "@/lib/cv-qc";
import { isForbiddenError } from "@/lib/view-state";
import { cn } from "@/lib/utils";

/**
 * Ile uwag jest na liście i ile z nich zatrzymuje wysyłkę (licznik QC z serwera).
 * `state` mówi, czy liczbie można wierzyć: zero w trakcie liczenia albo po
 * awarii QC to nie „brak uwag”.
 */
export interface CvIssueCount {
  total: number;
  blocking: number;
  state: "loading" | "ready" | "failed";
  /**
   * Wynik QC tej treści (`null`: bez etapu, QC jeszcze się liczy albo opisuje
   * inne CV pary) — stopka przekazania czyta z niego obejście i tryb doradczy.
   */
  qc?: QcResult | null;
}

export interface CvEditorIssuesProps {
  editor: Editor;
  /** Etap rekrutacji. Bez niego (wynik generatora) panel ma tylko uwagi generatora. */
  stageId?: number;
  /** Uwagi generatora dla edytora bez etapu — z listy, z której otwarto edytor. */
  generatorWarnings?: readonly string[];
  /** Wersja szkicu zapisana na serwerze; zmiana = QC liczy się od nowa. */
  savedRevision: number;
  /** Treść w edytorze różni się od zapisanej. */
  unsaved: boolean;
  /** Podgląd Word albo trwający zapis — poprawki wyłączone. */
  readOnly: boolean;
  /** Zakłada szkic na zatwierdzonej wersji przed poprawką; `false` = nie udało się. */
  ensureDraft: () => Promise<boolean>;
  /** Pokazuje kartkę (wąski ekran, podgląd Word), zanim panel przewinie do miejsca. */
  onShowCv: () => void;
  onCount?: (count: CvIssueCount) => void;
  /** Harness: dane z pamięci zamiast sieci. */
  api?: CvEditorIssuesApi;
  /** „Pogrub wymagania (N)” z nagłówka edytora woła poprawkę tego panelu. */
  ref?: Ref<CvEditorIssuesHandle>;
  /**
   * Asystent rozwinięty (17.10.2026): zostaje pasek z liczbami i „Lista”, lista
   * się chowa — panel dalej liczy znaczniki na kartce i liczbę w pasku.
   */
  summary?: boolean;
  /** „Lista” w pasku — wraca do listy (asystent zwija się do jednej linii). */
  onShowList?: () => void;
  /**
   * „Przekaż mimo uwag…” w nagłówku blokad — ta sama akcja co w stopce
   * (karta na „Zweryfikowany” i prawo obejścia); bez niej przycisku nie ma.
   */
  onOverride?: () => void;
  /** Ten sam warunek co w stopce (asystent pracuje, szkic się zakłada) — przycisk czeka. */
  overrideDisabled?: boolean;
  /**
   * „Usuń z CV” przy terminie, który stoi w zdaniu (nie na liście technologii):
   * serwer go nie usuwa, więc panel prosi asystenta o przeredagowanie zdania
   * bez tego słowa (PR 3, 17.10.2026). Bez asystenta — komunikat jak dotąd.
   */
  onAskAssistant?: (command: string) => void;
}

/** Polecenia panelu dla nagłówka edytora (Edytor CV 3, PR 3). */
export interface CvEditorIssuesHandle {
  /** Pogrubia wymagania klienta, których QC nie widzi pogrubionych — jak „Pogrub wszystkie”. */
  boldRequirements: () => void;
}

/** Po tylu ms od zapisu szkicu panel prosi o świeże QC (autozapis chodzi co 2 s). */
const QC_REFRESH_DELAY_MS = 1500;
/** Tyle ms miejsce wskazane przez „Pokaż w CV” zostaje wyróżnione. */
const FOCUS_MS = 2600;

const NO_FINDINGS: CvReviewFinding[] = [];
const NO_WARNINGS: readonly string[] = [];

/** Po najbliższym rysowaniu ekranu (stan Reacta z tej samej chwili jest już w DOM). */
function afterPaint(callback: () => void): void {
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => setTimeout(callback, 0));
  else setTimeout(callback, 0);
}

/** Nałożona poprawka — wiersz „Poprawione” z „Cofnij”, dopóki CV się po niej nie zmieniło. */
interface AppliedFix {
  id: number;
  labels: string[];
  /** Dokument zaraz po poprawce — „Cofnij” działa tylko, gdy edytor nadal go trzyma. */
  after: PMNode;
  bulk: boolean;
  skipped: QcTransformSkipped[];
}

/** Tyle ostatnich poprawek zostaje na liście „Poprawione”. */
const APPLIED_SHOWN = 6;

function GeneratorWarnings({ warnings, dismiss }: { warnings: readonly string[]; dismiss?: IssueDismiss }) {
  const infoId = useId();
  const [infoOpen, setInfoOpen] = useState(false);
  const [dismissText, setDismissText] = useState<string | null>(null);
  const { review, info } = useMemo(() => classifyCvWarnings(warnings), [warnings]);
  if (review.length + info.length === 0) return null;
  return (
    <section aria-label="Uwagi generatora" className="space-y-2">
      <h3 className={SECTION_TITLE}>Uwagi generatora ({review.length})</h3>
      {review.length > 0 ? (
        <ul className="space-y-1.5">
          {review.map((item) => (
            <li key={item.text} className="space-y-0.5 rounded-lg border border-warning/30 px-3 py-2 text-sm">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-warning-muted-foreground">{item.kind}</p>
              <p className="[overflow-wrap:anywhere]">{humanizeCvWarning(item.text)}</p>
              {dismiss ? (
                dismissText === item.text ? (
                  <DismissForm
                    subject={humanizeCvWarning(item.text)}
                    pending={dismiss.pending}
                    onSubmit={(value) =>
                      dismiss.submit({ source: "generator", text: item.text, status: null }, value, () =>
                        setDismissText(null),
                      )
                    }
                    onClose={() => setDismissText(null)}
                  />
                ) : (
                  <DismissButton onClick={() => setDismissText(item.text)} disabled={dismiss.pending} />
                )
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">Generator nie zgłosił niczego do sprawdzenia.</p>
      )}
      {info.length > 0 ? (
        <div className="rounded-lg border border-border">
          <button
            type="button"
            aria-expanded={infoOpen}
            aria-controls={infoId}
            onClick={() => setInfoOpen((open) => !open)}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-muted-foreground"
          >
            <ChevronRight aria-hidden className={cn("size-3.5 flex-none transition-transform", infoOpen && "rotate-90")} />
            <span className="font-semibold text-foreground">Informacje ({info.length})</span>
            <span className="min-w-0 truncate">— co generator zrobił i dlaczego</span>
          </button>
          {infoOpen ? (
            <ul id={infoId} className="space-y-1.5 border-t border-border px-3 py-2 text-xs text-muted-foreground">
              {info.map((item) => (
                <li key={item.text} className="[overflow-wrap:anywhere]">
                  {humanizeCvWarning(item.text)}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/** Informacje generatora — co zrobił i dlaczego; zwinięte, nie liczą się. */
/**
 * Luki kandydata (D2, 17.10.2026): wymagania, których nie ma w CV, oryginale
 * ani rozmowie. Jedna linia zamiast pozycji „do poprawy” — w CV nie ma czego
 * poprawić, to pytanie do rozmowy z kandydatem.
 */
function CandidateGaps({ items }: { items: readonly QcItem[] }) {
  const names = [...new Set(items.map((item) => (item.requirement ?? "").trim()).filter(Boolean))];
  if (names.length === 0) return null;
  const head = names.slice(0, 3).join(", ");
  const rest = names.length > 3 ? ` i ${countForm(names.length - 3, ["inne", "inne", "innych"])}` : "";
  return (
    <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
      <span className="font-semibold text-foreground">Luki kandydata ({names.length}):</span> {head}
      {rest} — nie ma tego w CV, w oryginale ani w rozmowie. Do rozmowy, nie do poprawy w CV.
    </p>
  );
}

function GeneratorInfo({ items }: { items: readonly ClassifiedCvWarning[] }) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  if (items.length === 0) return null;
  return (
    <div className="rounded-lg border border-border">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-muted-foreground"
      >
        <ChevronRight aria-hidden className={cn("size-3.5 flex-none transition-transform", open && "rotate-90")} />
        <span className="font-semibold text-foreground">Od generatora ({items.length})</span>
        <span className="min-w-0 truncate">— co zrobił i dlaczego</span>
      </button>
      {open ? (
        <ul id={listId} className="space-y-1.5 border-t border-border px-3 py-2 text-xs text-muted-foreground">
          {items.map((item) => (
            <li key={item.text} className="[overflow-wrap:anywhere]">
              {humanizeCvWarning(item.text)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function CvEditorIssues({
  editor,
  stageId,
  generatorWarnings,
  savedRevision,
  unsaved,
  readOnly,
  ensureDraft,
  onShowCv,
  onCount,
  api = networkIssuesApi,
  ref,
  summary = false,
  onShowList,
  onOverride,
  overrideDisabled = false,
  onAskAssistant,
}: CvEditorIssuesProps) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const hasStage = stageId != null;
  const stageKey = stageId ?? 0;

  const qcQuery = useQuery<QcResult>({
    queryKey: cvEditorQcQueryKey(stageKey),
    queryFn: () => api.qc(stageKey),
    enabled: hasStage,
    // W trakcie sesji odświeża je sam panel (po autozapisie). Każde otwarcie
    // edytora liczy od nowa i nie trzyma wyniku po zamknięciu — inaczej
    // ponowne otwarcie pokazywało listę sprzed poprawek z poprzedniej sesji.
    staleTime: Infinity,
    refetchOnMount: "always",
    gcTime: 0,
    retry: false,
  });
  const issuesQuery = useQuery<CvEditorIssuesData>({
    queryKey: cvEditorIssuesQueryKey(stageKey),
    queryFn: () => api.issues(stageKey),
    enabled: hasStage,
    staleTime: Infinity,
    refetchOnMount: "always",
    gcTime: 0,
    retry: false,
  });

  // ── QC po autozapisie i przebieg dla Tablicy przy zamknięciu ───────────────
  const seenRevision = useRef(savedRevision);
  const savedHere = useRef(false);
  const refetchQc = qcQuery.refetch;
  useEffect(() => {
    if (!hasStage || unsaved || savedRevision === seenRevision.current) return;
    const timer = setTimeout(() => {
      seenRevision.current = savedRevision;
      savedHere.current = true;
      void refetchQc();
    }, QC_REFRESH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [hasStage, unsaved, savedRevision, refetchQc]);
  // Wersja mogła się zmienić tuż przed zamknięciem — zanim minęło opóźnienie.
  const latestRevision = useRef(savedRevision);
  latestRevision.current = savedRevision;
  useEffect(() => {
    if (!hasStage) return;
    const openedRevision = latestRevision.current;
    return () => {
      if (!savedHere.current && latestRevision.current === openedRevision) return;
      // Tablica i kolejki czytają ZAPISANY przebieg QC — jeden na sesję edycji.
      // Przez `fetchQuery`: wynik trafia do klucza okna QC, a awaria do
      // zgłaszania błędów zapytań (`QueryProvider`) — panelu już nie ma,
      // więc nie ma komu pokazać komunikatu.
      void queryClient
        .fetchQuery({
          queryKey: cvQcQueryKey(stageKey),
          queryFn: () => api.persistQc(stageKey),
          staleTime: 0,
          retry: false,
        })
        .then((result) => invalidateAfterQcChange(queryClient, result.job_id))
        .catch(() => undefined);
    };
  }, [api, hasStage, queryClient, stageKey]);

  // ── Bieżąca treść: znaczniki i to, co nadal stoi w CV ──────────────────────
  const [docTick, setDocTick] = useState(0);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onTransaction = ({ transaction }: { transaction: { docChanged: boolean } }) => {
      if (!transaction.docChanged) return;
      clearTimeout(timer);
      timer = setTimeout(() => setDocTick((tick) => tick + 1), 200);
    };
    editor.on("transaction", onTransaction);
    return () => {
      editor.off("transaction", onTransaction);
      clearTimeout(timer);
    };
  }, [editor]);

  const qc = qcQuery.data;
  // Para ma kilka wierszy etapu, a QC bierze zatwierdzone CV pary — bywa, że inne niż otwarte.
  const otherDocument = !!qc && (qc.cv == null || qc.cv.stage_id !== stageId);
  const checks = useMemo(() => (qc && !otherDocument ? qc.checks : []), [qc, otherDocument]);
  // Zdania AI dopisuje do ról — także wtedy, gdy QC już przechodzi, a brak
  // opisu jest tylko uwagą.
  const hasAiGaps = checks.some((check) => check.status === "fail" && check.items.some((item) => item.fix === "ai"));
  // D5 (14.10.2026): propozycje ładują się same, gdy jest pozycja z poprawką AI.
  // Serwer liczy je zaraz po automacie i pamięta per treść — zwykle to odczyt.
  const fixesQuery = useQuery<QcFixesResponse>({
    queryKey: cvQcFixesQueryKey(stageKey),
    queryFn: () => api.fixes(stageKey),
    enabled: hasStage && hasAiGaps,
    staleTime: Infinity,
    retry: false,
  });
  const review = issuesQuery.data?.content_review ?? null;
  const allFindings = review?.findings ?? NO_FINDINGS;
  const warnings = hasStage ? (issuesQuery.data?.generator_warnings ?? NO_WARNINGS) : (generatorWarnings ?? NO_WARNINGS);

  const presentFindings = useMemo(
    () => (editor.isDestroyed ? NO_FINDINGS : findingsInCv(editor.state.doc, allFindings)),
    // `docTick` = treść się zmieniła.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editor, allFindings, docTick],
  );
  useEffect(() => {
    if (editor.isDestroyed) return;
    setIssueMarks(editor, issueMarks(editor.state.doc, checks, presentFindings));
  }, [editor, checks, presentFindings, docTick]);
  useEffect(() => () => setIssueMarks(editor, []), [editor]);

  const focusTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(focusTimer.current), []);
  const flash = (where: IssueRange | readonly IssueRange[], afterFix = false) => {
    onShowCv();
    // Kartka mogła być ukryta (wąski ekran, podgląd Word) — przewijamy dopiero
    // po klatce, w której React ją pokazał.
    afterPaint(() => {
      showIssueInCv(editor, where);
      // Po poprawce klawiatura wraca do tekstu: Ctrl+Z działa bez klikania w kartkę.
      // Nie na ekranie dotykowym — tam fokus wysuwa klawiaturę na pół ekranu.
      if (afterFix && !editor.isDestroyed && !window.matchMedia?.("(pointer: coarse)").matches) {
        editor.view.dom.focus({ preventScroll: true });
      }
      clearTimeout(focusTimer.current);
      focusTimer.current = setTimeout(() => clearIssueFocus(editor), FOCUS_MS);
    });
  };
  // `quiet`: rozwinięcie wiersza też pokazuje miejsce, ale bez komunikatu, gdy go nie ma.
  const locate = (target: IssueTarget, quiet = false) => {
    if (editor.isDestroyed) return;
    const range = locateTarget(editor.state.doc, target);
    if (range) flash(range);
    else if (!quiet) showError("Tego miejsca nie ma już w treści CV — tekst zmienił się od ostatniego sprawdzenia.");
  };

  // ── Poprawki: serwer liczy, edytor nakłada jednym krokiem ──────────────────
  const [working, setWorking] = useState(false);
  const workingRef = useRef(false);
  // „Poprawione”: co panel nałożył w tej sesji, najnowsze pierwsze.
  const [applied, setApplied] = useState<AppliedFix[]>([]);
  const appliedId = useRef(0);

  const run = async (actions: QcFixAction[], bulk: boolean, success: string, onApplied?: () => void) => {
    if (!hasStage || workingRef.current || editor.isDestroyed) return;
    workingRef.current = true;
    setWorking(true);
    try {
      const before = editor.state.doc;
      const result = await api.transform(stageKey, { content_html: editor.getHTML(), actions, bulk });
      if (editor.isDestroyed) return;
      const changedMeanwhile = () => {
        if (editor.state.doc.eq(before)) return false;
        showError("Treść CV zmieniła się, zanim poprawka była gotowa — kliknij jeszcze raz.");
        return true;
      };
      if (changedMeanwhile()) return;
      // Pusta treść nie jest poprawką — nie zastępujemy nią CV.
      const usable = result.changed && result.content_html.trim() !== "";
      if (!usable || !fixStep(editor.state, result.content_html)) {
        const only = actions.length === 1 ? actions[0] : null;
        if (
          only?.action === "remove_term" &&
          onAskAssistant &&
          result.skipped[0]?.code === "nothing_to_do"
        ) {
          // Termin stoi w zdaniu — przeredagowanie robi asystent (z kontrolą
          // „bez nowych faktów” i „Cofnij” przy odpowiedzi).
          onAskAssistant(
            `Usuń „${only.term}” z CV: przeredaguj zdania, w których to słowo stoi, bez niego. Nie dopisuj nowych faktów.`,
          );
          showSuccess(`„${only.term}” stoi w zdaniu — asystent przeredaguje je bez tego słowa.`);
          return;
        }
        showError(result.skipped[0]?.message ?? "Tej poprawki nie da się nałożyć na bieżącą treść CV.");
        return;
      }
      // Szkic dopiero teraz: nowy szkic zdejmuje z CV stan „zatwierdzone”,
      // więc poprawka, która nic nie zmienia, nie może go zakładać.
      if (!(await ensureDraft()) || editor.isDestroyed || changedMeanwhile()) return;
      const step = fixStep(editor.state, result.content_html);
      if (!step) return;
      editor.view.dispatch(step.transaction);
      flash(step.changed, true);
      const done = bulk ? appliedActions(actions, result.applied) : actions;
      appliedId.current += 1;
      const entry: AppliedFix = {
        id: appliedId.current,
        labels: done.map((action) => appliedLabel(action, checks, fixesQuery.data?.fixes ?? [])),
        after: editor.state.doc,
        bulk,
        skipped: result.skipped,
      };
      setApplied((list) => [entry, ...list].slice(0, APPLIED_SHOWN));
      showSuccess(success);
      onApplied?.();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się policzyć poprawki. Spróbuj ponownie."));
    } finally {
      workingRef.current = false;
      setWorking(false);
    }
  };

  // Świeży wynik QC z zapisu zastępuje listę panelu i okna QC, Tablica się odświeża.
  const storeQc = (result: QcResult) => {
    queryClient.setQueryData(cvEditorQcQueryKey(stageKey), result);
    queryClient.setQueryData(cvQcQueryKey(stageKey), result);
    invalidateAfterQcChange(queryClient, result.job_id);
  };
  const storeIssues = (data: CvEditorIssuesData) => queryClient.setQueryData(cvEditorIssuesQueryKey(stageKey), data);
  const confirm = useMutation({
    mutationFn: (body: { term: string; text?: string }) => api.confirm(stageKey, body),
    onSuccess: storeQc,
  });
  const dismissQc = useMutation({
    mutationFn: (body: QcDismissBody) => api.dismiss(stageKey, body),
    onSuccess: storeQc,
  });
  const restoreQc = useMutation({
    mutationFn: (dismissalId: number) => api.restore(stageKey, dismissalId),
    onSuccess: storeQc,
  });
  const dismissIssue = useMutation({
    mutationFn: (body: CvIssueDismissBody) => api.dismissIssue(stageKey, body),
    onSuccess: storeIssues,
  });
  const restoreIssue = useMutation({
    mutationFn: (dismissalId: number) => api.restoreIssue(stageKey, dismissalId),
    onSuccess: storeIssues,
  });
  const dismissFailed = (error: unknown) =>
    showError(apiErrorMessage(error, "Nie udało się zapisać pominięcia. Spróbuj ponownie."));
  const restoreFailed = (error: unknown) =>
    showError(apiErrorMessage(error, "Nie udało się przywrócić uwagi. Spróbuj ponownie."));
  const issueDismiss: IssueDismiss = {
    keep: (issue) =>
      dismissIssue.mutate(
        { ...issue, reason: "kept" },
        { onSuccess: () => showSuccess("Zostaje w CV — uwaga zeszła z listy."), onError: dismissFailed },
      ),
    submit: (issue, value, onSaved) =>
      dismissIssue.mutate(
        { ...issue, reason: value.reason, ...(value.note ? { note: value.note } : {}) },
        {
          onSuccess: () => {
            showSuccess("Oznaczono jako nieprawdę.");
            onSaved();
          },
          onError: dismissFailed,
        },
      ),
    pending: dismissIssue.isPending,
  };

  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const fixes = fixesQuery.data;
  const visibleFixes = useMemo(
    () =>
      (fixes?.fixes ?? []).filter(
        (fix: QcFix) => !dismissed.has(fix.id) && (editor.isDestroyed || !fixAlreadyInCv(editor.state.doc, fix)),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editor, fixes, dismissed, docTick],
  );

  const ctx: ActionContext | null =
    qc && !otherDocument
      ? {
          data: qc,
          editable: true,
          busy: working || readOnly,
          apply: (body, success, onApplied) => void run([body], false, `${success} Ctrl+Z cofa.`, onApplied),
          confirm: (body, onSaved) =>
            confirm.mutate(body, {
              onSuccess: () => {
                showSuccess("Potwierdzenie zapisane w notatkach kandydata.");
                onSaved?.();
              },
              onError: (error) =>
                showError(apiErrorMessage(error, "Nie udało się zapisać potwierdzenia. Spróbuj ponownie.")),
            }),
          confirming: confirm.isPending,
          // Zdanie AI stoi w wierszu swojej uwagi (17.10.2026) — nie ma dokąd przewijać.
          requestAiFixes: () => undefined,
          copyQuestion: (item) => {
            const question = candidateQuestion(item);
            void copyTextToClipboard(question).then((ok) =>
              ok
                ? showSuccess("Pytanie skopiowane — wyślij je kandydatowi.")
                : showError(`Przeglądarka nie pozwoliła skopiować. Pytanie: ${question}`),
            );
          },
          openEditor: null,
          locate,
          linksInNewTab: true,
          dismiss: (body, onSaved) =>
            dismissQc.mutate(body, {
              onSuccess: () => {
                showSuccess(qcDismissedMessage(body.reason));
                onSaved?.();
              },
              onError: dismissFailed,
            }),
          dismissing: dismissQc.isPending,
          canDismissBlocking: qc.can_override === true,
          restore: (dismissalId) =>
            restoreQc.mutate(dismissalId, {
              onSuccess: () => showSuccess("Uwaga przywrócona — QC przeliczone."),
              onError: restoreFailed,
            }),
          restoring: restoreQc.isPending,
        }
      : null;

  const dismissedEntries: DismissedEntry[] = [
    ...(ctx ? qcDismissedEntries(checks, ctx) : []),
    ...(issuesQuery.data?.dismissed ?? []).map((issue) => ({
      id: `${issue.source}:${issue.dismissal.id}`,
      title: issue.text,
      context:
        issue.source === "generator"
          ? "Uwaga generatora"
          : `Kontrola AI · ${REVIEW_FINDING_LABEL[issue.status ?? ""] ?? "do sprawdzenia"}`,
      dismissal: issue.dismissal,
      onRestore: () =>
        restoreIssue.mutate(issue.dismissal.id, {
          onSuccess: () => showSuccess("Uwaga przywrócona."),
          onError: restoreFailed,
        }),
    })),
  ];

  // Wyciszone w „Jakość QC” (QC często się przy nich myli) nie wchodzą do „Popraw wszystkie”.
  const plan = useMemo(() => bulkPlan(checks.filter((check) => !check.muted), visibleFixes), [checks, visibleFixes]);
  const classified = useMemo(() => classifyCvWarnings(warnings), [warnings]);
  // Jedna lista: QC, generator i kontrola AI po sekcjach CV (miejsca liczone na bieżącej treści).
  const list = useMemo(
    () =>
      buildIssueList({
        doc: editor.isDestroyed ? null : editor.state.doc,
        checks,
        warnings,
        findings: presentFindings,
      }),
    // `docTick` = treść się zmieniła.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editor, checks, warnings, presentFindings, docTick],
  );
  const total = list.total;
  const anyBlocking = checks.some((check) => check.status === "fail" && check.severity === "blocking");
  const blocking = qc && !otherDocument ? qc.blocking_failed : 0;
  const countState: CvIssueCount["state"] = !hasStage || qc ? "ready" : qcQuery.isError ? "failed" : "loading";
  const countQc = qc && !otherDocument ? qc : null;
  useEffect(() => {
    onCount?.({ total, blocking, state: countState, qc: countQc });
  }, [onCount, total, blocking, countState, countQc]);
  // Ta sama droga co „Pogrub wszystkie” przy sprawdzeniu: serwer liczy na treści
  // z edytora, edytor nakłada wynik jednym cofalnym krokiem.
  useImperativeHandle(ref, () => ({
    boldRequirements: () => {
      if (readOnly) return;
      const { actions } = boldRequirements(checks);
      if (actions.length > 0) void run(actions, false, "Pogrubiono wymagania klienta.");
    },
  }));

  // „Cofnij” przy ostatniej poprawce — dopóki nic nie zmieniono po niej (jak w asystencie).
  const latest = applied[0] ?? null;
  const canUndo = latest != null && !editor.isDestroyed && editor.state.doc === latest.after;
  const undoLatest = () => {
    if (!latest || !canUndo) return;
    editor.commands.undo();
    setApplied((list) => list.filter((entry) => entry.id !== latest.id));
    showSuccess(latest.labels.length > 1 ? "Cofnięto poprawki." : "Cofnięto poprawkę.");
  };

  if (!hasStage) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <header className="border-b border-border px-3 py-2">
          <h2 className="text-sm font-semibold">Do poprawy</h2>
          <p className="text-xs text-muted-foreground">
            To CV nie jest jeszcze na etapie rekrutacji — QC i kontrola AI pojawią się po podpięciu go do kandydata.
          </p>
        </header>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
          {classified.review.length + classified.info.length === 0 ? (
            <p className="text-sm text-muted-foreground">Generator nie zgłosił uwag do tego CV.</p>
          ) : (
            <GeneratorWarnings warnings={warnings} />
          )}
        </div>
      </div>
    );
  }

  const qcFailed = qcQuery.isError && !qc;
  const reviewVersion = review?.version ?? null;
  const goneFindings = allFindings.length - presentFindings.length;
  const hasInfo =
    review?.status === "unverified" ||
    goneFindings > 0 ||
    list.covered.length > 0 ||
    list.info.length > 0 ||
    list.gaps.length > 0 ||
    (ctx != null && (list.muted.length > 0 || (qc?.confirmations?.length ?? 0) > 0));
  const fixesState: RowContext["fixesState"] =
    fixesQuery.isError || fixes?.status === "unavailable" ? "failed" : hasAiGaps && !fixes ? "loading" : "ready";
  const rows = issueRows(list, visibleFixes, fixesState === "loading");
  const rowCtx: RowContext = {
    qc: ctx,
    locate,
    applyFix: (fix, text) =>
      ctx?.apply(
        text ? { action: "ai_fix", fix_id: fix.id, text } : { action: "ai_fix", fix_id: fix.id },
        "Zdanie dopisane do CV.",
        // Własny tekst nie jest równy propozycji — znika z listy po zastosowaniu.
        text ? () => setDismissed((prev) => new Set(prev).add(fix.id)) : undefined,
      ),
    rejectFix: (id) => setDismissed((prev) => new Set(prev).add(id)),
    fixesState,
    retryFixes: () => void fixesQuery.refetch(),
    dismiss: issueDismiss,
    reviewVersion,
    refreshQc: () => void refetchQc(),
  };
  const rowView = (row: IssueRow) => <IssueRowView key={row.id} row={row} ctx={rowCtx} />;
  // „Popraw wszystkie” stoi w nagłówku grupy, w której są poprawki z planu:
  // zwykle „Do poprawy”, a gdy są tylko zdania AI do blokad — „Blokuje wysyłkę”.
  const bulkHost =
    !ctx || plan.actions.length === 0
      ? null
      : rows.fixable.some(rowInBulk) || !rows.blocking.some(rowInBulk)
        ? "fixable"
        : "blocking";
  const bulkButton = (
    <Button
      size="sm"
      className="h-7 px-2 text-xs"
      disabled={working || readOnly}
      title={`Jednym kliknięciem: ${plan.parts.join(", ")}. Usunięcie treści i własne poprawki zatwierdzasz pojedynczo.`}
      onClick={() => void run(plan.actions, true, "Poprawki nałożone — jedno Ctrl+Z cofa wszystkie.")}
    >
      {working ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Wand2 className="size-3.5" aria-hidden />}
      Popraw wszystkie ({plan.actions.length})
    </Button>
  );
  const appliedCount = applied.reduce((sum, entry) => sum + entry.labels.length, 0);
  const status = qcQuery.isFetching
    ? "Sprawdzam zapisaną treść…"
    : unsaved
      ? "Lista dotyczy ostatnio zapisanej treści — odświeży się po zapisie."
      : null;
  const blockingBadge = ctx ? (
    blocking > 0 ? (
      <Badge variant="danger" size="sm">
        {countForm(blocking, ["blokuje wysyłkę", "blokują wysyłkę", "blokuje wysyłkę"])}
      </Badge>
    ) : (
      <Badge variant="success" size="sm">
        Nic nie blokuje wysyłki
      </Badge>
    )
  ) : null;

  if (summary) {
    // Asystent rozwinięty: pasek z liczbami, lista wraca po „Lista”.
    const rest = Math.max(0, total - blocking);
    return (
      <div className="flex items-center gap-1.5 border-b border-border px-3 py-2" role="group" aria-label="Do poprawy">
        <h2 className="shrink-0 text-sm font-semibold">Do poprawy</h2>
        {/* Krótko — pasek dzieli wiersz z „Pokaż listę” w kolumnie 360 px. */}
        {ctx ? (
          blocking > 0 ? (
            <Badge variant="danger" size="sm" title="Tyle rzeczy zatrzymuje wysyłkę CV">
              {countForm(blocking, ["blokuje", "blokują", "blokuje"])}
            </Badge>
          ) : (
            <Badge variant="success" size="sm">
              nic nie blokuje
            </Badge>
          )
        ) : null}
        {rest > 0 ? (
          <Badge variant="outline" size="sm">
            {rest} do decyzji
          </Badge>
        ) : null}
        {qcQuery.isFetching ? <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-label="Sprawdzam" /> : null}
        <Button size="sm" variant="ghost" className="ml-auto h-7 shrink-0 px-2 text-xs" onClick={onShowList}>
          Pokaż listę
          <ChevronDown className="size-3.5" aria-hidden />
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="space-y-1 border-b border-border px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold">Do poprawy</h2>
          {blockingBadge}
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            aria-label="Sprawdź ponownie"
            disabled={qcQuery.isFetching}
            onClick={() => {
              void qcQuery.refetch();
              void issuesQuery.refetch();
            }}
          >
            {qcQuery.isFetching ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="size-3.5" aria-hidden />
            )}
          </Button>
        </div>
        {status ? (
          <p role="status" className="text-xs text-muted-foreground">
            {status}
          </p>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {qcQuery.isLoading ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Sprawdzam CV…
          </p>
        ) : null}
        {qcFailed ? (
          <div role="alert" className="space-y-2 rounded-lg border border-border px-3 py-2 text-sm text-muted-foreground">
            <p>
              {isForbiddenError(qcQuery.error)
                ? "Nie masz dostępu do QC tej rekrutacji."
                : "Nie udało się policzyć QC — to nie znaczy, że CV jest bez uwag."}
            </p>
            {isForbiddenError(qcQuery.error) ? null : (
              <Button size="sm" variant="outline" onClick={() => void qcQuery.refetch()}>
                Ponów
              </Button>
            )}
          </div>
        ) : null}
        {qc && qcQuery.isError ? (
          <p role="alert" className="rounded-md bg-destructive-muted px-3 py-2 text-xs text-destructive-muted-foreground">
            Nie udało się przeliczyć QC ponownie — widzisz poprzedni wynik.
          </p>
        ) : null}
        {otherDocument ? (
          <p role="status" className="rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
            QC tej rekrutacji sprawdza inne CV tej osoby (zatwierdzone na innym etapie), więc jego lista nie dotyczy
            treści otwartej tutaj. Wynik zobaczysz w oknie QC na Tablicy.
          </p>
        ) : null}
        {otherDocument ? null : <QcWordFileNote cv={qc?.cv} />}
        {issuesQuery.isError ? (
          <p role="alert" className="rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground">
            Nie udało się wczytać uwag generatora i kontroli AI.{" "}
            <button type="button" className="font-medium text-primary hover:underline" onClick={() => void issuesQuery.refetch()}>
              Ponów
            </button>
          </p>
        ) : null}
        {ctx && !anyBlocking ? (
          <p role="status" className="flex items-center gap-2 rounded-lg border border-success/30 bg-success-muted px-3 py-2 text-sm text-success-muted-foreground">
            <CheckCircle2 className="size-4 shrink-0" aria-hidden />
            Nic nie blokuje wysyłki tego CV.
          </p>
        ) : null}

        {rows.blocking.length > 0 ? (
          <IssueGroup
            label="Blokuje wysyłkę"
            count={rows.blocking.length}
            tone="blocking"
            action={
              bulkHost === "blocking" || onOverride ? (
                <>
                  {bulkHost === "blocking" ? bulkButton : null}
                  {onOverride ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-xs"
                      disabled={overrideDisabled}
                      onClick={onOverride}
                    >
                      Przekaż mimo uwag…
                    </Button>
                  ) : null}
                </>
              ) : null
            }
          >
            <ul className="space-y-1.5">{rows.blocking.map(rowView)}</ul>
          </IssueGroup>
        ) : null}
        {rows.fixable.length > 0 || bulkHost === "fixable" ? (
          <IssueGroup label="Do poprawy" count={rows.fixable.length} action={bulkHost === "fixable" ? bulkButton : null}>
            {rows.fixable.length > 0 ? <ul className={ROWS}>{rows.fixable.map(rowView)}</ul> : null}
          </IssueGroup>
        ) : null}
        {applied.length > 0 ? (
          <IssueGroup
            label="Poprawione"
            count={appliedCount}
            action={
              canUndo && latest?.bulk ? (
                <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={undoLatest}>
                  <Undo2 className="size-3.5" aria-hidden />
                  Cofnij wszystkie
                </Button>
              ) : null
            }
          >
            <ul className={ROWS}>
              {applied.flatMap((entry) => [
                ...entry.labels.map((label, index) => (
                  <li key={`${entry.id}:${index}`} className="flex items-center gap-2 px-2.5 py-1.5 text-sm text-muted-foreground">
                    <Check className="size-3.5 shrink-0 text-success" aria-hidden />
                    <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{label}</span>
                    {entry === latest && canUndo && !entry.bulk && index === 0 ? (
                      <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={undoLatest}>
                        Cofnij
                      </Button>
                    ) : null}
                  </li>
                )),
                ...entry.skipped.map((item, index) => (
                  <li key={`${entry.id}:skip:${index}`} className="px-2.5 py-1.5 text-xs text-muted-foreground">
                    Pominięto: {item.message}
                  </li>
                )),
              ])}
            </ul>
          </IssueGroup>
        ) : null}
        {rows.decide.length > 0 ? (
          <IssueGroup label="Do decyzji · nie blokuje" count={rows.decide.length}>
            <ul className={ROWS}>{rows.decide.map(rowView)}</ul>
          </IssueGroup>
        ) : null}

        <DismissedSection entries={dismissedEntries} restoring={restoreQc.isPending || restoreIssue.isPending} />
        {hasInfo ? (
          <section aria-label="Informacje" className="space-y-2">
            <h3 className={SECTION_TITLE}>Informacje</h3>
            {review?.status === "unverified" ? (
              <p className="text-xs text-muted-foreground">
                Kontrola AI nie wykonała się dla zatwierdzonej wersji — sprawdź treść ręcznie. Uruchomi się ponownie po
                „Zapisz”.
              </p>
            ) : null}
            {goneFindings > 0 ? (
              <p className="text-xs text-muted-foreground">
                {countForm(goneFindings, [
                  "uwaga kontroli AI dotyczyła linii, której",
                  "uwagi kontroli AI dotyczyły linii, których",
                  "uwag kontroli AI dotyczyło linii, których",
                ])}{" "}
                już nie ma w CV.
              </p>
            ) : null}
            {list.covered.length > 0 ? (
              <p className="text-xs text-muted-foreground">
                {countForm(list.covered.length, [
                  "uwaga generatora o brakującym wymaganiu stoi",
                  "uwagi generatora o brakujących wymaganiach stoją",
                  "uwag generatora o brakujących wymaganiach stoi",
                ])}{" "}
                przy pozycji QC o tym samym wymaganiu.
              </p>
            ) : null}
            <CandidateGaps items={list.gaps} />
            {ctx ? <MutedChecks checks={list.muted} ctx={ctx} /> : null}
            <GeneratorInfo items={list.info} />
            {ctx ? <Confirmations items={qc?.confirmations ?? []} /> : null}
          </section>
        ) : null}
        {ctx ? <PassedChecks passed={list.passed} skipped={list.skipped} ctx={ctx} /> : null}
      </div>
    </div>
  );
}

/** Ramka wierszy grupy „Do poprawy”, „Poprawione” i „Do decyzji”. */
const ROWS = "divide-y divide-border rounded-lg border border-border";

/** Grupa listy: nazwa z liczbą i przycisk grupy po prawej. */
function IssueGroup({
  label,
  count,
  tone = "plain",
  action,
  children,
}: {
  label: string;
  count: number;
  tone?: "blocking" | "plain";
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-label={label} className="space-y-1.5">
      <h3
        className={cn(
          "flex min-h-7 flex-wrap items-center gap-x-2 gap-y-1 text-xs font-semibold uppercase tracking-wider",
          tone === "blocking" ? "text-destructive" : "text-muted-foreground",
        )}
      >
        <span>
          {label} · {count}
        </span>
        {action ? <span className="ml-auto flex flex-wrap gap-1 normal-case tracking-normal">{action}</span> : null}
      </h3>
      {children}
    </section>
  );
}
