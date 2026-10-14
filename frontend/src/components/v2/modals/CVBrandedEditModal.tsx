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
 * PR 3: „AI na zaznaczeniu” — dymek nad zaznaczonym tekstem i menu „AI” w pasku
 * (`cv-editor/useCvSelectionAi`, `CvEditorSelectionAi`). Tylko dla CV etapu
 * (potrzebne źródła i wymagania rekrutacji); propozycja trafia do CV dopiero po
 * „Przyjmij”.
 *
 * PR 5: „Historia” — zatwierdzone wersje i powrót pliku Word
 * (`cv-editor/useCvHistory`, `CvEditorHistory`). Panel zajmuje miejsce planu
 * zmian (jedno albo drugie), a treść trafia do CV dopiero po obejrzeniu różnic.
 *
 * D6 (14.10.2026): z propem `handoff` (karta na „Zweryfikowany”) stopka ma
 * „Uwaga dla Delivery Leada”, stan QC, „Zapisz” i „Zapisz i przekaż do DL →”.
 * Zapis jest ten sam co „Zapisz” (szkic, pola w nawiasach); ruch karty robi
 * wołający, a zatwierdzenie w tle rusza dopiero po udanym ruchu i zamknięciu
 * okna — zatwierdzenie pod otwartym edytorem rozjechałoby wersję szkicu przy
 * następnym autozapisie. Blokady QC zamieniają przycisk w „Przekaż mimo
 * uwag…” (okno obejścia QC z powodem). Bez `handoff` okno jest jak dotąd.
 */

