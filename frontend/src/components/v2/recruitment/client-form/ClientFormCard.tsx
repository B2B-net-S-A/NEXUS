"use client";

/**
 * Karta „Formularz CV klienta” w sekcji CV osoby (0522, 26.10.2026).
 *
 * Klient bierze własny formularz CV (reguła CV klienta: „Dokument do klienta:
 * formularz”) — np. SWZ Centrum e-Zdrowia, inny w każdym przetargu. Wzór DL
 * dodaje do Plików rekrutacji; NEXUS wypełnia go z CV, screeningu i notatek,
 * a karta mówi, ile pól zostało do uzupełnienia. Decyzje Artura: CV firmowe
 * nie powstaje samo (zostaje link do generatora), braki nie blokują ruchu.
 *
 * Awaria odczytu to komunikat z „Ponów”, nigdy pusty stan.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, FileText, Loader2, Sparkles } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { ClientFormDialog } from "@/components/v2/recruitment/client-form/ClientFormDialog";
import { apiErrorMessage } from "@/lib/api-error";
import {
  clientFormFieldName,
  clientFormKey,
  downloadClientForm,
  fillClientForm,
  saveClientForm,
  useClientForm,
  type ClientFormView,
} from "@/lib/api/clientForms";
import type { ClientFormKind } from "@/lib/api/jobFiles";
import { cn } from "@/lib/utils";

export interface ClientFormCardProps {
  stageId: number;
  candidateName: string;
  readOnly?: boolean;
  /** Otwórz okno braków od razu (akcja „Uzupełnij formularz” z listy wymagań). */
  openDialog?: boolean;
  onOpenDialogChange?: (open: boolean) => void;
  /** Link „Wygeneruj też CV firmowe” — rekruter może je zrobić ręcznie (D2). */
  onGenerateCompanyCv?: () => void;
  className?: string;
  /** 0525: „score” — tabela punktowa klienta (Excel), pokazywana tylko, gdy jest wzór. */
  kind?: ClientFormKind;
}

const MISSING_PREVIEW = 4;

