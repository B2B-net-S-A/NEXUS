"use client";

/**
 * CVBrandedEditModal — edytor CV do klienta (Tiptap + autosave).
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
 */

import { useState, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { CvEditorSection } from "@/lib/cv-editor-section";
import {
  Loader2,
  Printer,
  Download,
  RefreshCcw,
  Save,
  Sparkles,
  AlertCircle,
} from "lucide-react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CvDraftSession, type CvSaveState } from "@/lib/cv-draft-session";
import { useToast } from "@/components/Toast";
import {
  openAuthenticatedFile,
  downloadAuthenticatedFile,
  postAuthenticatedDownload,
  downloadBlob,
} from "@/lib/authenticated-files";
import {
  candidateStageCvApi,
  cvGeneratedEditorApi,
  type CVBrandedState,
} from "@/lib/api";
import {
  generatedApprovalKey,
  stageApprovalKey,
  startBackgroundApproval,
} from "@/lib/cv-background-approval";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Otwiera generator (np. etap bez CV albo CV bez źródeł do edycji). */
  onRegenerate?: () => void;

  candidateName: string;
  jobTitle?: string;
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
}: Props) {
  const stageId = (generatedId ?? pipelineStageId)!;
  const isGenerated = generatedId !== undefined;
  const scopeKey = isGenerated ? "cv-generated-editor" : "cv-branded";
  const editorApi = isGenerated ? cvGeneratedEditorApi : candidateStageCvApi.branded;
  const basePath = isGenerated ? `/api/cv-generator/generated/${generatedId}/editor` : `/api/candidates/stages/${stageId}/cv/branded`;
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

  const { data, isLoading, error: loadError, refetch, isFetching } = useQuery<CVBrandedState>({
    queryKey: [scopeKey, stageId],
    queryFn: () => editorApi.get(stageId).then((r) => r.data),
    enabled: open,
  });
  // Etap bez CV: backend nie składa już treści ze starego szablonu.
  const noCv = data?.status === "none";

  const editor = useEditor({
    immediatelyRender: false,
    extensions: [StarterKit, CvEditorSection],
    content: "",
    editorProps: {
      attributes: {
        class: "prose prose-sm max-w-none min-h-[400px] focus:outline-hidden border border-border rounded-lg bg-card p-4",
      },
    },
  });

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
    editor?.commands.setContent(session.html, { emitUpdate: false });
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
    editor?.setEditable(!noCv && !submitting);
  }, [editor, noCv, submitting]);

  const startNewDraft = () => {
    const session = sessionRef.current;
    if (!session || newDraftRef.current) return;
    setCreatingDraft(true);
    newDraftRef.current = editorApi.newDraft(stageId, session.revision)
      .then((response) => {
        // Tekst wpisany w zatwierdzoną wersję przechodzi do nowego szkicu.
        const typed = editor?.getHTML() ?? null;
        loadState(response.data);
        if (typed != null && typed !== sessionRef.current?.html) {
          editor?.commands.setContent(typed, { emitUpdate: false });
          sessionRef.current?.edit(typed);
        }
      })
      .catch((error: unknown) => {
        showError(`Nie udało się utworzyć nowej wersji: ${getErrorMessage(error)}`);
        // Zmiana nie trafiła do żadnego szkicu — wracamy do zatwierdzonej treści.
        if (sessionRef.current) editor?.commands.setContent(sessionRef.current.html, { emitUpdate: false });
      })
      .finally(() => {
        newDraftRef.current = null;
        setCreatingDraft(false);
      });
  };
  const startNewDraftRef = useRef(startNewDraft);
  startNewDraftRef.current = startNewDraft;

  useEffect(() => {
    if (!editor) return;
    const handler = () => {
      const session = sessionRef.current;
      if (!session) return;
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

  // Print view is Bearer-guarded — a raw window.open sends no Authorization
  // header and lands on a white "Not authenticated" page. Fetch the HTML with
  // auth and open it as a same-origin blob URL (its inline window.print() runs).
  const handlePrint = async () => {
    try {
      await flush();
      await openAuthenticatedFile(`${basePath}/render-pdf`, "text/html");
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
      const result = await postAuthenticatedDownload(
        `${basePath}/preview-docx`,
        {content_html: session.html, expected_revision: session.revision},
      );
      downloadBlob(result.blob, result.filename || "SZKIC_CV.docx");
    } catch (error) { showError(getErrorMessage(error)); }
    finally { setDownloadingDocx(false); }
  };
  const downloadApproved = async () => {
    if (!data?.docx_available) return;
    setDownloadingDocx(true);
    try {
      await downloadAuthenticatedFile(
        `${basePath}/versions/${data.version}/docx`,
        data.docx_filename || "CV.docx",
      );
    } catch (error) { showError(getErrorMessage(error)); }
    finally { setDownloadingDocx(false); }
  };

  const statusText = {
    saved: "Zapisano",
    unsaved: "Niezapisane zmiany",
    saving: "Zapisywanie…",
    error: "Błąd zapisu — poprawki pozostają w edytorze",
    finalizing: "Zapisywanie…",
    finalized: `Zatwierdzona wersja ${data?.version ?? ""} — zmiana utworzy nowy szkic`,
  }[saveState];

  return (
    <>
      <Dialog open={open} onOpenChange={(value) => void closeEditor(value)}>
        <DialogContent size="2xl" className="p-0 max-h-[92dvh] flex flex-col">
          {saveProblem && <div role="alert" className="pl-5 pr-16 py-3 border-b border-border text-sm space-y-2">
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
          <div className="flex items-center justify-between gap-3 pl-5 pr-16 py-3 border-b border-border">
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
            <div className="flex items-center gap-2">
              {data?.status === "draft" ? (
                <Badge variant="info" size="sm">Szkic v{data?.version ?? 1}</Badge>
              ) : null}
            </div>
          </div>

          {data?.presentation_review?.status === "conflict" && <p role="alert" className="px-5 py-2 text-sm text-destructive">
            Reguły klienta dla zapisanego szkicu: {data.presentation_review.message}
          </p>}
          {data?.presentation_review?.status === "needs_review" && <p className="px-5 py-2 text-xs text-muted-foreground">
            {data.presentation_review.reason === "rule_snapshot_unavailable"
              ? "Brak potwierdzonej kopii reguł klienta dla tego CV. Sprawdź wymagania klienta przed wysyłką."
              : `Przed wysyłką sprawdź ręcznie: ${(data.presentation_review.manual_fields ?? []).map(field => MANUAL_FIELD_LABELS[field] ?? "dodatkową regułę klienta").join(", ") || "reguły klienta"}. Automatyczna kontrola nie potwierdziła tych reguł.`}
          </p>}
          {!noCv && data ? (
            <div className="flex items-center justify-end gap-2 px-5 py-2 border-b border-border bg-background">
              <span className="text-[11px] text-muted-foreground" role="status">
                {creatingDraft ? "Tworzenie nowego szkicu…" : statusText}
              </span>
              {saveState === "error" ? <Button size="sm" variant="outline" onClick={() => void saveCurrent()}>Ponów zapis</Button> : null}
            </div>
          ) : null}

          <div className="flex-1 overflow-auto p-5 bg-background">
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
              <EditorContent editor={editor} />
            ) : null}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 border-t border-border">
            <Button
              variant="outline"
              size="sm"
              onClick={handlePrint}
              disabled={!data?.content_html || noCv}
            >
              <Printer className="h-3.5 w-3.5 mr-1.5" />
              Drukuj / PDF
            </Button>
            <div className="flex flex-wrap items-center gap-2">
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
