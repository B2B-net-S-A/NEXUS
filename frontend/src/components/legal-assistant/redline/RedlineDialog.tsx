"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, FileDiff, FileText, Loader2, Save, Scale, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { contractsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import {
  DOCX_MIME,
  acceptAll,
  acceptedChanges,
  aiStatusMessage,
  documentText,
  proposeRedline,
  renderRedline,
  summarize,
  type ChangeEdit,
  type Decision,
  type ProposeMode,
  type RedlineResponse,
  type RedlineTarget,
} from "@/lib/legal-redline";

import { RedlineReview } from "./RedlineReview";

export interface RedlineDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  target: RedlineTarget | null;
  /** Nazwa dokumentu w nagłówku okna. */
  title: string;
  /** „Zapisz w Dokumentach kontraktu” — tylko z prawem dodawania plików i przy znanym kontrakcie. */
  canSave: boolean;
  onSaved?: (filename: string) => void;
}

function targetContractId(target: RedlineTarget | null): number | null {
  return target ? target.contractId : null;
}

function pluralChanges(n: number): string {
  if (n === 1) return "1 zmiana";
  const last = n % 10;
  const lastTwo = n % 100;
  return `${n} ${last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14) ? "zmiany" : "zmian"}`;
}

/**
 * „Popraw dokument”: polecenie dla asystenta albo poprawiona treść do
 * porównania → tekst ze zmianami i lista „Przyjmij / Odrzuć / Zmień” →
 * DOCX ze śledzeniem zmian (pobranie albo zapis w Dokumentach kontraktu).
 * Nic nie wychodzi samo — plik zapisuje człowiek.
 */
