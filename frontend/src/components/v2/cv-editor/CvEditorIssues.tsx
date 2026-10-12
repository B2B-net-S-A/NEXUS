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
 * Panel nie ma obejścia QC ani ruchu karty — to zostaje w oknie QC. Edytor
 * wyniku generatora (bez etapu) pokazuje tylko uwagi generatora: QC nie widzi
 * jego edycji.
 */

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Editor } from "@tiptap/core";
import { CheckCircle2, ChevronRight, Loader2, LocateFixed, RefreshCw, Undo2, Wand2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AiFixesView,
  CheckRow,
  Confirmations,
  PassedChecks,
  SECTION_TITLE,
  TaskCard,
  type ActionContext,
} from "@/components/v2/recruitment/cv-qc-cards";
import { apiErrorMessage } from "@/lib/api-error";
import {
  cvEditorIssuesQueryKey,
  cvEditorQcQueryKey,
  networkIssuesApi,
  type CvEditorIssuesApi,
  type CvEditorIssuesData,
  type CvReviewFinding,
} from "@/lib/api/cvEditorIssues";
import {
  cvQcFixesQueryKey,
  cvQcQueryKey,
  invalidateAfterQcChange,
  type QcFix,
  type QcFixAction,
  type QcFixesResponse,
  type QcResult,
  type QcTransformSkipped,
} from "@/lib/api/cvQc";
import { copyTextToClipboard } from "@/lib/clipboard";
import { clearIssueFocus, setIssueMarks, showIssueInCv } from "@/lib/cv-editor-issue-marks";
import {
  REVIEW_FINDING_LABEL,
  bulkPlan,
  findingsInCv,
  fixAlreadyInCv,
  fixStep,
  issueMarks,
  locateTarget,
  type IssueRange,
} from "@/lib/cv-editor-issues";
import { classifyCvWarnings } from "@/lib/cv-generator";
import { candidateQuestion, countForm, splitChecks, type IssueTarget } from "@/lib/cv-qc";
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

interface BulkOutcome {
  applied: number;
  skipped: QcTransformSkipped[];
}

