"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Clock, Download, Undo2 } from "lucide-react";

import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import type { B2BGeneratedContractRow } from "@/lib/api";
import { b2bEsignApi } from "@/lib/api/b2bEsign";
import { downloadBlob } from "@/lib/cv-generator";
import { cn } from "@/lib/utils";

function formatDay(value: string | null | undefined): string {
  if (!value) return "";
  return new Date(value).toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Europe/Warsaw",
  });
}

type Step = { label: string; state: "done" | "now" | "wait" };

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
    onSuccess: (res, requestId) => downloadBlob(res.data, `umowa_${requestId}_podpisana.pdf`),
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
  const e = row.esign;
  if (!e) return null;

  const closed = e.status === "withdrawn" || e.status === "expired";
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
      {closed ? (
        <p className="text-xs text-muted-foreground">
          {e.status === "expired" ? "Link wygasł" : "Wysyłka wycofana"} — można wysłać ponownie
          albo jak dotąd.
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
      {e.status === "sent" ? (
        <p className="text-xs text-muted-foreground">Link ważny do {formatDay(e.expires_at)}</p>
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
    </div>
  );
}
