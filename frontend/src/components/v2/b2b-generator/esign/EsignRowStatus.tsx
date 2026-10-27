"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Check, Clock, Download, RefreshCw, Undo2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import type { B2BGeneratedContractRow } from "@/lib/api";
import { b2bEsignApi } from "@/lib/api/b2bEsign";
import { downloadBlob, parseDispositionFilename } from "@/lib/cv-generator";
import { cn } from "@/lib/utils";

import { EsignRenewDialog, type EsignRenewMode } from "./EsignRenewDialog";

function formatDay(value: string | null | undefined): string {
  if (!value) return "";
  return new Date(value).toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Europe/Warsaw",
  });
}

type Step = { label: string; state: "done" | "now" | "wait" };

/** Termin minął — także zanim pętla (co 30 min) zmieni stan na „expired”. */
export function esignLinkExpired(
  e: NonNullable<B2BGeneratedContractRow["esign"]>,
  now: Date = new Date(),
): boolean {
  return e.status === "expired" || (e.status === "sent" && new Date(e.expires_at) <= now);
}

/** Kroki podpisu w NEXUSIE w kolumnie „Podpis” (makieta 3). */
export function esignSteps(row: B2BGeneratedContractRow): Step[] {
  const e = row.esign;
  if (!e) return [];
  const signer = e.company_signer_name ?? "Firma";
  if (e.status === "sent") {
    return [
      { label: "Kontraktor", state: "now" },
      { label: signer, state: "wait" },
    ];
  }
  if (e.status === "contractor_signed") {
    return [
      { label: `Kontraktor · ${formatDay(e.contractor_signed_at)}`, state: "done" },
      { label: signer, state: "now" },
    ];
  }
  if (e.status === "completed") {
    return [
      { label: "Kontraktor", state: "done" },
      { label: `${signer} · ${formatDay(e.completed_at)}`, state: "done" },
    ];
  }
  return [];
}

/**
 * „Pobierz podpisaną umowę” — plik z podpisami obu stron w NEXUSIE. Gdy
 * automatyka nie założyła kontraktu (albo nie dołączyła pliku), nadawca oznacza
 * umowę ręcznie i dołącza właśnie ten plik, więc przycisk zostaje też przy
 * wierszu już oznaczonym jako podpisany (audyt 22.10, F45).
 */
export function EsignSignedPdfButton({ row }: { row: B2BGeneratedContractRow }) {
  const toast = useToast();
  const download = useMutation({
    mutationFn: (requestId: number) => b2bEsignApi.signedPdf(requestId),
    // Nazwę („Umowa B2B [nr] Nazwisko Imię”) układa serwer.
    onSuccess: (res) =>
      downloadBlob(
        res.data,
        parseDispositionFilename(
          String(res.headers?.["content-disposition"] ?? ""),
          "Umowa B2B podpisana.pdf",
        ),
      ),
    onError: (error) => toast.showError(apiErrorMessage(error, "Nie udało się pobrać pliku.")),
  });
  const e = row.esign;
  if (!e || e.status !== "completed" || !row.can_download_signed_esign) return null;
  return (
    <button
      type="button"
      onClick={() => download.mutate(e.request_id)}
      disabled={download.isPending}
      className="inline-flex items-center gap-1 text-xs text-primary hover:underline disabled:opacity-60"
    >
      <Download className="h-3 w-3" aria-hidden />
      Pobierz podpisaną umowę
    </button>
  );
}

