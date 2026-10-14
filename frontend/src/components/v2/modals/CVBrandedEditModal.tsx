"use client";

/**
 * CVBrandedEditModal — edytor CV do klienta (Tiptap + autosave), na cały ekran.
 *
 * Dwa miejsca, jeden edytor: CV etapu rekrutacji (`stageId`, karta „CV do
 * klienta”, dok kanbana, profil kandydata) i wynik generatora (`generatedId`,
 * okno generatora).
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
 * (`cv-editor/CvEditorSources`), „Jak u klienta” (strony PDF) z bieżącej treści i stała
 * klauzula zgody (`lib/cv-editor-structure.ts`). Logika sesji, zapisu
 * i zatwierdzenia została bez zmian.
 *
 * PR 2: po prawej panel „Do poprawy” (`cv-editor/CvEditorIssues`) — QC, uwagi
 * generatora i kontrola AI przy tekście. Panel jest zamontowany także wtedy,
 * gdy go nie widać: liczy znaczniki na kartce i licznik w pasku. Przy
 * szerokości 1180–1539 px (laptop 1280) obok kartki mieści się JEDEN panel —
 * źródła albo „Do poprawy”; od 1540 px oba.
 *
 * PR 5: „Historia” — zatwierdzone wersje i powrót pliku Word
 * (`cv-editor/useCvHistory`, `CvEditorHistory`); treść trafia do CV dopiero po
 * obejrzeniu różnic.
 *
 * Edytor CV 3, PR 3 (14.10.2026, „bardzo, bardzo prosto”): nagłówek w jednym
 * rzędzie (pasek z „Pogrub wymagania (N)” i „Więcej”, „Edycja | Jak u klienta”,
 * stan zapisu, „Oryginał”, „Pobierz Word”), JEDNA kolumna obok kartki
 * („Do poprawy” albo oryginał; plan zmian i historia zajmują ją na czas
 * decyzji) i stopka z „Gotowe” zamiast „Zapisz” w nagłówku — ta sama ścieżka
 * zapisu i zatwierdzenia w tle. Układ dwóch paneli od 1540 px zniknął.
 *
 * Edytor CV 3, PR 4 (14.10.2026): asystent w kolumnie (`cv-editor/useCvAssistant`,
 * `CvEditorAssistant`) zastępuje dymek AI nad zaznaczeniem, menu „AI” i pole
 * „Polecenie” z planem zmian. Kolumna CV etapu = „Do poprawy” (zwijane;
 * rozwinięte przy blokadach) nad asystentem. Zmiany asystenta są od razu na
 * kartce, w jednym kroku cofania na wiadomość.
 *
 * D6 (14.10.2026): z propem `handoff` (karta na „Zweryfikowany”) stopka ma
 * „Uwaga dla Delivery Leada”, stan QC, „Gotowe” i „Gotowe, przekaż do DL →”.
 * Zapis jest ten sam co „Gotowe” (szkic, pola w nawiasach); ruch karty robi
 * wołający, a zatwierdzenie w tle rusza dopiero po udanym ruchu i zamknięciu
 * okna — zatwierdzenie pod otwartym edytorem rozjechałoby wersję szkicu przy
 * następnym autozapisie. Blokady QC zamieniają przycisk w „Przekaż mimo
 * uwag…” (okno obejścia QC z powodem). Bez `handoff` stopka ma samo „Gotowe”.
 */

