"use client";

/**
 * „Karta przed CV (Word)” w edytorze reguły CV klienta (29.10.2026).
 *
 * Wgrany wzór = klient dostaje z każdym CV osobną kartę dostawcy (Credit
 * Agricole); usunięty = karty nie ma. Wzór zapisuje się od razu, osobno od
 * „Zapisz regułę” — plik leży w bazie (ma telefony opiekunów), nie w regule.
 */

import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileText, Loader2, Trash2, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  coverSheetTemplateKey,
  deleteCoverSheetTemplate,
  uploadCoverSheetTemplate,
  useCoverSheetTemplate,
} from "@/lib/api/coverSheet";

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function CoverSheetTemplateSection({ clientId }: { clientId: number }) {
  const queryClient = useQueryClient();
  // Komunikat w sekcji, nie toast — edytor reguły działa też bez ToastProvidera.
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<"upload" | "delete" | null>(null);
  const query = useCoverSheetTemplate(clientId);
  const template = query.data ?? null;

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setBusy("upload");
    setMessage(null);
    try {
      const next = await uploadCoverSheetTemplate(clientId, file);
      queryClient.setQueryData(coverSheetTemplateKey(clientId), next);
      setMessage({ tone: "ok", text: "Wzór karty zapisany — karta idzie teraz z każdym CV tego klienta." });
    } catch (error) {
      setMessage({ tone: "error", text: apiErrorMessage(error, "Nie udało się zapisać wzoru karty.") });
    } finally {
      setBusy(null);
      if (input.current) input.current.value = "";
    }
  };

  const remove = async () => {
    const ok = await askConfirm({
      title: "Usunąć wzór karty?",
      description: "Klient przestanie dostawać kartę przed CV. Poprawki DL-a w kartach osób zostają w bazie.",
      confirmLabel: "Usuń wzór",
      variant: "destructive",
    });
    if (!ok) return;
    setBusy("delete");
    setMessage(null);
    try {
      await deleteCoverSheetTemplate(clientId);
      queryClient.setQueryData(coverSheetTemplateKey(clientId), null);
    } catch (error) {
      setMessage({ tone: "error", text: apiErrorMessage(error, "Nie udało się usunąć wzoru karty.") });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="rounded-lg border" data-testid="cvrule-cover-sheet">
      <header className="flex items-center gap-3 border-b bg-muted/40 px-4 py-3">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
          <FileText className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold">Karta przed CV (Word)</p>
          <p className="text-xs text-muted-foreground">
            Gdy klient chce z każdym CV jednostronicową kartę dostawcy. Wgrany wzór włącza kartę w przeglądzie DL-a
            przed wysyłką; rekruter jej nie widzi, bo ma stawkę do klienta.
          </p>
        </div>
      </header>
      <div className="flex flex-col gap-3 p-4 text-sm">
        {query.isLoading ? (
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
            <Loader2 className="size-3.5 animate-spin" aria-hidden /> Sprawdzam wzór karty…
          </p>
        ) : query.isError ? (
          <p role="alert" className="text-xs text-destructive">
            {apiErrorMessage(query.error, "Nie udało się wczytać wzoru karty.")}{" "}
            <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
              Ponów
            </button>
          </p>
        ) : template ? (
          <div className="space-y-1">
            <p>
              <span className="font-medium">{template.filename}</span>{" "}
              <span className="text-xs text-muted-foreground">
                · {formatDate(template.uploaded_at)}
                {template.uploaded_by_name ? ` · ${template.uploaded_by_name}` : ""}
              </span>
            </p>
            <p className="text-xs text-muted-foreground">
              NEXUS rozpoznał: {template.fields.map((field) => field.label).join(", ")}.
            </p>
          </div>
        ) : query.isSuccess ? (
          <p className="text-xs text-muted-foreground">
            Bez wzoru — ten klient nie dostaje karty. Wzór to plik Word z etykietami „Rola:”, „Poziom doświadczenia:”,
            „Staż:”, „Profil kompetencji:”, „Dostępność:”, „Lokalizacja:”, „Wynagrodzenie:” i miejscem „xxx” na
            wartość.
          </p>
        ) : null}
        {message ? (
          <p
            role={message.tone === "error" ? "alert" : "status"}
            className={message.tone === "error" ? "text-xs text-destructive" : "text-xs text-muted-foreground"}
          >
            {message.text}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <input
            ref={input}
            type="file"
            accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            className="hidden"
            data-testid="cvrule-cover-sheet-input"
            onChange={(event) => void upload(event.target.files?.[0])}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy !== null || !query.isSuccess}
            onClick={() => input.current?.click()}
          >
            {busy === "upload" ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <Upload className="size-3.5" aria-hidden />
            )}
            {template ? "Podmień wzór" : "Wgraj wzór karty"}
          </Button>
          {template ? (
            <Button type="button" size="sm" variant="outline" disabled={busy !== null} onClick={() => void remove()}>
              {busy === "delete" ? (
                <Loader2 className="size-3.5 animate-spin" aria-hidden />
              ) : (
                <Trash2 className="size-3.5" aria-hidden />
              )}
              Usuń wzór
            </Button>
          ) : null}
        </div>
      </div>
      {confirmDialog}
    </section>
  );
}
