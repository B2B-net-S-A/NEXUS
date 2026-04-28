"use client";

/**
 * CVBrandedEditModal — edytor brandowanego CV per rekrutacja (Tiptap +
 * autosave + finalize). Mirror `DraftEditor` z `CandidateDetailV2.tsx:1288`.
 *
 * PR2 — Faza 5. Lazy render przez backend GET /cv/branded — pierwszy raz
 * generuje template z `_generate_cv_html()`. PATCH save / re-render. POST
 * finalize → snapshot do storage_service, status `draft → finalized`,
 * dalsze edycje 409.
 */

import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import {
  CheckCircle2,
  Loader2,
  Printer,
  RefreshCcw,
  Sparkles,
  AlertCircle,
} from "lucide-react";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/Toast";
import {
  candidateStageCvApi,
  type CVBrandedState,
  type CVTemplate,
  type CVLanguage,
} from "@/lib/api";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  stageId: number;
  candidateName: string;
  jobTitle?: string;
}

function getErrorMessage(e: unknown): string {
  return (
    (e as { response?: { data?: { detail?: string } } })?.response?.data
      ?.detail ?? "Nie udało się wykonać operacji"
  );
}

export function CVBrandedEditModal({
  open,
  onOpenChange,
  stageId,
  candidateName,
  jobTitle,
}: Props) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [confirmFinalize, setConfirmFinalize] = useState(false);
  const [pendingTemplate, setPendingTemplate] = useState<CVTemplate | null>(
    null,
  );
  const [pendingLanguage, setPendingLanguage] = useState<CVLanguage | null>(
    null,
  );

  const { data, isLoading } = useQuery<CVBrandedState>({
    queryKey: ["cv-branded", stageId],
    queryFn: () =>
      candidateStageCvApi.branded.get(stageId).then((r) => r.data),
    enabled: open,
  });

  const editor = useEditor({
    extensions: [StarterKit],
    content: "",
    editorProps: {
      attributes: {
        class:
          "prose prose-sm max-w-none min-h-[400px] focus:outline-none border border-[hsl(var(--border-subtle))] rounded-v2-m bg-white p-4",
      },
    },
  });

  // Hydrate editor when data loads or template is swapped.
  const lastLoadedSig = useRef<string | null>(null);
  useEffect(() => {
    if (!editor || !data) return;
    const sig = `${data.template ?? ""}:${data.language ?? ""}:${data.updated_at ?? ""}`;
    if (sig === lastLoadedSig.current) return;
    lastLoadedSig.current = sig;
    editor.commands.setContent(data.content_html ?? "<p></p>", false);
  }, [editor, data]);

  // Disable editor when finalized.
  useEffect(() => {
    if (!editor) return;
    editor.setEditable(data?.status !== "finalized");
  }, [editor, data?.status]);

  // Debounced autosave for manual edits.
  const dirtyRef = useRef(false);
  const saveMut = useMutation({
    mutationFn: (html: string) =>
      candidateStageCvApi.branded.update(stageId, { content_html: html }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cv-branded", stageId] });
    },
    onError: (e) => showError(getErrorMessage(e)),
  });

  useEffect(() => {
    if (!editor) return;
    const handler = () => {
      if (data?.status === "finalized") return;
      dirtyRef.current = true;
    };
    editor.on("update", handler);
    return () => {
      editor.off("update", handler);
    };
  }, [editor, data?.status]);

  useEffect(() => {
    if (!editor) return;
    const id = setInterval(() => {
      if (
        dirtyRef.current &&
        !saveMut.isPending &&
        data?.status !== "finalized"
      ) {
        dirtyRef.current = false;
        saveMut.mutate(editor.getHTML());
      }
    }, 2000);
    return () => clearInterval(id);
  }, [editor, saveMut, data?.status]);

  const swapMut = useMutation({
    mutationFn: (payload: { template?: CVTemplate; language?: CVLanguage }) =>
      candidateStageCvApi.branded.update(stageId, payload),
    onSuccess: () => {
      showSuccess("Wczytano nowy szablon");
      lastLoadedSig.current = null; // force editor re-hydration
      queryClient.invalidateQueries({ queryKey: ["cv-branded", stageId] });
      setPendingTemplate(null);
      setPendingLanguage(null);
    },
    onError: (e) => showError(getErrorMessage(e)),
  });

  const finalizeMut = useMutation({
    mutationFn: () => candidateStageCvApi.branded.finalize(stageId),
    onSuccess: () => {
      showSuccess("Brandowane CV sfinalizowane");
      queryClient.invalidateQueries({ queryKey: ["cv-branded", stageId] });
      setConfirmFinalize(false);
    },
    onError: (e) => showError(getErrorMessage(e)),
  });

  const handleTemplateChange = (val: CVTemplate) => {
    if (data?.status === "finalized") return;
    if (val === data?.template) return;
    setPendingTemplate(val);
  };

  const handleLanguageChange = (val: CVLanguage) => {
    if (data?.status === "finalized") return;
    if (val === data?.language) return;
    setPendingLanguage(val);
  };

  const confirmSwap = () => {
    const payload: { template?: CVTemplate; language?: CVLanguage } = {};
    if (pendingTemplate) payload.template = pendingTemplate;
    if (pendingLanguage) payload.language = pendingLanguage;
    swapMut.mutate(payload);
  };

  const handlePrint = () => {
    window.open(candidateStageCvApi.branded.printableUrl(stageId), "_blank");
  };

  const isFinalized = data?.status === "finalized";

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent size="2xl" className="p-0 max-h-[92vh] flex flex-col">
          <div className="flex items-center justify-between px-5 py-3 border-b border-[hsl(var(--border-subtle))]">
            <div className="min-w-0">
              <div className="text-xs uppercase tracking-wider text-[hsl(var(--text-muted))]">
                Brandowane CV (per rekrutacja)
              </div>
              <div className="text-sm font-medium text-[hsl(var(--text-title))] truncate">
                {candidateName}
                {jobTitle ? (
                  <span className="text-[hsl(var(--text-muted))] font-normal">
                    {" "}
                    — {jobTitle}
                  </span>
                ) : null}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {isFinalized ? (
                <Badge variant="success" size="sm">
                  <CheckCircle2 className="h-3 w-3 mr-1" />
                  Sfinalizowane
                </Badge>
              ) : data?.status === "draft" ? (
                <Badge variant="info" size="sm">
                  Draft
                </Badge>
              ) : null}
            </div>
          </div>

          <div className="px-5 py-3 border-b border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-canvas))]">
            <div className="flex items-end gap-3 flex-wrap">
              <div>
                <Label className="text-[10px] uppercase">Szablon</Label>
                <Select
                  value={pendingTemplate ?? data?.template ?? "standard"}
                  onValueChange={(v) => handleTemplateChange(v as CVTemplate)}
                  disabled={isFinalized}
                >
                  <SelectTrigger className="w-36 h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="standard">Pełny (z kontaktem)</SelectItem>
                    <SelectItem value="blind">Anonimowy (blind)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-[10px] uppercase">Język</Label>
                <Select
                  value={pendingLanguage ?? data?.language ?? "pl"}
                  onValueChange={(v) => handleLanguageChange(v as CVLanguage)}
                  disabled={isFinalized}
                >
                  <SelectTrigger className="w-24 h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="pl">PL</SelectItem>
                    <SelectItem value="en">EN</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {(pendingTemplate || pendingLanguage) && !isFinalized ? (
                <div className="flex items-center gap-2 text-xs">
                  <Button
                    size="sm"
                    onClick={confirmSwap}
                    disabled={swapMut.isPending}
                  >
                    {swapMut.isPending ? (
                      <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                    ) : (
                      <RefreshCcw className="h-3 w-3 mr-1" />
                    )}
                    Wczytaj nowy szablon (nadpisze edycje)
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setPendingTemplate(null);
                      setPendingLanguage(null);
                    }}
                  >
                    Anuluj
                  </Button>
                </div>
              ) : null}
              <div className="ml-auto flex items-center gap-2">
                {saveMut.isPending ? (
                  <span className="text-[11px] text-[hsl(var(--text-muted))] flex items-center gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Zapisywanie…
                  </span>
                ) : data?.updated_at && !isFinalized ? (
                  <span className="text-[11px] text-[hsl(var(--text-muted))]">
                    Zapisano automatycznie
                  </span>
                ) : null}
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-auto p-5 bg-[hsl(var(--bg-canvas))]">
            {isLoading ? (
              <div className="text-center text-sm text-[hsl(var(--text-muted))] py-10">
                Ładowanie…
              </div>
            ) : (
              <EditorContent editor={editor} />
            )}
          </div>

          <div className="flex items-center justify-between gap-2 px-5 py-3 border-t border-[hsl(var(--border-subtle))]">
            <Button
              variant="outline"
              size="sm"
              onClick={handlePrint}
              disabled={!data?.content_html}
            >
              <Printer className="h-3.5 w-3.5 mr-1.5" />
              Drukuj / PDF
            </Button>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onOpenChange(false)}
              >
                Zamknij
              </Button>
              <Button
                size="sm"
                onClick={() => setConfirmFinalize(true)}
                disabled={
                  isFinalized || !data?.content_html || finalizeMut.isPending
                }
              >
                <Sparkles className="h-3.5 w-3.5 mr-1.5" />
                Sfinalizuj
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {confirmFinalize ? (
        <Dialog open onOpenChange={() => setConfirmFinalize(false)}>
          <DialogContent size="md">
            <div className="p-5 space-y-3">
              <div className="flex items-start gap-3">
                <AlertCircle className="h-5 w-5 text-amber-500 mt-0.5" />
                <div>
                  <h3 className="font-medium">Sfinalizować brandowane CV?</h3>
                  <p className="text-sm text-[hsl(var(--text-muted))] mt-1">
                    Po finalizacji CV będzie immutable — żeby zmienić, trzeba
                    będzie odwołać udostępnienia. Możesz wtedy generować
                    publiczne linki dla klienta.
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirmFinalize(false)}
                >
                  Anuluj
                </Button>
                <Button
                  size="sm"
                  onClick={() => finalizeMut.mutate()}
                  disabled={finalizeMut.isPending}
                >
                  {finalizeMut.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                  ) : null}
                  Sfinalizuj
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  );
}
