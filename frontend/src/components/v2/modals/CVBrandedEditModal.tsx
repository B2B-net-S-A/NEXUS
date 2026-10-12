"use client";

/**
 * CVBrandedEditModal — edytor CV do klienta (Tiptap + autosave), na cały ekran.
 *
 * Dwa miejsca, jeden edytor: CV etapu rekrutacji (`stageId`, karta „CV do
 * klienta”, dok kanbana, profil kandydata) i wynik generatora (`generatedId`,
 * „Moje CV”).
 *
 * Od generatora CV v3 edytor ma JEDEN przycisk „Zapisz”: zapisuje szkic,
 * zamyka okno, a zatwierdzenie (kontrola AI treści + nowa wersja) idzie
 * w tle przez `lib/cv-background-approval.ts`. Wynik kontroli przychodzi
 * toastem. Nie ma już okna „Sfinalizować?” ani osobnego kroku „Zatwierdź”.
 *
 * Zatwierdzona wersja jest edytowalna: pierwsza zmiana zakłada nowy szkic
 * (`new-draft`), a wpisany tekst przechodzi do niego. Istniejące linki
 * i pobrania zachowują treść poprzedniej wersji.
 *
 * Etap bez CV (`status: "none"`) nie ma już treści ze starego szablonu —
 * edytor mówi „Najpierw wygeneruj CV” i odsyła do generatora.
 *
 * Edytor CV 2 (12.10.2026, decyzje D1 i D3): okno na cały ekran, kartka
 * w układzie szablonu Worda (`.cv-paper` w `globals.css`), pasek narzędzi
 * z blokami CV (`cv-editor/CvEditorToolbar`), źródła obok
 * (`cv-editor/CvEditorSources`), „Podgląd Word” z bieżącej treści i stała
 * klauzula zgody (`lib/cv-editor-structure.ts`). Logika sesji, zapisu
 * i zatwierdzenia została bez zmian.
 *
 * PR 2: po prawej panel „Do poprawy” (`cv-editor/CvEditorIssues`) — QC, uwagi
 * generatora i kontrola AI przy tekście. Panel jest zamontowany także wtedy,
 * gdy go nie widać: liczy znaczniki na kartce i licznik w pasku. Przy
 * szerokości 1180–1539 px (laptop 1280) obok kartki mieści się JEDEN panel —
 * źródła albo „Do poprawy”; od 1540 px oba.
 */

import { useState, useEffect, useRef, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEditor, EditorContent } from "@tiptap/react";
import {
  ListChecks,
  Loader2,
  PanelLeft,
  Printer,
  Download,
  RefreshCcw,
  Save,
  Sparkles,
  AlertCircle,
} from "lucide-react";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CvDraftSession, type CvSaveState } from "@/lib/cv-draft-session";
import { useToast } from "@/components/Toast";
import {
  CvEditorSources,
  type CvEditorSourceContext,
  type CvEditorSourcesProps,
} from "@/components/v2/cv-editor/CvEditorSources";
import { CvEditorIssues, type CvIssueCount } from "@/components/v2/cv-editor/CvEditorIssues";
import { CvEditorToolbar } from "@/components/v2/cv-editor/CvEditorToolbar";
import { CvEditorWordPreview } from "@/components/v2/cv-editor/CvEditorWordPreview";
import { keepDialogOpenOnDocumentSearchEscape } from "@/components/v2/files/DocumentSearchBar";
import {
  openAuthenticatedFile,
  downloadAuthenticatedFile,
  fetchAuthenticatedBlob,
  postAuthenticatedDownload,
  downloadBlob,
  type AuthenticatedDownload,
} from "@/lib/authenticated-files";
import {
  candidateStageCvApi,
  cvGeneratedEditorApi,
  type CVBrandedState,
} from "@/lib/api";
import type { CvEditorIssuesApi } from "@/lib/api/cvEditorIssues";
import {
  generatedApprovalKey,
  stageApprovalKey,
  startBackgroundApproval,
} from "@/lib/cv-background-approval";
import { withDownloadIntent } from "@/lib/cv-download-intent";
import { cvPlaceholders, type CvLang } from "@/lib/cv-editor-blocks";
import { cvEditorExtensions, loadCvHtml } from "@/lib/cv-editor-structure";
import { useElementWidth } from "@/lib/use-element-width";
import { cn } from "@/lib/utils";