export function RedlineDialog({ open, onOpenChange, target, title, canSave, onSaved }: RedlineDialogProps) {
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [result, setResult] = useState<RedlineResponse | null>(null);
  const [loading, setLoading] = useState<null | "open" | "ai" | "diff">(null);
  const [busy, setBusy] = useState<null | "download" | "save">(null);
  const [error, setError] = useState("");
  const [instruction, setInstruction] = useState("");
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareText, setCompareText] = useState("");
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [edits, setEdits] = useState<Record<string, ChangeEdit>>({});
  const [saved, setSaved] = useState(false);
  const loadedFor = useRef<RedlineTarget | null>(null);

  const run = async (mode: ProposeMode, phase: "open" | "ai" | "diff") => {
    if (!target) return;
    setLoading(phase);
    setError("");
    try {
      const next = await proposeRedline(target, mode);
      setResult((prev) =>
        phase === "open" || !prev ? next : { ...next, paragraphs: next.paragraphs.length ? next.paragraphs : prev.paragraphs },
      );
      if (phase !== "open") {
        setDecisions({});
        setEdits({});
        setSaved(false);
      }
      if (phase === "open") setCompareText(documentText(next.paragraphs));
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się otworzyć dokumentu."));
    } finally {
      setLoading(null);
    }
  };

  useEffect(() => {
    if (!open || !target || loadedFor.current === target) return;
    loadedFor.current = target;
    setResult(null);
    setDecisions({});
    setEdits({});
    setInstruction("");
    setCompareOpen(false);
    setSaved(false);
    void run({ mode: "manual" }, "open");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- jedno wczytanie na dokument
  }, [open, target]);

  const changes = useMemo(() => result?.changes ?? [], [result]);
  const summary = summarize(changes, decisions, edits);
  const accepted = acceptedChanges(changes, decisions, edits);
  const contractId = targetContractId(target);
  const statusMessage = result ? aiStatusMessage(result.ai.status, changes.length) : null;
  const reviewing = result != null && (result.ai.status !== "manual" || changes.length > 0);

  const close = async () => {
    if (accepted.length > 0 && !saved) {
      const ok = await askConfirm({
        title: "Zamknąć bez pliku?",
        description: `Przyjęte zmiany (${accepted.length}) nie trafiły jeszcze do pliku. Po zamknięciu trzeba je przejrzeć od nowa.`,
        confirmLabel: "Zamknij",
        variant: "destructive",
      });
      if (!ok) return;
    }
    loadedFor.current = null;
    onOpenChange(false);
  };

  const render = async () => {
    if (!target || !result) return null;
    return renderRedline(target, result.source.sha256, accepted);
  };

  const download = async () => {
    setBusy("download");
    setError("");
    try {
      const file = await render();
      if (file) downloadBlob(file.blob, file.filename);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się przygotować pliku DOCX."));
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    if (contractId == null) return;
    setBusy("save");
    setError("");
    try {
      const file = await render();
      if (!file) return;
      const fd = new FormData();
      fd.append("file", new File([file.blob], file.filename, { type: DOCX_MIME }));
      const docType = target?.kind === "contract-document" ? target.docType : null;
      fd.append("doc_type", docType || "other");
      await contractsApi.uploadDocument(contractId, fd);
      setSaved(true);
      onSaved?.(file.filename);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zapisać pliku w Dokumentach kontraktu."));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : void close())}>
      <DialogContent size="full" className="h-[calc(100dvh-2rem)] max-h-[calc(100dvh-2rem)] max-w-[1240px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileDiff className="size-4 text-muted-foreground" aria-hidden="true" />
            Popraw dokument
          </DialogTitle>
          <DialogDescription className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px]">
            <FileText className="size-3.5" aria-hidden="true" />
            <span className="font-medium text-foreground">{title}</span>
            <span aria-hidden="true">·</span>
            <span>wynik to DOCX ze śledzeniem zmian i komentarzami z podstawą</span>
          </DialogDescription>
        </DialogHeader>

        <div className="relative min-h-0 flex-1 space-y-3 overflow-y-auto px-6 py-4">
          {loading === "open" && !result && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" /> Czytam dokument…
            </p>
          )}

          {error && (
            <div role="alert" className="flex items-start gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">
              <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" /> {error}
            </div>
          )}

          {result && (
            <>
              <section className="space-y-2 rounded-lg border border-border bg-card p-3">
                <label htmlFor="redline-instruction" className="text-[12px] font-semibold text-muted-foreground">
                  Polecenie dla asystenta
                </label>
                <Textarea
                  id="redline-instruction"
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                  rows={2}
                  maxLength={4000}
                  placeholder="np. Dostosuj do aneksu DORA klienta: szkolenia z bezpieczeństwa ICT i zgłaszanie zdarzeń w 24 godziny"
                  className="text-[13px]"
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    disabled={!instruction.trim() || loading != null}
                    onClick={() => void run({ mode: "ai", instruction }, "ai")}
                  >
                    {loading === "ai" ? (
                      <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden="true" />
                    ) : (
                      <Sparkles className="mr-1.5 size-3.5" aria-hidden="true" />
                    )}
                    Zaproponuj zmiany
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setCompareOpen((v) => !v)} aria-expanded={compareOpen}>
                    {compareOpen ? "Schowaj porównanie" : "Wklej poprawioną treść i porównaj"}
                  </Button>
                  {reviewing && (
                    <Badge variant="info" size="sm" className="ml-auto">
                      {pluralChanges(summary.total)} · przyjęte {summary.accepted}
                    </Badge>
                  )}
                </div>
                {compareOpen && (
                  <div className="space-y-1.5 pt-1">
                    <p className="text-[12px] text-muted-foreground">
                      Każdy akapit w osobnym wierszu. Zmień treść tutaj albo wklej wersję od klienta — NEXUS policzy
                      różnice słowami, bez modelu.
                    </p>
                    <Textarea
                      aria-label="Poprawiona treść dokumentu"
                      value={compareText}
                      onChange={(e) => setCompareText(e.target.value)}
                      rows={8}
                      className="font-mono text-[12px]"
                    />
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={loading != null}
                      onClick={() => void run({ mode: "diff", newText: compareText }, "diff")}
                    >
                      {loading === "diff" && <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden="true" />}
                      Porównaj z oryginałem
                    </Button>
                  </div>
                )}
              </section>

              {statusMessage && (
                <p role="status" className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-[13px] text-muted-foreground">
                  {statusMessage}
                </p>
              )}

              <RedlineReview
                paragraphs={result.paragraphs}
                changes={changes}
                decisions={decisions}
                edits={edits}
                notes={result.notes}
                dropped={result.dropped}
                onDecide={(id, decision) => {
                  setSaved(false);
                  setDecisions((prev) => ({ ...prev, [id]: decision }));
                }}
                onEdit={(id, edit) => {
                  setSaved(false);
                  setEdits((prev) => ({ ...prev, [id]: edit }));
                }}
              />
            </>
          )}
        </div>

        {result && (
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-border px-6 py-3">
            <p className="mr-auto flex items-center gap-1.5 text-[12px] text-muted-foreground">
              <Scale className="size-3.5 shrink-0" aria-hidden="true" />
              Asystent nie jest poradą prawną. Kara umowna, spór z klientem, rozwiązanie ze skutkiem natychmiastowym — do
              prawnika.
            </p>
            {summary.pending > 0 && (
              <Button size="sm" variant="ghost" onClick={() => setDecisions((prev) => acceptAll(changes, prev, edits))}>
                Przyjmij wszystkie
              </Button>
            )}
            <Button size="sm" disabled={accepted.length === 0 || busy != null} onClick={() => void download()}>
              {busy === "download" ? (
                <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <FileDiff className="mr-1.5 size-3.5" aria-hidden="true" />
              )}
              Pobierz DOCX ze śledzeniem zmian
            </Button>
            {canSave && contractId != null && (
              <Button
                size="sm"
                variant="outline"
                disabled={accepted.length === 0 || busy != null || saved}
                onClick={() => void save()}
              >
                {busy === "save" ? (
                  <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <Save className="mr-1.5 size-3.5" aria-hidden="true" />
                )}
                {saved ? "Zapisano w Dokumentach" : "Zapisz w Dokumentach kontraktu"}
              </Button>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
    {confirmDialog}
    </>
  );
}