import { useState, useEffect, useRef, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEditor, EditorContent } from "@tiptap/react";
import {
  Check,
  ChevronDown,
  FileText,
  History,
  Loader2,
  Printer,
  Download,
  RefreshCcw,
  Sparkles,
  AlertCircle,
  X,
} from "lucide-react";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { CvEditorHandoffBar } from "@/components/v2/cv-editor/CvEditorHandoffBar";
import { QcOverrideDialog } from "@/components/v2/recruitment/QcOverrideDialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CvDraftSession, type CvSaveState } from "@/lib/cv-draft-session";
import { useToast } from "@/components/Toast";
import {
  CvEditorSources,
  type CvEditorSourceContext,
  type CvEditorSourcesProps,
} from "@/components/v2/cv-editor/CvEditorSources";
import {
  CvEditorIssues,
  type CvEditorIssuesHandle,
  type CvIssueCount,
} from "@/components/v2/cv-editor/CvEditorIssues";
import { CvEditorAssistant } from "@/components/v2/cv-editor/CvEditorAssistant";
import { CV_PANEL_ATTR } from "@/components/v2/cv-editor/Marked";
import { CvEditorHistory } from "@/components/v2/cv-editor/CvEditorHistory";
import { useCvAssistant } from "@/components/v2/cv-editor/useCvAssistant";
import { useCvHistory } from "@/components/v2/cv-editor/useCvHistory";
import { CvEditorToolbar, type CvEditorMoreItem } from "@/components/v2/cv-editor/CvEditorToolbar";
import { CvPagesPreview } from "@/components/v2/cv/CvPagesPreview";
import { keepDialogOpenOnDocumentSearchEscape } from "@/components/v2/files/DocumentSearchBar";
import {
  openAuthenticatedFile,
  downloadAuthenticatedFile,
  fetchAuthenticatedBlob,
  fetchAuthenticatedDownload,
  postAuthenticatedDownload,
  downloadBlob,
  type AuthenticatedDownload,
} from "@/lib/authenticated-files";
import {
  candidateStageCvApi,
  cvGeneratedEditorApi,
  type CVBrandedState,
} from "@/lib/api";
import type { CvEditorCommandApi } from "@/lib/api/cvEditorCommand";
import type { CvEditorHistoryApi } from "@/lib/api/cvEditorHistory";
import type { CvEditorIssuesApi } from "@/lib/api/cvEditorIssues";
import {
  generatedApprovalKey,
  stageApprovalKey,
  startBackgroundApproval,
} from "@/lib/cv-background-approval";
import { withDownloadIntent } from "@/lib/cv-download-intent";
import { normalizeCvAlign } from "@/lib/cv-editor-align";
import { cvPlaceholders, type CvLang } from "@/lib/cv-editor-blocks";
import { boldRequirements } from "@/lib/cv-editor-issues";
import { cvEditorExtensions, loadCvHtml } from "@/lib/cv-editor-structure";
import { apiErrorMessage } from "@/lib/api-error";
import {
  handedOffMessage,
  handoffGate,
  handoffStatus,
  type CvEditorHandoff,
} from "@/lib/cv-editor-handoff";
import { hasPermission } from "@/lib/permissions";
import { useElementWidth } from "@/lib/use-element-width";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

/** Od tej szerokości okna (px) kolumna stoi obok kartki; węziej — przełącznik. */
const SIDE_BY_SIDE_MIN_WIDTH = 1180;

const NO_ISSUES: CvIssueCount = { total: 0, blocking: 0, state: "loading" };

type CvDraftPayload = { content_html: string; expected_revision: number };

