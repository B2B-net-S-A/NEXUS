"use client";

/**
 * Krok „Podpisana obustronnie” w wąskim panelu osoby, gdy umowę można wysłać
 * do podpisu w NEXUSIE (22.11.2026).
 *
 * Od 26.10 żadna umowa nie poszła tą drogą: w panelu, w którym pracują
 * rekruterzy i Delivery Leadzi, był tylko „Poproś o potwierdzenie” albo
 * „Oznacz jako podpisaną”. Teraz główną akcją jest wysyłka, a droga mailowa
 * zostaje pod spodem (bez chowania — DL potwierdza też umowy, które wróciły
 * mailem). Makiety: https://claude.ai/artifact/UyyBZKNWJKia9ekX357r8W
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Download, Send } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  AgreementSignatureAction,
  invalidateAgreementQueries,
} from "@/components/v2/b2b-generator/AgreementSignatureAction";
import { SendForSignatureDialog } from "@/components/v2/b2b-generator/esign/SendForSignatureDialog";
import { b2bGeneratorApi, type B2BGeneratedContractRow } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob, parseDispositionFilename } from "@/lib/cv-generator";

export function EsignSendStep({
  row,
  jobId,
  requestedAt = null,
}: {
  row: B2BGeneratedContractRow;
  jobId: number;
  /** `signature_requested_at` z karty Tablicy — dla „Przypomnij o podpisie”. */
  requestedAt?: string | null;
}) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [sending, setSending] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const download = async () => {
    setDownloading(true);
    try {
      const res = await b2bGeneratorApi.downloadGenerated(row.id);
      const filename = parseDispositionFilename(
        res.headers["content-disposition"] || "",
        `Umowa B2B ${row.contract_number.replaceAll("/", "-")}.docx`,
      );
      downloadBlob(res.data as Blob, filename);
    } catch (e) {
      showError(apiErrorMessage(e, "Nie udało się pobrać umowy."));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="space-y-1.5" data-testid="esign-send-step">
      <Button size="sm" onClick={() => setSending(true)}>
        <Send className="h-3.5 w-3.5" aria-hidden />
        Wyślij do podpisu w NEXUSIE
      </Button>
      <p className="text-[11px] text-muted-foreground">
        Kontraktor dostaje link i przypomnienie. Za B2Bnetwork podpis idzie w NEXUSIE,
        a po podpisie obu stron kontrakt i data podpisu wpisują się same.
      </p>
      <div className="space-y-1 border-t border-border pt-1.5" data-testid="esign-send-step-mail">
        <span className="block text-[11px] text-muted-foreground">
          Wysyłasz mailem albo umowa już wróciła podpisana?
        </span>
        <div className="flex flex-wrap items-start gap-2">
          {row.can_download ? (
            <Button size="sm" variant="outline" disabled={downloading} onClick={() => void download()}>
              <Download className="h-3.5 w-3.5" aria-hidden />
              Pobierz DOCX
            </Button>
          ) : null}
          <AgreementSignatureAction
            row={row}
            jobId={jobId}
            requestedAt={requestedAt}
            readOnly={false}
            secondary
          />
        </div>
      </div>
      {sending ? (
        <SendForSignatureDialog
          row={row}
          onClose={() => {
            setSending(false);
            invalidateAgreementQueries(queryClient, jobId);
          }}
        />
      ) : null}
    </div>
  );
}