export function EsignRowStatus({ row }: { row: B2BGeneratedContractRow }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const withdraw = useMutation({
    mutationFn: (requestId: number) =>
      b2bEsignApi.withdraw(requestId, "Przejście na drogę zwykłą"),
    onSuccess: () => {
      toast.showSuccess("Wysyłka wycofana — umowa wraca do drogi zwykłej.");
      // Rejestr, karta Tablicy (plakietka „U kontraktora…”) i lista na pulpicie.
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      queryClient.invalidateQueries({ queryKey: ["kanban"] });
      queryClient.invalidateQueries({ queryKey: ["board-tasks"] });
    },
    onError: (error) => toast.showError(apiErrorMessage(error, "Nie udało się wycofać.")),
  });
  const [renew, setRenew] = useState<EsignRenewMode | null>(null);
  const e = row.esign;
  if (!e) return null;

  const expired = esignLinkExpired(e);
  const closed = e.status === "withdrawn" || expired;
  const steps = esignSteps(row);
  const onWithdraw = async () => {
    const ok = await askConfirm({
      title: "Przejść na drogę zwykłą?",
      description: `Link kontraktora do umowy ${row.contract_number} przestanie działać. Umowę wyślesz mailem jak dotąd albo ponownie w NEXUSIE.`,
      confirmLabel: "Wycofaj wysyłkę",
      variant: "destructive",
    });
    if (ok) withdraw.mutate(e.request_id);
  };

  return (
    <div className="space-y-1">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">W NEXUSIE</p>
      {expired ? (
        <div className="space-y-1">
          <p className="inline-flex rounded-md border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 text-xs font-semibold text-destructive">
            Link wygasł {formatDay(e.expires_at)}
          </p>
          {e.renewal_requested_at ? (
            <p className="text-xs font-medium text-warning-muted-foreground">
              Kontraktor prosi o nowy link ({formatDay(e.renewal_requested_at)})
            </p>
          ) : null}
          {row.can_relink_esign ? (
            <>
              <button
                type="button"
                onClick={() => setRenew("relink")}
                className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
              >
                <RefreshCw className="h-3 w-3" aria-hidden />
                Wyślij nowy link
              </button>
              <p className="text-[11px] leading-snug text-muted-foreground">
                Ten sam PDF: podpisany już plik przejdzie.
              </p>
            </>
          ) : (
            <p className="text-xs text-muted-foreground">Można wysłać ponownie albo jak dotąd.</p>
          )}
        </div>
      ) : closed ? (
        <p className="text-xs text-muted-foreground">
          Wysyłka wycofana — można wysłać ponownie albo jak dotąd.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-1" aria-label="Kroki podpisu">
          {steps.map((step) => (
            <li
              key={step.label}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs",
                step.state === "done" && "border-success/30 bg-success-muted text-success-muted-foreground",
                step.state === "now" && "border-warning/40 bg-warning-muted font-semibold text-warning-muted-foreground",
                step.state === "wait" && "border-border text-muted-foreground",
              )}
            >
              {step.state === "done" ? (
                <Check className="h-3 w-3" aria-hidden />
              ) : step.state === "now" ? (
                <Clock className="h-3 w-3" aria-hidden />
              ) : null}
              {step.label}
            </li>
          ))}
        </ul>
      )}
      {e.status === "sent" && !expired ? (
        <p className="text-xs text-muted-foreground">Link ważny do {formatDay(e.expires_at)}</p>
      ) : null}
      {row.can_extend_esign && !expired ? (
        <button
          type="button"
          onClick={() => setRenew("extend")}
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
        >
          <CalendarPlus className="h-3 w-3" aria-hidden />
          Przedłuż termin
        </button>
      ) : null}
      {e.cc_names && e.cc_names.length > 0 ? (
        <p className="text-[11px] leading-snug text-muted-foreground">
          DW: <span className="text-foreground">{e.cc_names.join(", ")}</span>
        </p>
      ) : null}
      <EsignSignedPdfButton row={row} />
      {row.can_withdraw_esign ? (
        <button
          type="button"
          onClick={() => void onWithdraw()}
          disabled={withdraw.isPending}
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline disabled:opacity-60"
        >
          <Undo2 className="h-3 w-3" aria-hidden />
          Przejdź na zwykłą drogę
        </button>
      ) : null}
      {confirmDialog}
      {renew ? <EsignRenewDialog row={row} mode={renew} onClose={() => setRenew(null)} /> : null}
    </div>
  );
}