export function ClientFormCard({
  stageId,
  candidateName,
  readOnly = false,
  openDialog,
  onOpenDialogChange,
  onGenerateCompanyCv,
  className,
  kind = "form",
}: ClientFormCardProps) {
  const score = kind === "score";
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const query = useClientForm(stageId, true, kind);
  const [filling, setFilling] = useState(false);
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [localOpen, setLocalOpen] = useState(false);
  const dialogOpen = openDialog ?? localOpen;
  const setDialogOpen = onOpenDialogChange ?? setLocalOpen;

  const store = (view: ClientFormView) => {
    queryClient.setQueryData(clientFormKey(stageId, kind), view);
    // Tablica i lista wymagań liczą braki formularza z serwera.
    void queryClient.invalidateQueries({ queryKey: ["move-requirements"] });
    void queryClient.invalidateQueries({ queryKey: ["kanban"] });
  };

  const fill = async () => {
    setFilling(true);
    try {
      const view = await fillClientForm(stageId, kind);
      store(view);
      if (view.message) showError(view.message);
      else
        showSuccess(
          view.missing.length
            ? `${score ? "Tabela wypełniona" : "Formularz wypełniony"} — ${view.missing.length} do uzupełnienia.`
            : score
              ? "Tabela wypełniona."
              : "Formularz wypełniony.",
        );
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wypełnić formularza."));
    } finally {
      setFilling(false);
    }
  };

  const save = async (fields: Record<string, string>) => {
    setSaving(true);
    try {
      store(await saveClientForm(stageId, fields, kind));
      showSuccess(score ? "Zapisano tabelę." : "Zapisano formularz.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać formularza."));
    } finally {
      setSaving(false);
    }
  };

  const download = async (view: ClientFormView) => {
    setDownloading(true);
    try {
      await downloadClientForm(
        stageId,
        view.template?.filename ?? (score ? "tabela.xlsx" : "formularz.docx"),
        kind,
      );
    } catch {
      showError("Nie udało się pobrać formularza.");
    } finally {
      setDownloading(false);
    }
  };

  if (query.isPending) {
    return (
      <p className={cn("flex items-center gap-2 text-xs text-muted-foreground", className)}>
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> Wczytuję formularz klienta…
      </p>
    );
  }
  if (query.isError || !query.data) {
    return (
      <p role="alert" className={cn("text-xs text-destructive", className)}>
        Nie udało się wczytać formularza klienta.{" "}
        <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
          Ponów
        </button>
      </p>
    );
  }

  const view = query.data;
  if (view.client_document !== "client_form") return null;
  // Tabela punktowa jest dodatkiem do formularza — bez wzoru w Plikach jej nie ma.
  if (score && view.status === "no_template") return null;
  const total = view.fields.length;
  const missing = view.fields.filter((field) => view.missing.includes(field.id));
  const filledCount = total - missing.length;

  return (
    <section
      aria-label={score ? "Tabela punktowa klienta" : "Formularz CV klienta"}
      data-testid={score ? "client-score-card" : "client-form-card"}
      className={cn("space-y-2.5 rounded-lg border border-border bg-card p-3 text-xs", className)}
    >
      {score ? (
        <p className="text-muted-foreground">
          <span className="font-medium text-foreground">Tabela punktowa</span> — punkty według
          zasad oceny z Plików rekrutacji.
        </p>
      ) : (
        <p className="text-muted-foreground">
          Klient przyjmuje swój <span className="font-medium text-foreground">formularz CV</span>,
          nie CV firmowe.
        </p>
      )}
      {view.status === "no_template" ? (
        <p className="flex items-start gap-1.5 text-foreground" data-testid="client-form-no-template">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
          <span>
            W Plikach rekrutacji nie ma wzoru formularza — dodaje go Delivery Lead (menu „⋯” →
            „Pliki”).
          </span>
        </p>
      ) : (
        <>
          <div className="flex items-start gap-2 rounded-md border border-border px-2.5 py-2">
            <FileText className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-foreground" title={view.template?.filename}>
                {view.template?.filename}
              </p>
              <p className="text-muted-foreground">
                {view.status === "not_filled"
                  ? "Jeszcze nie wypełniony."
                  : "Wypełniony z CV, screeningu i notatek."}
              </p>
            </div>
          </div>
          {view.template_changed ? (
            <p className="flex items-start gap-1.5 text-warning-muted-foreground">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              Wzór w Plikach się zmienił — wypełnij {score ? "tabelę" : "formularz"} ponownie.
            </p>
          ) : null}
          {view.status === "filled" ? (
            <div className="space-y-1.5">
              <div className="flex justify-between gap-2">
                <span>
                  {score && view.points
                    ? `Punkty: ${view.points.total} z ${view.points.max}`
                    : `${filledCount} z ${total} pól wypełnionych`}
                </span>
                {missing.length ? (
                  <span className="font-medium text-warning-muted-foreground">
                    {missing.length} do uzupełnienia
                  </span>
                ) : (
                  <span className="flex items-center gap-1 font-medium text-success-muted-foreground">
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> gotowy
                  </span>
                )}
              </div>
              <div className="h-1.5 rounded-full bg-muted" aria-hidden>
                <div
                  className={cn("h-1.5 rounded-full", missing.length ? "bg-warning" : "bg-success")}
                  style={{ width: `${total ? Math.round((filledCount / total) * 100) : 0}%` }}
                />
              </div>
              {missing.length ? (
                <ul className="list-disc space-y-0.5 pl-4 text-foreground" data-testid="client-form-missing">
                  {missing.slice(0, MISSING_PREVIEW).map((field) => (
                    <li key={field.id} className="truncate" title={clientFormFieldName(field)}>
                      {clientFormFieldName(field)}
                    </li>
                  ))}
                  {missing.length > MISSING_PREVIEW ? (
                    <li className="list-none text-muted-foreground">
                      i {missing.length - MISSING_PREVIEW} więcej
                    </li>
                  ) : null}
                </ul>
              ) : null}
            </div>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {view.status === "filled" ? (
              <Button type="button" size="sm" onClick={() => setDialogOpen(true)}>
                {missing.length && !readOnly
                  ? "Uzupełnij braki"
                  : score
                    ? "Pokaż tabelę"
                    : "Pokaż formularz"}
              </Button>
            ) : null}
            {readOnly ? null : (
              <Button
                type="button"
                size="sm"
                variant={view.status === "filled" ? "outline" : "primary"}
                loading={filling}
                disabled={filling}
                title="Model wpisuje tylko to, co jest w CV, screeningu i notatkach — zwykle do minuty."
                onClick={() => void fill()}
              >
                <Sparkles className="h-3.5 w-3.5" aria-hidden />
                {view.status === "filled" ? "Wypełnij ponownie" : "Wypełnij z CV i screeningu"}
              </Button>
            )}
            {view.status === "filled" ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={downloading}
                onClick={() => void download(view)}
              >
                <Download className="h-3.5 w-3.5" aria-hidden />
                {score ? "Pobierz Excel" : "Pobierz Word"}
              </Button>
            ) : null}
          </div>
        </>
      )}
      {onGenerateCompanyCv && !readOnly && !score ? (
        <button
          type="button"
          className="text-muted-foreground underline hover:text-foreground"
          onClick={onGenerateCompanyCv}
        >
          Wygeneruj też CV firmowe
        </button>
      ) : null}
      {view.status === "filled" ? (
        <ClientFormDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          view={view}
          kind={kind}
          candidateName={candidateName}
          readOnly={readOnly}
          saving={saving}
          downloading={downloading}
          onSave={save}
          onDownload={() => void download(view)}
        />
      ) : null}
    </section>
  );
}

export default ClientFormCard;