import { useState, useEffect, useRef, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEditor, EditorContent } from "@tiptap/react";
import {
  History,
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
import { CV_AI_CARD_ATTR } from "@/components/v2/cv-editor/CvAiProposalCard";
import { CvEditorIssues, type CvIssueCount } from "@/components/v2/cv-editor/CvEditorIssues";
import { CvEditorSelectionAi } from "@/components/v2/cv-editor/CvEditorSelectionAi";
import { CvEditorCommandBar, CV_COMMAND_ATTR } from "@/components/v2/cv-editor/CvEditorCommandBar";
import { CvEditorHistory } from "@/components/v2/cv-editor/CvEditorHistory";
import { CvEditorPlan } from "@/components/v2/cv-editor/CvEditorPlan";
import { useCvCommandPlan } from "@/components/v2/cv-editor/useCvCommandPlan";
import { useCvHistory } from "@/components/v2/cv-editor/useCvHistory";
import { CvEditorToolbar } from "@/components/v2/cv-editor/CvEditorToolbar";
import { CvPagesPreview } from "@/components/v2/cv/CvPagesPreview";
import { useCvSelectionAi } from "@/components/v2/cv-editor/useCvSelectionAi";
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
import type { CvEditorAiApi } from "@/lib/api/cvEditorAi";
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
  /** „Jak u klienta”: strony PDF szkicu z bieżącej treści (Edytor CV 3, J2). */
  draftPdf?: (payload: CvDraftPayload) => Promise<Blob>;
  /** „Jak u klienta”: strony PDF zatwierdzonej wersji; brak = plik Word. */
  previewApprovedPdf?: (version: number) => Promise<Blob>;
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
    draftPdf: (payload) =>
      postAuthenticatedDownload(`${basePath}/preview-pdf`, payload).then((file) => file.blob),
    // Strony PDF wersji ma tylko CV etapu; edytor wyniku generatora pokazuje
    // wtedy plik Word (`CvPagesPreview`).
    previewApprovedPdf: basePath.includes("/cv/branded")
      ? (version) => fetchAuthenticatedBlob(`${basePath}/versions/${version}/pdf`)
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
   * Panel otwarty od razu: „Sprawdź i popraw” z karty „CV do klienta” otwiera
   * edytor na „Do poprawy” (także w wąskim oknie, zamiast kartki).
   */
  initialPanel?: "issues";

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
  /** Harness: propozycje AI dla zaznaczenia z pamięci zamiast sieci. */
  aiApi?: CvEditorAiApi;
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
  aiApi,
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
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const issuesFirst = initialPanel === "issues";
  const [issuesOpen, setIssuesOpen] = useState(issuesFirst);
  // Który panel wygrywa, gdy obok kartki mieści się tylko jeden.
  const [lastSide, setLastSide] = useState<"sources" | "issues">(issuesFirst ? "issues" : "sources");
  const sideTouched = useRef(issuesFirst);
  const [issueCount, setIssueCount] = useState<CvIssueCount>(NO_ISSUES);
  const [narrowPane, setNarrowPane] = useState<"cv" | "sources" | "issues" | "plan" | "history">(
    issuesFirst ? "issues" : "cv",
  );
  // Pasek „polecenia dla całego CV” (wynik: plan zmian w panelu obok).
  const [commandOpen, setCommandOpen] = useState(false);
  const [body, setBody] = useState<HTMLElement | null>(null);
  // Kolumna kartki: w niej stoją dymek nad zaznaczeniem i karta propozycji AI.
  const [paper, setPaper] = useState<HTMLElement | null>(null);
  // „Pokaż w oryginale” z karty propozycji → „Szukaj w CV” w panelu źródeł.
  const [sourceSearch, setSourceSearch] = useState<{ text: string; nonce: number } | null>(null);
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
  /** „Jak u klienta”: strony PDF z tego samego pliku co „Pobierz”. */
  const loadPagesPreview = async (): Promise<Blob> => {
    const session = sessionRef.current;
    if (!session) throw new Error("Edytor nie wczytał jeszcze CV.");
    await session.settle();
    if (session.state === "finalized" && data?.docx_available) {
      if (!files.previewApprovedPdf) throw new Error("Brak stron PDF dla tej wersji.");
      return files.previewApprovedPdf(data.version);
    }
    if (!files.draftPdf) throw new Error("Brak stron PDF dla tego CV.");
    return files.draftPdf({ content_html: session.html, expected_revision: session.revision });
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
    saved: "Zapisano",
    unsaved: "Niezapisane zmiany",
    saving: "Zapisywanie…",
    error: "Błąd zapisu — poprawki pozostają w edytorze",
    finalizing: "Zapisywanie…",
    finalized: `Zatwierdzona wersja ${data?.version ?? ""} — zmiana utworzy nowy szkic`,
  }[saveState];

  const language: CvLang = data?.language === "en" ? "en" : "pl";
  const textAlign = normalizeCvAlign(data?.text_align);
  const hasCv = !!data && !noCv;
  const command = useCvCommandPlan({
    editor,
    stageId: isGenerated ? undefined : stageId,
    // Bez `creatingDraft` — jak przy AI na zaznaczeniu: szkic zakłada samo „Zastosuj”.
    disabled: !hasCv || mode === "word" || submitting,
    ensureDraft,
    api: commandApi,
  });
  const planOpen = command.phase !== "idle";
  useEffect(() => {
    // Bez zgłaszania „update”: Tiptap domyślnie zgłasza je przy każdej zmianie
    // trybu edycji, a dla okna to znaczy „treść się zmieniła”. „Zapisz” na
    // zatwierdzonym CV bez żadnej poprawki zakładało przez to nowy szkic.
    // Plan zmian odnosi się do treści z chwili zamówienia — do decyzji kartka
    // jest tylko do odczytu.
    editor?.setEditable(!noCv && !submitting && !command.locked, false);
  }, [editor, noCv, submitting, command.locked]);
  const ai = useCvSelectionAi({
    editor,
    stageId: isGenerated ? undefined : stageId,
    // Bez `creatingDraft`: szkic na zatwierdzonej wersji zakłada samo „Przyjmij”,
    // a zakres czekający na propozycję przeżywa wczytanie tej samej treści.
    disabled: !hasCv || mode === "word" || submitting || command.locked,
    ensureDraft,
    api: aiApi,
  });
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
  const issuesSide = hasIssuesPanel && issuesOpen && (bothPanels || !sourcesOpen || lastSide === "issues");
  const sourcesSide = sourcesOpen && (bothPanels || !issuesSide);
  const pane =
    (narrowPane === "issues" && !hasIssuesPanel) ||
    (narrowPane === "plan" && !planOpen) ||
    (narrowPane === "history" && !historyOpen)
      ? "cv"
      : narrowPane;
  // Plan zmian i historia (jedno albo drugie) zajmują miejsce panelu „Do poprawy”;
  // przy jednym panelu naraz także źródeł.
  const takeover = planOpen || historyOpen;
  const showPlan = planOpen && (sideBySide || pane === "plan");
  const showHistory = historyOpen && !planOpen && (sideBySide || pane === "history");
  const showSources = hasCv && (sideBySide ? sourcesSide && (bothPanels || !takeover) : pane === "sources");
  const showIssues = hasIssuesPanel && !takeover && (sideBySide ? issuesSide : pane === "issues");
  const showCv = sideBySide || pane === "cv" || !hasCv;
  // Wąski ekran: plan pokazuje się od razu, a po decyzji wraca kartka.
  useEffect(() => {
    setNarrowPane((current) => (planOpen ? "plan" : current === "plan" ? "cv" : current));
  }, [planOpen]);
  useEffect(() => {
    setNarrowPane((current) => (historyOpen ? "history" : current === "history" ? "cv" : current));
  }, [historyOpen]);
  const closeCommand = () => {
    command.discard();
    setCommandOpen(false);
  };
  // Historia i polecenie wykluczają się: otwarcie jednego zamyka drugie.
  const openCommand = () => {
    history.close();
    setCommandOpen(true);
  };
  const openHistory = () => {
    closeCommand();
    history.show();
  };
  // Zlecone wyszukanie cytatu dotyczy tego pokazania źródeł: po ich schowaniu
  // wygasa, żeby ponowne otwarcie nie szukało starego cytatu od nowa.
  useEffect(() => {
    if (!showSources) setSourceSearch(null);
  }, [showSources]);
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
  const showSourceQuote = (quote: string) => {
    // Wyszukiwarka PDF-a gubi się na łamaniu wierszy — wystarczy początek cytatu.
    const text = quote.split(/\s+/).slice(0, 8).join(" ").slice(0, 60);
    setSourceSearch({ text, nonce: Date.now() });
    sideTouched.current = true;
    setSourcesOpen(true);
    setLastSide("sources");
    setNarrowPane("sources");
  };
  const issuesLabel =
    issueCount.state === "ready"
      ? `Do poprawy (${issueCount.total})`
      : issueCount.state === "failed"
        ? "Do poprawy (?)"
        : "Do poprawy";
  const sources = isGenerated ? (
    <CvEditorSources context={sourceContext ?? null} loaders={sourceLoaders} />
  ) : (
    <CvEditorSources
      stageId={stageId}
      context={sourceContext ?? undefined}
      loaders={sourceLoaders}
      search={sourceSearch}
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
            // Escape w karcie propozycji AI odrzuca propozycję (robi to sama karta).
            // W pasku polecenia i w planie zmian Escape też nie zamyka edytora —
            // także gdy plan się liczy: pole polecenia jest wtedy wyłączone,
            // więc klawisz trafia w `body`, nie w pasek.
            if (
              planOpen ||
              target.closest(".ProseMirror") ||
              target.closest(`[${CV_AI_CARD_ATTR}]`) ||
              target.closest(`[${CV_COMMAND_ATTR}]`)
            ) {
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
              {command.phase === "plan" ? (
                // Telefon: to samo zdanie stoi w nagłówku panelu planu, a plakietka ściskała tytuł.
                <Badge variant="warning" size="sm" className="hidden sm:inline-flex">
                  Podgląd zmian — nic nie jest jeszcze zapisane
                </Badge>
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
              {/* Z przekazaniem „Zapisz” stoi w stopce obok „Zapisz i przekaż do DL”. */}
              {handoff && hasCv ? null : (
                <Button
                  size="sm"
                  onClick={() => void saveAndApprove()}
                  disabled={!data || noCv || submitting || creatingDraft}
                >
                  {submitting ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <Save className="h-3.5 w-3.5 mr-1.5" />}
                  Zapisz
                </Button>
              )}
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
              <CvEditorToolbar
                editor={editor}
                language={language}
                defaultAlign={textAlign}
                disabled={mode === "word" || submitting || command.locked}
                ai={ai}
              />
              {/* Wąski ekran: przełączniki w osobnym wierszu — pasek narzędzi nie traci na nie miejsca. */}
              <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1", sideBySide ? "flex-none" : "basis-full")}>
              <div className="flex flex-none items-center gap-1" role="group" aria-label="Widok CV">
                <ViewToggle active={mode === "edit"} onClick={() => setMode("edit")}>Edycja</ViewToggle>
                <ViewToggle active={mode === "word"} onClick={() => { setMode("word"); setNarrowPane("cv"); }}>
                  Jak u klienta
                </ViewToggle>
              </div>
              {!isGenerated ? (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-pressed={commandOpen}
                  disabled={mode === "word" || submitting || history.busy}
                  title="Polecenie własnymi słowami dla całego CV"
                  className={cn("flex-none", commandOpen && "bg-primary/10 text-primary hover:bg-primary/10")}
                  onClick={() => (commandOpen ? closeCommand() : openCommand())}
                >
                  <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                  Polecenie
                </Button>
              ) : null}
              {!isGenerated ? (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-pressed={historyOpen}
                  // Plan zmian czeka na decyzję — najpierw „Zastosuj” albo „Odrzuć plan”.
                  disabled={mode === "word" || submitting || planOpen || history.busy}
                  title="Zatwierdzone wersje CV i poprawiony plik Word"
                  className={cn("flex-none", historyOpen && "bg-primary/10 text-primary hover:bg-primary/10")}
                  onClick={() => (historyOpen ? history.close() : openHistory())}
                >
                  <History className="h-3.5 w-3.5 mr-1.5" />
                  Historia
                </Button>
              ) : null}
              {sideBySide ? (
                <div className="flex flex-none items-center gap-1">
                  <Button size="sm" variant="ghost" aria-pressed={sourcesSide} onClick={toggleSources}>
                    <PanelLeft className="h-3.5 w-3.5 mr-1.5" />
                    {sourcesSide ? "Ukryj źródła" : "Pokaż źródła"}
                  </Button>
                  {hasIssuesPanel ? (
                    // Włączony tylko, gdy panel faktycznie widać: plan zmian i historia
                    // zajmują jego miejsce. Klik przy otwartej historii zamyka ją
                    // i pokazuje uwagi (planu nie — ten czeka na decyzję).
                    <Button size="sm" variant="ghost" aria-pressed={issuesSide && !takeover}
                      // Plan zmian czeka na decyzję — do tego czasu nie przełączamy panelu pod nim.
                      disabled={planOpen}
                      onClick={() => {
                        if (!historyOpen) return toggleIssues();
                        history.close();
                        sideTouched.current = true;
                        setIssuesOpen(true);
                        setLastSide("issues");
                      }}
                      className={cn(
                        issuesSide && !takeover && "bg-primary/10 text-primary hover:bg-primary/10",
                        !(issuesSide && !takeover) && issueCount.blocking > 0 && "text-destructive",
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
                  {hasIssuesPanel && !takeover ? (
                    <ViewToggle active={pane === "issues"} onClick={() => setNarrowPane("issues")}>{issuesLabel}</ViewToggle>
                  ) : null}
                  {planOpen ? (
                    <ViewToggle active={pane === "plan"} onClick={() => setNarrowPane("plan")}>Plan zmian</ViewToggle>
                  ) : null}
                  {historyOpen && !planOpen ? (
                    <ViewToggle active={pane === "history"} onClick={() => setNarrowPane("history")}>Historia</ViewToggle>
                  ) : null}
                </div>
              )}
              </div>
            </div>
          ) : null}
          {hasCv && editor && commandOpen && mode === "edit" ? (
            <CvEditorCommandBar controller={command} onClose={closeCommand} />
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
              ref={setPaper}
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
                  {editor && mode === "edit" ? (
                    <CvEditorSelectionAi
                      editor={editor}
                      controller={ai}
                      container={paper}
                      cvLanguage={language}
                      onShowSource={showSourceQuote}
                    />
                  ) : null}
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
                  readOnly={mode === "word" || submitting || creatingDraft || command.locked}
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
            {showPlan ? (
              <aside
                className={cn(
                  "min-h-0 min-w-0 bg-card",
                  sideBySide ? "w-[360px] flex-none border-l border-border" : "flex-1",
                )}
              >
                <CvEditorPlan controller={command} onShowCv={sideBySide ? undefined : () => setNarrowPane("cv")} />
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
              disabled={!data || creatingDraft}
              error={handoffError}
              onSave={() => void saveAndApprove()}
              onHandOff={() => void saveAndHandOff()}
              onOverride={openOverride}
            />
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