function GeneratorWarnings({ warnings }: { warnings: readonly string[] }) {
  const infoId = useId();
  const [infoOpen, setInfoOpen] = useState(false);
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
              <p className="[overflow-wrap:anywhere]">{item.text}</p>
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
                  {item.text}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function ReviewFindings({
  review,
  present,
  onLocate,
}: {
  review: CvEditorIssuesData["content_review"];
  /** Uwagi, których linia nadal stoi w CV. */
  present: CvReviewFinding[];
  onLocate: (target: IssueTarget) => void;
}) {
  if (review.status == null) return null;
  const version = review.version != null ? ` v${review.version}` : "";
  const gone = review.findings.length - present.length;
  return (
    <section aria-label="Kontrola AI" className="space-y-2">
      <h3 className={SECTION_TITLE}>
        Kontrola AI zatwierdzonej wersji{version} ({present.length})
      </h3>
      {review.status === "unverified" ? (
        <p className="text-xs text-muted-foreground">
          Kontrola AI nie wykonała się dla tej wersji — sprawdź treść ręcznie. Uruchomi się ponownie po „Zapisz”.
        </p>
      ) : present.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {gone > 0
            ? "Linie wskazane przez kontrolę AI zostały już zmienione."
            : "Kontrola AI nie miała uwag do zatwierdzonej wersji."}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {present.map((finding, index) => (
            <li key={`${index}:${finding.text}`} className="space-y-1 rounded-lg border border-warning/30 px-3 py-2 text-sm">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-warning-muted-foreground">
                {REVIEW_FINDING_LABEL[finding.status] ?? "do sprawdzenia"}
              </p>
              <p className="italic [overflow-wrap:anywhere]">„{finding.text}”</p>
              <Button size="sm" variant="ghost" onClick={() => onLocate({ kind: "line", text: finding.text })}>
                <LocateFixed className="size-3.5" aria-hidden />
                Pokaż w CV
              </Button>
            </li>
          ))}
        </ul>
      )}
      {gone > 0 && present.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          {countForm(gone, ["uwaga dotyczyła linii, której", "uwagi dotyczyły linii, których", "uwag dotyczyło linii, których"])} już
          nie ma w CV.
        </p>
      ) : null}
    </section>
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
  const [aiRequested, setAiRequested] = useState(false);
  const fixesQuery = useQuery<QcFixesResponse>({
    queryKey: cvQcFixesQueryKey(stageKey),
    queryFn: () => api.fixes(stageKey),
    enabled: hasStage && aiRequested,
    staleTime: Infinity,
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
  const locate = (target: IssueTarget) => {
    if (editor.isDestroyed) return;
    const range = locateTarget(editor.state.doc, target);
    if (range) flash(range);
    else showError("Tego miejsca nie ma już w treści CV — tekst zmienił się od ostatniego sprawdzenia.");
  };

  // ── Poprawki: serwer liczy, edytor nakłada jednym krokiem ──────────────────
  const [working, setWorking] = useState(false);
  const workingRef = useRef(false);
  const [bulkOutcome, setBulkOutcome] = useState<BulkOutcome | null>(null);
  const bulkDoc = useRef<unknown>(null);

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
      if (bulk) {
        bulkDoc.current = editor.state.doc;
        setBulkOutcome({ applied: result.applied.length, skipped: result.skipped });
      }
      showSuccess(success);
      onApplied?.();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się policzyć poprawki. Spróbuj ponownie."));
    } finally {
      workingRef.current = false;
      setWorking(false);
    }
  };

  const confirm = useMutation({
    mutationFn: (body: { term: string; text?: string }) => api.confirm(stageKey, body),
    onSuccess: (result) => {
      queryClient.setQueryData(cvEditorQcQueryKey(stageKey), result);
      queryClient.setQueryData(cvQcQueryKey(stageKey), result);
      invalidateAfterQcChange(queryClient, result.job_id);
    },
  });

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

  const aiSectionId = `cv-editor-ai-${stageKey}`;
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
          requestAiFixes: () => {
            setAiRequested(true);
            if (typeof document !== "undefined") {
              document.getElementById(aiSectionId)?.scrollIntoView?.({ block: "nearest" });
            }
          },
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
        }
      : null;

  const split = useMemo(() => splitChecks(checks), [checks]);
  const plan = useMemo(() => bulkPlan(checks, visibleFixes), [checks, visibleFixes]);
  const hasAiGaps = checks.some((check) => check.status === "fail" && check.items.some((item) => item.fix === "ai"));
  const classified = useMemo(() => classifyCvWarnings(warnings), [warnings]);
  const total = split.tasks.length + split.notes.length + classified.review.length + presentFindings.length;
  const blocking = qc && !otherDocument ? qc.blocking_failed : 0;
  const countState: CvIssueCount["state"] = !hasStage || qc ? "ready" : qcQuery.isError ? "failed" : "loading";
  useEffect(() => {
    onCount?.({ total, blocking, state: countState });
  }, [onCount, total, blocking, countState]);

  // „Cofnij” przy wyniku „Popraw wszystko” — dopóki nic nie zmieniono po poprawce.
  const canUndoBulk = bulkOutcome != null && !editor.isDestroyed && editor.state.doc === bulkDoc.current;
  const undoBulk = () => {
    editor.commands.undo();
    setBulkOutcome(null);
    showSuccess("Cofnięto poprawki.");
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
  const tasksTitle = qc?.advisory ? "Zalecane poprawki przed wysłaniem" : "Do poprawy przed wysłaniem";
  const status = qcQuery.isFetching
    ? "Sprawdzam zapisaną treść…"
    : unsaved
      ? "Lista dotyczy ostatnio zapisanej treści — odświeży się po zapisie."
      : null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="space-y-1 border-b border-border px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold">Do poprawy</h2>
          {ctx ? (
            blocking > 0 ? (
              <Badge variant="danger" size="sm">
                Blokuje wysyłkę: {blocking}
              </Badge>
            ) : (
              <Badge variant="success" size="sm">
                Nic nie blokuje wysyłki
              </Badge>
            )
          ) : null}
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

        {ctx && plan.actions.length > 0 ? (
          <section aria-label="Popraw wszystko" className="space-y-1.5 rounded-lg border border-primary/30 bg-primary/5 p-3">
            <Button
              size="sm"
              disabled={working || readOnly}
              onClick={() =>
                void run(plan.actions, true, "Poprawki nałożone — jedno Ctrl+Z cofa wszystkie.")
              }
            >
              {working ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Wand2 className="size-3.5" aria-hidden />}
              Popraw wszystko ({plan.actions.length})
            </Button>
            <p className="text-xs text-muted-foreground">
              Jednym kliknięciem: {plan.parts.join(", ")}. Usunięcie treści i własne poprawki zatwierdzasz pojedynczo.
            </p>
          </section>
        ) : null}
        {bulkOutcome ? (
          <section aria-label="Wynik poprawek" className="space-y-1.5 rounded-lg border border-border px-3 py-2 text-xs">
            <p role="status" className="flex flex-wrap items-center gap-2">
              <span>Nałożono: {countForm(bulkOutcome.applied, ["poprawkę", "poprawki", "poprawek"])}.</span>
              {canUndoBulk ? (
                <Button size="sm" variant="outline" onClick={undoBulk}>
                  <Undo2 className="size-3.5" aria-hidden />
                  Cofnij
                </Button>
              ) : null}
            </p>
            {bulkOutcome.skipped.length > 0 ? (
              <ul className="space-y-0.5 text-muted-foreground">
                {bulkOutcome.skipped.map((item, index) => (
                  <li key={index}>Pominięto: {item.message}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}

        {ctx ? (
          split.tasks.length > 0 ? (
            <section aria-label={tasksTitle} className="space-y-2">
              <h3 className={SECTION_TITLE}>
                {tasksTitle} ({split.tasks.length})
              </h3>
              <ul className="space-y-2">
                {split.tasks.map((task) => (
                  <TaskCard key={task.id} task={task} ctx={ctx} />
                ))}
              </ul>
            </section>
          ) : (
            <p role="status" className="flex items-center gap-2 rounded-lg border border-success/30 bg-success-muted px-3 py-2 text-sm text-success-muted-foreground">
              <CheckCircle2 className="size-4 shrink-0" aria-hidden />
              Nic nie blokuje wysyłki tego CV.
            </p>
          )
        ) : null}
        {ctx && hasAiGaps ? (
          <AiFixesView
            sectionId={aiSectionId}
            ctx={ctx}
            data={fixes}
            loading={fixesQuery.isFetching && !fixes}
            failed={fixesQuery.isError}
            visible={visibleFixes}
            onRequest={() => setAiRequested(true)}
            onRetry={() => void fixesQuery.refetch()}
            onApply={(fix, text) =>
              ctx.apply(
                text ? { action: "ai_fix", fix_id: fix.id, text } : { action: "ai_fix", fix_id: fix.id },
                "Zdanie dopisane do CV.",
                // Własny tekst nie jest równy propozycji — znika z listy po zastosowaniu.
                text ? () => setDismissed((prev) => new Set(prev).add(fix.id)) : undefined,
              )
            }
            onDismiss={(id) => setDismissed((prev) => new Set(prev).add(id))}
          />
        ) : null}
        {ctx && split.notes.length > 0 ? (
          <section aria-label="Warto poprawić — nie blokuje" className="space-y-2">
            <h3 className={SECTION_TITLE}>Warto poprawić — nie blokuje ({split.notes.length})</h3>
            <ul className="space-y-2">
              {split.notes.map((check) => (
                <CheckRow key={check.key} check={check} ctx={ctx} />
              ))}
            </ul>
          </section>
        ) : null}

        {issuesQuery.isError ? (
          <p role="alert" className="rounded-lg border border-border px-3 py-2 text-xs text-muted-foreground">
            Nie udało się wczytać uwag generatora i kontroli AI.{" "}
            <button type="button" className="font-medium text-primary hover:underline" onClick={() => void issuesQuery.refetch()}>
              Ponów
            </button>
          </p>
        ) : null}
        <GeneratorWarnings warnings={warnings} />
        {review ? <ReviewFindings review={review} present={presentFindings} onLocate={locate} /> : null}

        {ctx ? <Confirmations items={qc?.confirmations ?? []} /> : null}
        {ctx ? <PassedChecks passed={split.passed} skipped={split.skipped} ctx={ctx} /> : null}
      </div>
    </div>
  );
}