/** Od tej szerokości okna (px) panel stoi obok kartki; węziej — przełącznik. */
const SIDE_BY_SIDE_MIN_WIDTH = 1180;
/** Od tej szerokości mieszczą się oba panele: źródła (440) + kartka (794) + „Do poprawy” (360). */
const BOTH_PANELS_MIN_WIDTH = 1540;

const NO_ISSUES: CvIssueCount = { total: 0, blocking: 0, state: "loading" };

type CvDraftPayload = { content_html: string; expected_revision: number };

/** Pliki edytora. Harness podaje wersję z pamięci — podgląd `/preview/*` nie ma sieci. */
export interface CvEditorFiles {
  /** Word z bieżącej treści szkicu: do pobrania albo do „Podglądu Word”. */
  draftDocx: (payload: CvDraftPayload, purpose: "download" | "preview") => Promise<AuthenticatedDownload>;
  downloadApproved: (version: number, filename: string) => Promise<void>;
  previewApproved: (version: number) => Promise<Blob>;
  print: () => Promise<void>;
}

/** Stan i zapis edytora — te same cztery operacje dla CV etapu i wyniku generatora. */
export type CvEditorApi = Pick<
  typeof candidateStageCvApi.branded,
  "get" | "update" | "newDraft" | "finalize"
>;

function networkFiles(basePath: string): CvEditorFiles {
  return {
    draftDocx: (payload, purpose) =>
      postAuthenticatedDownload(
        purpose === "download"
          ? withDownloadIntent(`${basePath}/preview-docx`, "editor")
          : `${basePath}/preview-docx`,
        payload,
      ),
    downloadApproved: (version, filename) =>
      downloadAuthenticatedFile(
        withDownloadIntent(`${basePath}/versions/${version}/docx`, "editor"),
        filename,
      ),
    previewApproved: (version) => fetchAuthenticatedBlob(`${basePath}/versions/${version}/docx`),
    // Print view is Bearer-guarded — a raw window.open sends no Authorization
    // header and lands on a white "Not authenticated" page. Fetch the HTML with
    // auth and open it as a same-origin blob URL (its inline window.print() runs).
    print: () =>
      openAuthenticatedFile(withDownloadIntent(`${basePath}/render-pdf`, "editor"), "text/html"),
  };
}

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Otwiera generator (np. etap bez CV albo CV bez źródeł do edycji). */
  onRegenerate?: () => void;

  candidateName: string;
  jobTitle?: string;
  /**
   * Kandydat i rekrutacja dla panelu źródeł, gdy edytor nie zna etapu (wynik
   * generatora). `null` = CV bez rekrutacji. CV etapu ustala parę samo.
   */
  sourceContext?: CvEditorSourceContext | null;
  /** Harness: stan, zapis i pliki z pamięci zamiast sieci. */
  editorApi?: CvEditorApi;
  editorFiles?: CvEditorFiles;
  sourceLoaders?: CvEditorSourcesProps["loaders"];
  /**
   * Uwagi generatora dla CV bez etapu (wynik generatora) — panel „Do poprawy”
   * pokazuje tam tylko je. Bez nich edytor wyniku generatora nie ma panelu.
   */
  generatorWarnings?: readonly string[];
  /** Harness: QC, uwagi i poprawki z pamięci zamiast sieci. */
  issuesApi?: CvEditorIssuesApi;
} & ({ stageId: number; generatedId?: never } | { generatedId: number; stageId?: never });

function getErrorMessage(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") return detail.message;
  return typeof detail === "string" ? detail : e instanceof Error ? e.message : "Nie udało się wykonać operacji";
}

const MANUAL_FIELD_LABELS: Record<string, string> = {
  generator_instructions: "instrukcje klienta",
  generator_instructions_en: "instrukcje klienta dla wersji angielskiej",
  notes: "uwagi klienta",
  date_format: "format dat",
  glossary: "tłumaczenia",
  highlight_policy: "zasady pogrubień",
  highlight_terms: "wyróżnione słowa",
  max_bullets_per_role: "liczbę obowiązków w opisach stanowisk",
  max_bullet_chars: "długość opisów obowiązków",
};

/** Przełącznik widoku w pasku: aktywny w kolorze akcentu, jak zakładki. */
function ViewToggle({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <Button
      size="sm"
      variant="ghost"
      aria-pressed={active}
      className={cn(active && "bg-primary/10 text-primary hover:bg-primary/10")}
      onClick={onClick}
    >
      {children}
    </Button>
  );
}

export function CVBrandedEditModal(props: Props) {
  return <CVBrandedEditContent key={props.generatedId !== undefined ? `generated-${props.generatedId}` : `stage-${props.stageId}`} {...props} />;
}

