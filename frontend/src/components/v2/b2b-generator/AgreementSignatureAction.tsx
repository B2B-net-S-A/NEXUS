"use client";

/**
 * Podpis umowy z panelu osoby (04.10.2026, decyzja Artura D1).
 *
 * Z uprawnieniem „Podpis B2B” (`row.can_confirm_signed`) — to samo okno co
 * w rejestrze Generatora: zakłada kontrakt i zamówienie i przesuwa kartę na
 * „Zatrudniony”. Bez niego rekruter prosi Delivery Leada (dzwonek i sprawa
 * na jego pulpicie); prośba wysłana w ciągu doby nie idzie drugi raz.
 */

import dynamic from "next/dynamic";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { b2bGeneratorApi, type B2BGeneratedContractRow } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatIsoDatePl } from "@/lib/date-pl";

const ConfirmFullySignedDialog = dynamic(
  () =>
    import("@/components/v2/pages/B2BContractGeneratorV2").then(
      (m) => m.ConfirmFullySignedDialog,
    ),
  { ssr: false },
);

/** Klucze odświeżane po podpisie albo prośbie — karta, panel, pulpit, rejestr. */
export function invalidateAgreementQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  jobId: number,
): void {
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  void queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
  void queryClient.invalidateQueries({ queryKey: ["board-tasks"] });
}

export function AgreementSignatureAction({
  row,
  jobId,
  requestedAt,
  readOnly,
  size = "sm",
}: {
  row: B2BGeneratedContractRow;
  jobId: number;
  /** `signature_requested_at` z karty Tablicy (`item.agreement`). */
  requestedAt?: string | null;
  readOnly: boolean;
  size?: "sm" | "md";
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sentAt, setSentAt] = useState<string | null>(null);

  if (readOnly) return null;
  if (row.signature_status === "signed_both" || row.contract_status !== "in_progress") {
    return null;
  }

  if (row.can_confirm_signed) {
    return (
      <>
        <Button size={size} onClick={() => setOpen(true)}>
          Oznacz jako podpisaną…
        </Button>
        {open ? (
          <ConfirmFullySignedDialog
            row={row}
            open={true}
            onOpenChange={(v: boolean) => {
              if (!v) setOpen(false);
            }}
            onConfirmed={(result) => {
              setOpen(false);
              showSuccess(result.message);
              invalidateAgreementQueries(queryClient, jobId);
            }}
          />
        ) : null}
      </>
    );
  }

  const lastRequest = sentAt ?? requestedAt ?? null;
  const request = async () => {
    setBusy(true);
    try {
      const result = await b2bGeneratorApi.requestSignature(row.id);
      setSentAt(result.requested_at ?? new Date().toISOString());
      invalidateAgreementQueries(queryClient, jobId);
      if (!result.sent) {
        showSuccess("Prośba o potwierdzenie podpisu była już wysłana w ciągu ostatniej doby.");
      } else if (result.recipient_names.length > 0) {
        showSuccess(`Wysłano prośbę o potwierdzenie podpisu: ${result.recipient_names.join(", ")}.`);
      } else {
        showSuccess("Wysłano prośbę o potwierdzenie podpisu.");
      }
    } catch (e) {
      showError(apiErrorMessage(e, "Nie udało się wysłać prośby o potwierdzenie podpisu."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-1">
      <Button size={size} variant="outline" disabled={busy} onClick={() => void request()}>
        {lastRequest ? "Przypomnij o podpisie" : "Poproś o potwierdzenie podpisu"}
      </Button>
      <p className="text-[11px] text-muted-foreground">
        {lastRequest
          ? `Prośba wysłana ${formatIsoDatePl(lastRequest.slice(0, 10))} — potwierdza Delivery Lead.`
          : "Podpis potwierdza Delivery Lead — dostanie prośbę i sprawę na pulpicie."}
      </p>
    </div>
  );
}