/** Pliki edytora. Harness podaje wersję z pamięci — podgląd `/preview/*` nie ma sieci. */
export interface CvEditorFiles {
  /** Word z bieżącej treści szkicu: do pobrania albo do „Podglądu Word”. */
  draftDocx: (payload: CvDraftPayload, purpose: "download" | "preview") => Promise<AuthenticatedDownload>;
  downloadApproved: (version: number, filename: string) => Promise<void>;
  previewApproved: (version: number) => Promise<Blob>;
  /** „Jak u klienta” i „Pobierz PDF”: PDF szkicu z bieżącej treści (Edytor CV 3, J2). */
  draftPdf?: (payload: CvDraftPayload, purpose: "download" | "preview") => Promise<AuthenticatedDownload>;
  /** PDF zatwierdzonej wersji; brak = PDF z treści (edytor wyniku generatora). */
  approvedPdf?: (version: number, purpose: "download" | "preview") => Promise<AuthenticatedDownload>;
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
    draftPdf: (payload, purpose) =>
      postAuthenticatedDownload(
        purpose === "download"
          ? withDownloadIntent(`${basePath}/preview-pdf`, "editor")
          : `${basePath}/preview-pdf`,
        payload,
      ),
    // PDF wersji ma tylko CV etapu; edytor wyniku generatora bierze PDF z treści.
    approvedPdf: basePath.includes("/cv/branded")
      ? (version, purpose) =>
          fetchAuthenticatedDownload(
            purpose === "download"
              ? withDownloadIntent(`${basePath}/versions/${version}/pdf`, "editor")
              : `${basePath}/versions/${version}/pdf`,
          )
      : undefined,
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
  /**
   * „Napisz od nowa: …” z asystenta (Edytor CV 3, PR 5): edytor zapisuje szkic,
   * zamyka się i oddaje uwagę karcie, która zleca nową generację.
   */
  onRewrite?: (instruction: string) => void;
  /**
   * Panel otwarty od razu: „Sprawdź i popraw” z karty „CV do klienta” otwiera
   * edytor na „Do sprawdzenia” (także w wąskim oknie, zamiast kartki),
   * „Historia wersji” z menu karty — na historii.
   */
  initialPanel?: "issues" | "history";

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
    /** Harness: plan zmian dla polecenia z pamięci zamiast sieci. */
  commandApi?: CvEditorCommandApi;
  /** Harness: wersje CV i treść pliku Word z pamięci zamiast sieci. */
  historyApi?: CvEditorHistoryApi;
  /**
   * Przekazanie Delivery Leadowi ze stopki (D6, 14.10.2026) — tylko CV etapu,
   * gdy karta stoi na „Zweryfikowany”. Bez propa edytor wygląda jak dotąd.
   */
  handoff?: CvEditorHandoff;
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
  onRewrite,
  initialPanel,
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
  commandApi,
  historyApi,
  handoff: handoffProp,
}: Props) {
  const stageId = (generatedId ?? pipelineStageId)!;
  const isGenerated = generatedId !== undefined;
  // Ruch karty ma tylko CV etapu — wynik generatora nie ma karty.
  const handoff = isGenerated ? undefined : handoffProp;
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
  // Jedna kolumna obok kartki (Edytor CV 3, PR 3): „Do poprawy” albo oryginał
  // („Oryginał” w nagłówku). `null` = domyślnie: oryginał tylko, gdy edytor
  // nie ma panelu „Do poprawy” (wynik generatora bez uwag).
  const [sourcesChoice, setSourcesChoice] = useState<boolean | null>(null);
  const issuesFirst = initialPanel === "issues";
  const issuesRef = useRef<CvEditorIssuesHandle>(null);
  const [issueCount, setIssueCount] = useState<CvIssueCount>(NO_ISSUES);
  const [narrowPane, setNarrowPane] = useState<"cv" | "sources" | "issues" | "plan" | "history">(
    issuesFirst ? "issues" : "cv",
  );
  // Panel „Do poprawy” nad asystentem: rozwinięty, gdy są blokady albo karta
  // otwiera edytor na uwagach; potem decyduje człowiek (`null` = sam).
  const [issuesChoice, setIssuesChoice] = useState<boolean | null>(issuesFirst ? true : null);
  const [body, setBody] = useState<HTMLElement | null>(null);
  const bodyWidth = useElementWidth(body);
  const sideBySide = bodyWidth >= SIDE_BY_SIDE_MIN_WIDTH;

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
  // „Zapisano 14:01” — godzina ostatniego autozapisu w tej sesji.
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const previousSaveState = useRef<CvSaveState>("saved");
  useEffect(() => {
    if (saveState === "saved" && previousSaveState.current === "saving") setSavedAt(new Date());
    previousSaveState.current = saveState;
  }, [saveState]);
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
   * Zapis jak przed zatwierdzeniem: szkic na serwer, potem pola w nawiasach.
   * `null` = nie da się (komunikat już stoi); `payload: null` = zatwierdzona
   * wersja bez zmian — nie ma czego zatwierdzać.
   */
  const saveForApproval = async (): Promise<{ payload: CvDraftPayload | null } | null> => {
    const session = sessionRef.current;
    if (!session) return null;
    try {
      await flush();
    } catch (error) {
      reportSaveProblem(error);
      return null;
    }
    setSaveProblem(null);
    const current = sessionRef.current ?? session;
    if (current.state === "finalized") return { payload: null };
    // Nowe bloki mają pola w nawiasach kwadratowych. Szkic z nimi zapisuje
    // się normalnie, ale do zatwierdzenia (i do klienta) nie mogą pójść.
    const missing = cvPlaceholders(current.html);
    if (missing.length > 0) {
      setUnfilled(missing);
      return null;
    }
    return { payload: { content_html: current.html, expected_revision: current.revision } };
  };
  const approveInBackground = (payload: CvDraftPayload) => {
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

  /**
   * „Zapisz”: zapis szkicu → zamknięcie okna → zatwierdzenie w tle. Niczego
   * nie zmienione w zatwierdzonej wersji = samo zamknięcie.
   */
  const saveAndApprove = async () => {
    if (!sessionRef.current || submitting) return;
    setSubmitting(true);
    const saved = await saveForApproval();
    setSubmitting(false);
    if (!saved) return;
    onOpenChange(false);
    if (!saved.payload) return;
    showSuccess("Zapisano. Sprawdzamy treść w tle.");
    approveInBackground(saved.payload);
  };

  // ── Przekazanie Delivery Leadowi (D6) ─────────────────────────────────────
  const [remark, setRemark] = useState("");
  const [handoffError, setHandoffError] = useState<string | null>(null);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const impersonating = useAuthStore((s) => s.realUser !== null);
  const me = useAuthStore((s) => s.user);
  const gate = handoffGate(issueCount, {
    impersonating,
    canManage: hasPermission(me, "recruitment_manage"),
    advisoryFallback: handoff?.advisory,
  });

  /** Zapis jak „Zapisz”, ruch karty u wołającego; zatwierdzenie w tle dopiero po ruchu. */
  const saveAndHandOff = async () => {
    if (!handoff || !sessionRef.current || submitting) return;
    setSubmitting(true);
    setHandoffError(null);
    try {
      const saved = await saveForApproval();
      if (!saved) return;
      let moved = false;
      try {
        moved = await handoff.onSaveAndHandOff(remark.trim());
      } catch (error) {
        setHandoffError(
          `${apiErrorMessage(error, "Nie udało się przekazać Delivery Leadowi.")} CV jest zapisane — spróbuj ponownie.`,
        );
        return;
      }
      if (!moved) {
        // Powód odmowy pokazał już rdzeń ruchu (komunikat obok).
        setHandoffError("Karta nie przeszła do Delivery Leada. CV jest zapisane — spróbuj ponownie.");
        return;
      }
      onOpenChange(false);
      showSuccess(handedOffMessage(candidateName, saved.payload != null));
      if (saved.payload) approveInBackground(saved.payload);
    } finally {
      setSubmitting(false);
    }
  };

  /** „Przekaż mimo uwag…”: pola w nawiasach sprawdzamy przed oknem obejścia. */
  const openOverride = () => {
    if (submitting) return;
    const html = liveEditor()?.getHTML() ?? sessionRef.current?.html ?? "";
    const missing = cvPlaceholders(html);
    if (missing.length > 0) {
      setUnfilled(missing);
      return;
    }
    setHandoffError(null);
    setOverrideOpen(true);
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
  /** PDF tego samego pliku co „Pobierz Word”: wersja zatwierdzona albo szkic z treści. */
  const loadPdf = async (purpose: "download" | "preview"): Promise<AuthenticatedDownload> => {
    const session = sessionRef.current;
    if (!session) throw new Error("Edytor nie wczytał jeszcze CV.");
    await session.settle();
    if (session.state === "finalized" && data?.docx_available && files.approvedPdf) {
      return files.approvedPdf(data.version, purpose);
    }
    if (!files.draftPdf) throw new Error("PDF tego CV nie jest tu dostępny.");
    return files.draftPdf({ content_html: session.html, expected_revision: session.revision }, purpose);
  };
  /** „Jak u klienta”: strony PDF z tego samego pliku co „Pobierz”. */
  const loadPagesPreview = (): Promise<Blob> => loadPdf("preview").then((file) => file.blob);
  const downloadPdf = async () => {
    setDownloadingDocx(true);
    try {
      const file = await loadPdf("download");
      downloadBlob(file.blob, file.filename || "CV.pdf");
    } catch (error) { showError(getErrorMessage(error)); }
    finally { setDownloadingDocx(false); }
  };
  /** Zapas „Jak u klienta”: ten sam plik co „Pobierz”, z treści widocznej w edytorze. */
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
    saved: savedAt
      ? `Zapisano ${savedAt.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}`
      : "Zapisano",
    unsaved: "Niezapisane zmiany",
    saving: "Zapisywanie…",
    error: "Błąd zapisu — poprawki pozostają w edytorze",
    finalizing: "Zapisywanie…",
    finalized: `Zatwierdzona wersja ${data?.version ?? ""}`,
  }[saveState];

  const language: CvLang = data?.language === "en" ? "en" : "pl";
  const textAlign = normalizeCvAlign(data?.text_align);
  const hasCv = !!data && !noCv;
  // Asystent (Edytor CV 3, PR 4): jedno miejsce do AI, zmiany od razu.
  const assistant = useCvAssistant({
    editor,
    stageId: isGenerated ? undefined : stageId,
    // Bez `creatingDraft`: szkic na zatwierdzonej wersji zakłada pierwsza nakładana zmiana.
    disabled: !hasCv || mode === "word" || submitting,
    ensureDraft,
    api: commandApi,
    onRewrite: onRewrite
      ? (instruction) => {
          void closeEditor(false).then((closed) => {
            if (closed) onRewrite(instruction);
          });
        }
      : undefined,
  });
  useEffect(() => {
    // Bez zgłaszania „update”: Tiptap domyślnie zgłasza je przy każdej zmianie
    // trybu edycji, a dla okna to znaczy „treść się zmieniła”. „Zapisz” na
    // zatwierdzonym CV bez żadnej poprawki zakładało przez to nowy szkic.
    // Plan asystenta odnosi się do treści z chwili wysłania — do odpowiedzi
    // kartka jest tylko do odczytu.
    editor?.setEditable(!noCv && !submitting && !assistant.locked, false);
  }, [editor, noCv, submitting, assistant.locked]);
  const history = useCvHistory({
    editor,
    stageId: isGenerated ? undefined : stageId,
    // Bez `creatingDraft`: szkic na zatwierdzonej wersji zakłada samo „Przywróć” / „Wstaw”.
    // Z `!open`: zamknięte okno nie przyjmuje treści, której zakładanie szkicu jeszcze trwało.
    disabled: !open || !hasCv || mode === "word" || submitting,
    ensureDraft,
    downloadVersion: (version) => {
      // Wersja, którą etap pokazuje teraz, ma nazwę jak przycisk w nagłówku; starsze niosą numer.
      const name = data?.docx_filename || "CV.docx";
      return files.downloadApproved(
        version,
        version === data?.version ? name : name.replace(/(\.docx)?$/i, `_v${version}.docx`),
      );
    },
    onApplied: () => setNarrowPane("cv"),
    api: historyApi,
  });
  const historyOpen = history.open;
  const hasIssuesPanel = hasCv && (!isGenerated || generatorWarnings !== undefined);
  const sourcesSide = sourcesChoice ?? !hasIssuesPanel;
  const pane =
    (narrowPane === "issues" && !hasIssuesPanel) ||
    (narrowPane === "history" && !historyOpen)
      ? "cv"
      : narrowPane;
  // Historia zajmuje kolumnę na czas przeglądania.
  const takeover = historyOpen;
  const showHistory = historyOpen && (sideBySide || pane === "history");
  const showSources = hasCv && (sideBySide ? sourcesSide && !takeover : pane === "sources");
  const showIssues = hasIssuesPanel && !takeover && (sideBySide ? !sourcesSide : pane === "issues");
  const showCv = sideBySide || pane === "cv" || !hasCv;
  useEffect(() => {
    setNarrowPane((current) => (historyOpen ? "history" : current === "history" ? "cv" : current));
  }, [historyOpen]);
  const openHistory = () => history.show();
  // „Historia wersji” z menu karty „CV do klienta” otwiera edytor od razu na historii.
  // Czekamy na gotową historię, nie na samo CV: karta ma stan CV w pamięci, więc
  // CV jest od pierwszego renderu, a edytor (i historia) — dopiero po nim.
  const historyFirst = useRef(initialPanel === "history");
  useEffect(() => {
    if (!historyFirst.current || !history.enabled) return;
    historyFirst.current = false;
    history.show();
  }, [history]);
  // „Oryginał”: kolumna pokazuje oryginał zamiast „Do poprawy” (i odwrotnie);
  // otwarta historia ustępuje oryginałowi.
  const toggleSources = () => {
    if (historyOpen) {
      history.close();
      setSourcesChoice(true);
      return;
    }
    setSourcesChoice(!sourcesSide);
  };
  // Bez liczby, dopóki QC się liczy; „?” gdy nie odpowiada — zero znaczy zero.
  const issuesLabel =
    issueCount.state === "ready"
      ? `Do poprawy (${issueCount.total})`
      : issueCount.state === "failed"
        ? "Do poprawy (?)"
        : "Do poprawy";
  const bold = boldRequirements(issueCount.state === "ready" ? (issueCount.qc?.checks ?? null) : null);
  const canPdf = isFinalized && data?.docx_available ? !!(files.approvedPdf ?? files.draftPdf) : data?.status === "draft" && !!files.draftPdf;
  const moreGroups: CvEditorMoreItem[][] = [
    isGenerated
      ? []
      : [
          {
            label: historyOpen ? "Zamknij historię wersji" : "Historia wersji",
            icon: <History aria-hidden className="h-4 w-4" />,
            title: "Zatwierdzone wersje CV i poprawiony plik Word",
            // Asystent liczy zmiany — historia poczeka na jego odpowiedź.
            disabled: mode === "word" || submitting || assistant.locked || history.busy,
            onSelect: () => (historyOpen ? history.close() : openHistory()),
          },
        ],
    [
      {
        label: "Pobierz PDF",
        icon: <Download aria-hidden className="h-4 w-4" />,
        disabled: !canPdf || downloadingDocx || submitting,
        onSelect: () => void downloadPdf(),
      },
      {
        label: "Drukuj",
        icon: <Printer aria-hidden className="h-4 w-4" />,
        disabled: !data?.content_html || noCv,
        onSelect: () => void handlePrint(),
      },
    ],
  ];
  // Asystent ma tylko CV etapu (rekrutacja = wymagania, notatki i uprawnienia).
  const withAssistant = !isGenerated && hasCv;
  const issuesExpanded =
    issuesChoice ?? (issueCount.blocking > 0 || issueCount.state === "failed" || !withAssistant);
  const sources = isGenerated ? (
    <CvEditorSources context={sourceContext ?? null} loaders={sourceLoaders} />
  ) : (
    <CvEditorSources
      stageId={stageId}
      context={sourceContext ?? undefined}
      loaders={sourceLoaders}
    />
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
            if (!(target instanceof HTMLElement)) return;
            // W asystencie i w historii Escape nie zamyka edytora — także gdy
            // asystent liczy zmiany (pole jest wtedy wyłączone, klawisz trafia w `body`).
            if (assistant.locked || target.closest(".ProseMirror") || target.closest(`[${CV_PANEL_ATTR}]`)) {
              event.preventDefault();
            }
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
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 border-b border-border px-2 py-1.5">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Zamknij"
              title="Zamknij — poprawki są zapisane jako szkic"
              onClick={() => void closeEditor(false)}
            >
              <X aria-hidden className="h-4 w-4" />
            </Button>
            <div className="min-w-0 max-w-[12rem] flex-none">
              <div
                className="truncate text-sm font-medium text-foreground"
                title={jobTitle ? `${candidateName} — ${jobTitle}` : candidateName}
              >
                {candidateName}
              </div>
              {jobTitle ? <div className="truncate text-[11px] text-muted-foreground">{jobTitle}</div> : null}
            </div>
            {data?.status === "draft" ? (
              <Badge variant="info" size="sm" className="flex-none">Szkic v{data?.version ?? 1}</Badge>
            ) : null}
            {hasCv && editor ? (
              <CvEditorToolbar
                editor={editor}
                language={language}
                defaultAlign={textAlign}
                disabled={mode === "word" || submitting || assistant.locked}
                boldRequirements={
                  hasIssuesPanel && !isGenerated
                    ? {
                        count: bold.count,
                        disabled: mode === "word" || submitting || creatingDraft || assistant.locked,
                        onRun: () => issuesRef.current?.boldRequirements(),
                      }
                    : undefined
                }
                moreGroups={moreGroups}
              />
            ) : (
              <div className="flex-1" />
            )}
            <div className="ml-auto flex flex-none flex-wrap items-center gap-1">
              {hasCv ? (
                <div className="flex flex-none items-center gap-1" role="group" aria-label="Widok CV">
                  <ViewToggle active={mode === "edit"} onClick={() => setMode("edit")}>Edycja</ViewToggle>
                  <ViewToggle active={mode === "word"} onClick={() => { setMode("word"); setNarrowPane("cv"); }}>
                    Jak u klienta
                  </ViewToggle>
                </div>
              ) : null}
              {hasCv ? (
                <span
                  className="px-1 text-[11px] text-muted-foreground"
                  role="status"
                  title={isFinalized ? "Zmiana utworzy nowy szkic — zatwierdzona wersja zostaje." : undefined}
                >
                  {creatingDraft ? "Tworzenie nowego szkicu…" : statusText}
                </span>
              ) : null}
              {hasCv && saveState === "error" ? (
                <Button size="sm" variant="outline" onClick={() => void saveCurrent()}>Ponów zapis</Button>
              ) : null}
              {hasCv && sideBySide ? (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-pressed={showSources}
                  // Asystent liczy zmiany — kolumna z jego odpowiedzią zostaje na miejscu.
                  disabled={assistant.locked}
                  title="Oryginalne CV, Champion, odpowiedzi i notatki — źródła tego CV"
                  className={cn(showSources && "bg-primary/10 text-primary hover:bg-primary/10")}
                  onClick={toggleSources}
                >
                  <FileText className="h-3.5 w-3.5 mr-1.5" aria-hidden />
                  Oryginał
                </Button>
              ) : null}
              {!isFinalized && data?.status === "draft" ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={downloadingDocx || submitting}
                  title="Plik Word szkicu z treści widocznej w edytorze"
                  onClick={() => void previewDocx()}
                >
                  <Download className="h-3.5 w-3.5 mr-1.5" aria-hidden /> Pobierz Word
                </Button>
              ) : null}
              {isFinalized && data?.docx_available ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={downloadingDocx}
                  title={`Zatwierdzona wersja ${data.version}`}
                  onClick={() => void downloadApproved()}
                >
                  <Download className="h-3.5 w-3.5 mr-1.5" aria-hidden /> Pobierz Word
                </Button>
              ) : null}
            </div>
            {hasCv && !sideBySide ? (
              // Wąski ekran: kartka, oryginał i kolumna na zmianę, w osobnym wierszu.
              <div className="flex basis-full flex-wrap items-center gap-1" role="group" aria-label="Kolumna">
                <ViewToggle active={pane === "cv"} onClick={() => setNarrowPane("cv")}>CV</ViewToggle>
                <ViewToggle active={pane === "sources"} onClick={() => setNarrowPane("sources")}>Oryginał</ViewToggle>
                {hasIssuesPanel && !takeover ? (
                  <ViewToggle active={pane === "issues"} onClick={() => setNarrowPane("issues")}>{issuesLabel}</ViewToggle>
                ) : null}
                {historyOpen ? (
                  <ViewToggle active={pane === "history"} onClick={() => setNarrowPane("history")}>Historia</ViewToggle>
                ) : null}
              </div>
            ) : null}
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

          <div ref={setBody} className="flex min-h-0 flex-1">
            <div
              hidden={!showCv}
              data-cv-lang={language}
              data-cv-align={textAlign}
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
                  {mode === "word" ? (
                    <CvPagesPreview
                      loadPdf={loadPagesPreview}
                      loadDocx={loadWordPreview}
                      className="absolute inset-0"
                    />
                  ) : null}
                </>
              ) : null}
            </div>
            {showSources ? (
              <aside
                aria-label="Źródła CV"
                className={cn(
                  "min-h-0 min-w-0 bg-card",
                  sideBySide ? "w-[440px] flex-none border-l border-border" : "flex-1",
                )}
              >
                {sources}
              </aside>
            ) : null}
            {hasIssuesPanel && editor && data ? (
              // Zamontowany także ukryty: liczy znaczniki na kartce i liczbę w pasku.
              <aside
                aria-label="Do poprawy"
                hidden={!showIssues}
                className={cn(
                  "flex min-h-0 min-w-0 flex-col bg-card",
                  sideBySide ? "w-[360px] flex-none border-l border-border" : "flex-1",
                )}
              >
                {/* Zamontowany także zwinięty: liczy znaczniki na kartce i liczbę w pasku. */}
                <div
                  className={cn(
                    "min-h-0",
                    !withAssistant ? "flex-1" : issuesExpanded ? "flex-[2_1_0%] overflow-hidden" : "flex-none",
                  )}
                >
                  <CvEditorIssues
                    ref={issuesRef}
                    editor={editor}
                    stageId={isGenerated ? undefined : stageId}
                    generatorWarnings={generatorWarnings}
                    savedRevision={data.edit_revision}
                    unsaved={saveState !== "saved" && saveState !== "finalized"}
                    readOnly={mode === "word" || submitting || creatingDraft || assistant.locked}
                    ensureDraft={ensureDraft}
                    onShowCv={() => {
                      setMode("edit");
                      setNarrowPane("cv");
                    }}
                    onCount={setIssueCount}
                    api={issuesApi}
                    collapsed={withAssistant && !issuesExpanded}
                    heading={
                      withAssistant ? (
                        // Edytor CV 3 (PR 4): „Do poprawy” zwijane nad asystentem — jedna kolumna.
                        <button
                          type="button"
                          aria-expanded={issuesExpanded}
                          className="-mx-1 flex items-center gap-1.5 rounded px-1 py-1 text-left text-sm font-semibold hover:bg-muted/50"
                          onClick={() => setIssuesChoice(!issuesExpanded)}
                        >
                          <ChevronDown aria-hidden className={cn("h-3.5 w-3.5 transition-transform", !issuesExpanded && "-rotate-90")} />
                          {issuesLabel}
                          {issueCount.blocking > 0 ? (
                            <span className="text-xs font-normal text-destructive">· blokuje wysyłkę: {issueCount.blocking}</span>
                          ) : null}
                        </button>
                      ) : undefined
                    }
                  />
                </div>
                {withAssistant ? <CvEditorAssistant controller={assistant} editor={editor} /> : null}
              </aside>
            ) : null}
            {showHistory ? (
              <aside
                className={cn(
                  "min-h-0 min-w-0 bg-card",
                  sideBySide ? "w-[360px] flex-none border-l border-border" : "flex-1",
                )}
              >
                <CvEditorHistory controller={history} />
              </aside>
            ) : null}
          </div>
          {handoff && hasCv ? (
            <CvEditorHandoffBar
              gate={gate}
              status={handoffStatus(issueCount, gate)}
              remark={remark}
              onRemarkChange={setRemark}
              busy={submitting}
              // Asystent liczy albo nakłada odpowiedź — zapis poczeka na zmianę.
              disabled={!data || creatingDraft || assistant.busy}
              error={handoffError}
              onSave={() => void saveAndApprove()}
              onHandOff={() => void saveAndHandOff()}
              onOverride={openOverride}
            />
          ) : hasCv ? (
            <div
              role="group"
              aria-label="Zakończenie pracy z CV"
              className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border bg-card px-4 py-2"
            >
              <p className="text-xs text-muted-foreground">
                Zmiany zapisują się same. „Gotowe” zamyka CV i sprawdza treść w tle.
              </p>
              <Button
                size="sm"
                className="ml-auto"
                onClick={() => void saveAndApprove()}
                disabled={!data || noCv || submitting || creatingDraft || assistant.busy}
              >
                {submitting ? (
                  <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" aria-hidden />
                ) : (
                  <Check className="h-3.5 w-3.5 mr-1.5" aria-hidden />
                )}
                Gotowe
              </Button>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
      {overrideOpen && handoff && gate.kind === "override" ? (
        <QcOverrideDialog
          stageId={stageId}
          open
          onOpenChange={setOverrideOpen}
          pending={gate.pending}
          advisory={gate.advisory}
          // Powód zapisany — dalej to samo co „Zapisz i przekaż do DL”.
          onDone={() => void saveAndHandOff()}
        />
      ) : null}

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