function CVBrandedEditContent({
  open,
  onOpenChange,
  onRegenerate,
  stageId: pipelineStageId,
  generatedId,
  candidateName,
  jobTitle,
  sourceContext,
  editorApi: editorApiOverride,
  editorFiles,
  sourceLoaders,
  generatorWarnings,
  issuesApi,
}: Props) {
  const stageId = (generatedId ?? pipelineStageId)!;
  const isGenerated = generatedId !== undefined;
  const scopeKey = isGenerated ? "cv-generated-editor" : "cv-branded";
  const editorApi: CvEditorApi =
    editorApiOverride ?? (isGenerated ? cvGeneratedEditorApi : candidateStageCvApi.branded);
  const basePath = isGenerated ? `/api/cv-generator/generated/${generatedId}/editor` : `/api/candidates/stages/${stageId}/cv/branded`;
  const files = editorFiles ?? networkFiles(basePath);
  const approvalKey = isGenerated ? generatedApprovalKey(stageId) : stageApprovalKey(stageId);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  // Trwały błąd zapisu (409 — ktoś zapisał nowszą wersję, 422 — puste CV).
  // Zamknięcie edytora = udany zapis, więc bez tej ścieżki okna nie dało się
  // zamknąć wcale: każde „Zamknij" kończyło się tym samym błędem.
  const [saveProblem, setSaveProblem] = useState<{message: string; conflict: boolean} | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // Pola w nawiasach z nowo wstawionych bloków, które zatrzymały „Zapisz”.
  const [unfilled, setUnfilled] = useState<string[]>([]);
  const [mode, setMode] = useState<"edit" | "word">("edit");
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const [issuesOpen, setIssuesOpen] = useState(false);
  // Który panel wygrywa, gdy obok kartki mieści się tylko jeden.
  const [lastSide, setLastSide] = useState<"sources" | "issues">("sources");
  const sideTouched = useRef(false);
  const [issueCount, setIssueCount] = useState<CvIssueCount>(NO_ISSUES);
  const [narrowPane, setNarrowPane] = useState<"cv" | "sources" | "issues">("cv");
  const [body, setBody] = useState<HTMLElement | null>(null);
  const bodyWidth = useElementWidth(body);
  const sideBySide = bodyWidth >= SIDE_BY_SIDE_MIN_WIDTH;
  const bothPanels = bodyWidth >= BOTH_PANELS_MIN_WIDTH;

  // Są uwagi albo QC nie odpowiada — panel „Do poprawy” otwiera się sam, raz;
  // potem decyduje człowiek. Awaria QC schowana w zamkniętym panelu wyglądałaby
  // jak CV bez uwag.
  const issuesNeedAttention =
    issueCount.state === "failed" || (issueCount.state === "ready" && issueCount.total > 0);
  useEffect(() => {
    if (sideTouched.current || !issuesNeedAttention) return;
    sideTouched.current = true;
    setIssuesOpen(true);
    setLastSide("issues");
  }, [issuesNeedAttention]);

  const { data, isLoading, error: loadError, refetch, isFetching } = useQuery<CVBrandedState>({
    queryKey: [scopeKey, stageId],
    queryFn: () => editorApi.get(stageId).then((r) => r.data),
    enabled: open,
  });
  // Etap bez CV: backend nie składa już treści ze starego szablonu.
  const noCv = data?.status === "none";

  const editor = useEditor({
    immediatelyRender: false,
    extensions: cvEditorExtensions(),
    content: "",
    editorProps: { attributes: { "aria-label": "Treść CV" } },
  });

  // Async callbacks (nowy szkic, ponowne wczytanie) mogą wrócić po zamknięciu
  // okna — wtedy `useEditor` zdążył już zniszczyć edytor, a `editor.commands`
  // na zniszczonym edytorze rzuca TypeError.
  const liveEditor = () => (editor && !editor.isDestroyed ? editor : null);

  const sessionRef = useRef<CvDraftSession | null>(null);
  const loadedStage = useRef<number | null>(null);
  const [saveState, setSaveState] = useState<CvSaveState>("saved");
  // Nowy szkic z zatwierdzonej wersji — zakładany przy PIERWSZEJ zmianie.
  const newDraftRef = useRef<Promise<void> | null>(null);
  const [creatingDraft, setCreatingDraft] = useState(false);

  const loadState = (state: CVBrandedState) => {
    const session = new CvDraftSession(state.content_html ?? "<p></p>", state.edit_revision,
      state.status === "finalized", {
        save: (html, revision) => editorApi.update(stageId, {
          content_html: html, expected_revision: revision,
        }).then((r) => { queryClient.setQueryData([scopeKey, stageId], r.data); return r.data; }),
        // Zatwierdzenie nie idzie przez sesję — robi je `cv-background-approval`
        // po zamknięciu okna.
        finalize: () => Promise.reject(new Error("Zatwierdzenie CV idzie w tle po zapisie.")),
      }, (status) => {
        if (sessionRef.current === session) setSaveState(status);
      });
    sessionRef.current = session;
    loadedStage.current = stageId;
    setSaveState(session.state);
    const live = liveEditor();
    if (live) loadCvHtml(live, session.html);
    queryClient.setQueryData([scopeKey, stageId], state);
  };

  useEffect(() => {
    if (!editor || !data) return;
    if (loadedStage.current === stageId) {
      const session = sessionRef.current;
      if (!session || session.state !== "saved" || data.edit_revision <= session.revision) return;
    }
    loadState(data);
    // Remote refetches must not replace locally edited content.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, data, stageId]);

  useEffect(() => {
    // Bez zgłaszania „update”: Tiptap domyślnie zgłasza je przy każdej zmianie
    // trybu edycji, a dla okna to znaczy „treść się zmieniła”. „Zapisz” na
    // zatwierdzonym CV bez żadnej poprawki zakładało przez to nowy szkic.
    editor?.setEditable(!noCv && !submitting, false);
  }, [editor, noCv, submitting]);

  const startNewDraft = () => {
    const session = sessionRef.current;
    if (!session || newDraftRef.current) return;
    setCreatingDraft(true);
    newDraftRef.current = editorApi.newDraft(stageId, session.revision)
      .then((response) => {
        // Tekst wpisany w zatwierdzoną wersję przechodzi do nowego szkicu.
        const typed = liveEditor()?.getHTML() ?? null;
        loadState(response.data);
        const current = liveEditor();
        if (current && typed != null && typed !== sessionRef.current?.html) {
          loadCvHtml(current, typed);
          sessionRef.current?.edit(typed);
        }
      })
      .catch((error: unknown) => {
        showError(`Nie udało się utworzyć nowej wersji: ${getErrorMessage(error)}`);
        // Zmiana nie trafiła do żadnego szkicu — wracamy do zatwierdzonej treści.
        const current = liveEditor();
        if (sessionRef.current && current) loadCvHtml(current, sessionRef.current.html);
      })
      .finally(() => {
        newDraftRef.current = null;
        setCreatingDraft(false);
      });
  };
  const startNewDraftRef = useRef(startNewDraft);
  startNewDraftRef.current = startNewDraft;

  /**
   * Poprawka z panelu „Do poprawy” na zatwierdzonej wersji: najpierw szkic,
   * potem zmiana. Wczytanie szkicu jest poza historią cofania, więc poprawka
   * nałożona przed nim nie dałaby się cofnąć.
   */
  const ensureDraft = async (): Promise<boolean> => {
    if (sessionRef.current?.state === "finalized") startNewDraft();
    if (newDraftRef.current) await newDraftRef.current;
    const session = sessionRef.current;
    return !!session && session.state !== "finalized";
  };

  useEffect(() => {
    if (!editor) return;
    const handler = () => {
      const session = sessionRef.current;
      if (!session) return;
      setUnfilled([]);
      if (session.state === "finalized") {
        startNewDraftRef.current();
        return;
      }
      session.edit(editor.getHTML());
    };
    editor.on("update", handler);
    return () => { editor.off("update", handler); };
  }, [editor]);

  const reportSaveProblem = (error: unknown) => {
    const status = (error as {response?: {status?: unknown}} | null)?.response?.status;
    setSaveProblem({message: getErrorMessage(error), conflict: status === 409});
    showError(getErrorMessage(error));
  };
  const saveCurrent = async () => {
    try { await sessionRef.current?.save(); setSaveProblem(null); }
    catch (error) { reportSaveProblem(error); }
  };
  const flush = async () => {
    if (newDraftRef.current) await newDraftRef.current;
    const session = sessionRef.current;
    await session?.settle();
    await session?.save();
    while (session?.state === "unsaved") await session.save();
  };
  const reloadCurrentVersion = async () => {
    setReloading(true);
    try {
      const fresh = await refetch();
      if (!fresh.data) throw fresh.error ?? new Error("Nie udało się wczytać aktualnej wersji CV");
      loadState(fresh.data);
      setSaveProblem(null);
      showSuccess("Wczytano aktualną wersję CV");
    } catch (error) { showError(getErrorMessage(error)); }
    finally { setReloading(false); }
  };
  useEffect(() => {
    if (!open) return;
    const id = setInterval(() => {
      if (sessionRef.current?.state === "unsaved") void saveCurrent();
    }, 2000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, stageId]);

  /** Zamknięcie bez zatwierdzenia — szkic zostaje zapisany. */
  const closeEditor = async (nextOpen: boolean) => {
    if (nextOpen) { onOpenChange(true); return true; }
    if (submitting) return false;
    try {
      await flush();
      setSaveProblem(null);
      onOpenChange(false);
      return true;
    } catch (error) { reportSaveProblem(error); return false; }
  };

  /**
   * „Zapisz”: zapis szkicu → zamknięcie okna → zatwierdzenie w tle. Niczego
   * nie zmienione w zatwierdzonej wersji = samo zamknięcie.
   */
  const saveAndApprove = async () => {
    const session = sessionRef.current;
    if (!session || submitting) return;
    setSubmitting(true);
    try {
      await flush();
    } catch (error) {
      reportSaveProblem(error);
      setSubmitting(false);
      return;
    }
    setSaveProblem(null);
    const current = sessionRef.current ?? session;
    if (current.state === "finalized") {
      setSubmitting(false);
      onOpenChange(false);
      return;
    }
    // Nowe bloki mają pola w nawiasach kwadratowych. Szkic z nimi zapisuje
    // się normalnie, ale do zatwierdzenia (i do klienta) nie mogą pójść.
    const missing = cvPlaceholders(current.html);
    if (missing.length > 0) {
      setUnfilled(missing);
      setSubmitting(false);
      return;
    }
    const payload = { content_html: current.html, expected_revision: current.revision };
    setSubmitting(false);
    onOpenChange(false);
    showSuccess("Zapisano. Sprawdzamy treść w tle.");
    void startBackgroundApproval(
      {
        key: approvalKey,
        label: candidateName,
        run: () => editorApi.finalize(stageId, payload),
        onSettled: () => {
          void queryClient.invalidateQueries({ queryKey: [scopeKey, stageId] });
          void queryClient.invalidateQueries({ queryKey: ["cv-generated"] });
        },
      },
      { success: showSuccess, error: showError },
    );
  };

  const handlePrint = async () => {
    try {
      await flush();
      await files.print();
    } catch (error) {
      // 409 `consent_required` (wymóg zgody RODO — wydruk nie niesie zrzutu)
      // przychodzi z polskim komunikatem serwera, jak przy pobraniu DOCX.
      showError(getErrorMessage(error) || "Nie udało się otworzyć CV do druku.");
    }
  };

  const isFinalized = saveState === "finalized";
  const [downloadingDocx, setDownloadingDocx] = useState(false);
  const previewDocx = async () => {
    const session = sessionRef.current;
    if (!session) return;
    setDownloadingDocx(true);
    try {
      await session.settle();
      const result = await files.draftDocx(
        {content_html: session.html, expected_revision: session.revision},
        "download",
      );
      downloadBlob(result.blob, result.filename || "SZKIC_CV.docx");
    } catch (error) { showError(getErrorMessage(error)); }
    finally { setDownloadingDocx(false); }
  };
  const downloadApproved = async () => {
    if (!data?.docx_available) return;
    setDownloadingDocx(true);
    try {
      await files.downloadApproved(data.version, data.docx_filename || "CV.docx");
    } catch (error) { showError(getErrorMessage(error)); }
    finally { setDownloadingDocx(false); }
  };
  /** „Podgląd Word”: ten sam plik co „Pobierz”, z treści widocznej w edytorze. */
  const loadWordPreview = async (): Promise<Blob> => {
    const session = sessionRef.current;
    if (!session) throw new Error("Edytor nie wczytał jeszcze CV.");
    await session.settle();
    if (session.state === "finalized" && data?.docx_available) {
      return files.previewApproved(data.version);
    }
    const file = await files.draftDocx(
      {content_html: session.html, expected_revision: session.revision},
      "preview",
    );
    return file.blob;
  };

  const statusText = {
    saved: "Zapisano",
    unsaved: "Niezapisane zmiany",
    saving: "Zapisywanie…",
    error: "Błąd zapisu — poprawki pozostają w edytorze",
    finalizing: "Zapisywanie…",
    finalized: `Zatwierdzona wersja ${data?.version ?? ""} — zmiana utworzy nowy szkic`,
  }[saveState];

  const language: CvLang = data?.language === "en" ? "en" : "pl";
  const hasCv = !!data && !noCv;
  const hasIssuesPanel = hasCv && (!isGenerated || generatorWarnings !== undefined);
  const issuesSide = hasIssuesPanel && issuesOpen && (bothPanels || !sourcesOpen || lastSide === "issues");
  const sourcesSide = sourcesOpen && (bothPanels || !issuesSide);
  const pane = narrowPane === "issues" && !hasIssuesPanel ? "cv" : narrowPane;
  const showSources = hasCv && (sideBySide ? sourcesSide : pane === "sources");
  const showIssues = hasIssuesPanel && (sideBySide ? issuesSide : pane === "issues");
  const showCv = sideBySide || pane === "cv" || !hasCv;
  const toggleSources = () => {
    sideTouched.current = true;
    setSourcesOpen(!sourcesSide);
    if (!sourcesSide) setLastSide("sources");
  };
  const toggleIssues = () => {
    sideTouched.current = true;
    setIssuesOpen(!issuesSide);
    if (!issuesSide) setLastSide("issues");
  };
  // Bez liczby, dopóki QC się liczy; „?” gdy nie odpowiada — zero znaczy zero.
  const issuesLabel =
    issueCount.state === "ready"
      ? `Do poprawy (${issueCount.total})`
      : issueCount.state === "failed"
        ? "Do poprawy (?)"
        : "Do poprawy";
  const sources = isGenerated ? (
    <CvEditorSources context={sourceContext ?? null} loaders={sourceLoaders} />
  ) : (
    <CvEditorSources stageId={stageId} context={sourceContext ?? undefined} loaders={sourceLoaders} />
  );

  return (
    <>
      <Dialog open={open} onOpenChange={(value) => void closeEditor(value)}>
        <DialogContent
          size="full"
          hideClose
          // `max-h-dvh`, nie `max-h-none`: tailwind-merge 2 nie zna `max-h-none`
          // jako max-height i zostawiłby obok bazowe `max-h-[90dvh]` okna.
          className="left-0 top-0 h-dvh max-h-dvh w-full max-w-none translate-x-0 translate-y-0 rounded-none border-0 p-0 shadow-none"
          // Escape w „Szukaj w CV” czyści wyszukiwanie, a w tekście CV nie robi
          // nic — okno zamyka się nim tylko spoza treści (zapis jak przy „Zamknij”).
          onEscapeKeyDown={(event) => {
            keepDialogOpenOnDocumentSearchEscape(event);
            const target = event.target;
            if (target instanceof HTMLElement && target.closest(".ProseMirror")) event.preventDefault();
          }}
          // Okno zajmuje cały ekran; klik w toast (poza drzewem okna) nie może go zamknąć.
          onInteractOutside={(event) => event.preventDefault()}
        >
          <DialogTitle className="sr-only">Edytor CV do klienta</DialogTitle>
          {saveProblem && <div role="alert" className="px-4 py-3 border-b border-border text-sm space-y-2">
            <p className="text-destructive">Nie udało się zapisać CV: {saveProblem.message}</p>
            {saveProblem.conflict && <p className="text-muted-foreground">
              Ktoś zapisał nowszą wersję tego CV. Wczytanie aktualnej wersji zastąpi niezapisane poprawki w edytorze.
            </p>}
            <div className="flex flex-wrap gap-2">
              {saveProblem.conflict && <Button size="sm" variant="outline" disabled={reloading}
                onClick={() => void reloadCurrentVersion()}>
                {reloading ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <RefreshCcw className="h-3 w-3 mr-1" />}
                Wczytaj aktualną wersję
              </Button>}
              <Button size="sm" variant="outline" onClick={() => void closeEditor(false)}>Ponów zapis i zamknij</Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmDiscard(true)}>Zamknij bez zapisu</Button>
            </div>
          </div>}
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-2 border-b border-border">
            <div className="flex min-w-0 items-center gap-3">
              <div className="min-w-0">
                <div className="text-xs uppercase tracking-wider text-muted-foreground">
                  CV do klienta
                </div>
                <div className="text-sm font-medium text-foreground truncate">
                  {candidateName}
                  {jobTitle ? (
                    <span className="text-muted-foreground font-normal"> — {jobTitle}</span>
                  ) : null}
                </div>
              </div>
              {data?.status === "draft" ? (
                <Badge variant="info" size="sm">Szkic v{data?.version ?? 1}</Badge>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {hasCv ? (
                <span className="text-[11px] text-muted-foreground" role="status">
                  {creatingDraft ? "Tworzenie nowego szkicu…" : statusText}
                </span>
              ) : null}
              {hasCv && saveState === "error" ? <Button size="sm" variant="outline" onClick={() => void saveCurrent()}>Ponów zapis</Button> : null}
              <Button
                variant="outline"
                size="sm"
                onClick={handlePrint}
                disabled={!data?.content_html || noCv}
              >
                <Printer className="h-3.5 w-3.5 mr-1.5" />
                Drukuj / PDF
              </Button>
              {!isFinalized && data?.status === "draft" && <Button size="sm" variant="outline"
                disabled={downloadingDocx || submitting} onClick={() => void previewDocx()}>
                <Download className="h-3.5 w-3.5 mr-1.5" /> Pobierz szkic DOCX
              </Button>}
              {isFinalized && data?.docx_available && <Button size="sm" variant="outline"
                disabled={downloadingDocx} onClick={() => void downloadApproved()}>
                <Download className="h-3.5 w-3.5 mr-1.5" /> Pobierz zatwierdzony DOCX v{data.version}
              </Button>}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void closeEditor(false)}
              >
                Zamknij
              </Button>
              <Button
                size="sm"
                onClick={() => void saveAndApprove()}
                disabled={!data || noCv || submitting || creatingDraft}
              >
                {submitting ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1.5" />}
                Zapisz
              </Button>
            </div>
          </div>

          {data?.presentation_review?.status === "conflict" && <p role="alert" className="px-4 py-2 text-sm text-destructive">
            Reguły klienta dla zapisanego szkicu: {data.presentation_review.message}
          </p>}
          {data?.presentation_review?.status === "needs_review" && <p className="px-4 py-2 text-xs text-muted-foreground">
            {data.presentation_review.reason === "rule_snapshot_unavailable"
              ? "Brak potwierdzonej kopii reguł klienta dla tego CV. Sprawdź wymagania klienta przed wysyłką."
              : `Przed wysyłką sprawdź ręcznie: ${(data.presentation_review.manual_fields ?? []).map(field => MANUAL_FIELD_LABELS[field] ?? "dodatkową regułę klienta").join(", ") || "reguły klienta"}. Automatyczna kontrola nie potwierdziła tych reguł.`}
          </p>}
          {unfilled.length > 0 && <p role="alert" className="px-4 py-2 text-sm text-destructive">
            Uzupełnij albo usuń pola w nawiasach, zanim zapiszesz CV dla klienta: {unfilled.join(", ")}. Szkic jest zapisany.
          </p>}
          {hasCv && editor ? (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-background px-3 py-1.5">
              <CvEditorToolbar editor={editor} language={language} disabled={mode === "word" || submitting} />
              {/* Wąski ekran: przełączniki w osobnym wierszu — pasek narzędzi nie traci na nie miejsca. */}
              <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1", sideBySide ? "flex-none" : "basis-full")}>
              <div className="flex flex-none items-center gap-1" role="group" aria-label="Widok CV">
                <ViewToggle active={mode === "edit"} onClick={() => setMode("edit")}>Edycja</ViewToggle>
                <ViewToggle active={mode === "word"} onClick={() => { setMode("word"); setNarrowPane("cv"); }}>
                  Podgląd Word
                </ViewToggle>
              </div>
              {sideBySide ? (
                <div className="flex flex-none items-center gap-1">
                  <Button size="sm" variant="ghost" aria-pressed={sourcesSide} onClick={toggleSources}>
                    <PanelLeft className="h-3.5 w-3.5 mr-1.5" />
                    {sourcesSide ? "Ukryj źródła" : "Pokaż źródła"}
                  </Button>
                  {hasIssuesPanel ? (
                    <Button size="sm" variant="ghost" aria-pressed={issuesSide} onClick={toggleIssues}
                      className={cn(
                        issuesSide && "bg-primary/10 text-primary hover:bg-primary/10",
                        !issuesSide && issueCount.blocking > 0 && "text-destructive",
                      )}>
                      <ListChecks className="h-3.5 w-3.5 mr-1.5" />
                      {issuesLabel}
                    </Button>
                  ) : null}
                </div>
              ) : (
                <div className="flex flex-none items-center gap-1" role="group" aria-label="Kolumna">
                  <ViewToggle active={pane === "cv"} onClick={() => setNarrowPane("cv")}>CV</ViewToggle>
                  <ViewToggle active={pane === "sources"} onClick={() => setNarrowPane("sources")}>Źródła</ViewToggle>
                  {hasIssuesPanel ? (
                    <ViewToggle active={pane === "issues"} onClick={() => setNarrowPane("issues")}>{issuesLabel}</ViewToggle>
                  ) : null}
                </div>
              )}
              </div>
            </div>
          ) : null}

          <div ref={setBody} className="flex min-h-0 flex-1">
            {showSources ? (
              <aside
                aria-label="Źródła CV"
                className={cn(
                  "min-h-0 min-w-0 bg-card",
                  sideBySide ? "w-[440px] flex-none border-r border-border" : "flex-1",
                )}
              >
                {sources}
              </aside>
            ) : null}
            <div
              hidden={!showCv}
              data-cv-lang={language}
              className="cv-paper relative min-h-0 min-w-0 flex-1 overflow-auto bg-muted/40 p-4"
            >
              {loadError && <div role="alert" className="mb-4 space-y-2 text-sm text-destructive">
                <p>Nie udało się wczytać CV: {getErrorMessage(loadError)}</p>
                <Button variant="outline" size="sm" disabled={isFetching} onClick={() => void refetch()}>
                  Ponów wczytanie
                </Button>
                {!data && onRegenerate && (loadError as {response?: {data?: {detail?: {code?: string}}}}).response?.data?.detail?.code === "cv_editor_assets_unavailable" && (
                  <Button variant="outline" size="sm" disabled={isFetching} onClick={() => { onOpenChange(false); onRegenerate(); }}>
                    Przejdź do generatora
                  </Button>
                )}
              </div>}
              {isLoading ? (
                <div className="text-center text-sm text-muted-foreground py-10">
                  Ładowanie…
                </div>
              ) : noCv ? (
                <div className="mx-auto max-w-md space-y-3 py-10 text-center">
                  <p className="text-sm font-medium text-foreground">Najpierw wygeneruj CV</p>
                  <p className="text-sm text-muted-foreground">
                    Ta rekrutacja nie ma jeszcze CV do klienta. Gotowe CV z generatora podepnie się tutaj samo.
                  </p>
                  {onRegenerate ? (
                    <Button size="sm" onClick={() => { onOpenChange(false); onRegenerate(); }}>
                      <Sparkles className="h-3.5 w-3.5 mr-1.5" /> Wygeneruj CV
                    </Button>
                  ) : null}
                </div>
              ) : data ? (
                <>
                  {/* Edytor zostaje zamontowany pod podglądem — stan i kursor nie giną. */}
                  <div hidden={mode !== "edit"}>
                    <EditorContent editor={editor} />
                  </div>
                  {mode === "word" ? <CvEditorWordPreview load={loadWordPreview} /> : null}
                </>
              ) : null}
            </div>
            {hasIssuesPanel && editor && data ? (
              // Zamontowany także ukryty: liczy znaczniki na kartce i licznik w pasku.
              <aside
                aria-label="Do poprawy"
                hidden={!showIssues}
                className={cn(
                  "min-h-0 min-w-0 bg-card",
                  sideBySide ? "w-[360px] flex-none border-l border-border" : "flex-1",
                )}
              >
                <CvEditorIssues
                  editor={editor}
                  stageId={isGenerated ? undefined : stageId}
                  generatorWarnings={generatorWarnings}
                  savedRevision={data.edit_revision}
                  unsaved={saveState !== "saved" && saveState !== "finalized"}
                  readOnly={mode === "word" || submitting || creatingDraft}
                  ensureDraft={ensureDraft}
                  onShowCv={() => {
                    setMode("edit");
                    setNarrowPane("cv");
                  }}
                  onCount={setIssueCount}
                  api={issuesApi}
                />
              </aside>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>

      {confirmDiscard ? (
        <Dialog open onOpenChange={() => setConfirmDiscard(false)}>
          <DialogContent size="md">
            <div className="p-5 space-y-3">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-5 w-5 text-destructive mt-0.5" />
                <div>
                  <h3 className="font-medium">Zamknąć bez zapisu?</h3>
                  <p className="text-sm text-muted-foreground mt-1">
                    Niezapisane poprawki z edytora przepadną. Na serwerze zostaje ostatnia zapisana wersja CV.
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="ghost" size="sm" onClick={() => setConfirmDiscard(false)}>Wróć do edycji</Button>
                <Button variant="destructive" size="sm" onClick={() => {
                  setConfirmDiscard(false);
                  setSaveProblem(null);
                  onOpenChange(false);
                }}>Zamknij bez zapisu</Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  );
}
