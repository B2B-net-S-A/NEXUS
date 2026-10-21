"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSignature, Loader2 } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ESIGN_MINE_KEY,
  b2bEsignApi,
  signedPdfProblem,
  type EsignRequest,
} from "@/lib/api/b2bEsign";
import { downloadBlob } from "@/lib/cv-generator";

import { SignedPdfField } from "./SignedPdfField";

function SignRow({ request }: { request: EsignRequest }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const download = useMutation({
    mutationFn: () => b2bEsignApi.companyPdf(request.id),
    onSuccess: (res) =>
      downloadBlob(res.data, `umowa_${request.id}_podpisana_przez_kontraktora.pdf`),
    onError: (error) => toast.showError(apiErrorMessage(error, "Nie udało się pobrać pliku.")),
  });
  const sign = useMutation({
    mutationFn: (picked: File) => b2bEsignApi.companySign(request.id, picked),
    onSuccess: () => {
      toast.showSuccess("Umowa podpisana przez obie strony.");
      queryClient.invalidateQueries({ queryKey: ESIGN_MINE_KEY });
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
    },
  });
  const problem = file ? signedPdfProblem(file) : null;
  return (
    <li className="space-y-3 border-t border-border p-4 first:border-t-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">{request.contractor_name}</p>
          <p className="text-xs text-muted-foreground">
            Kontraktor podpisał podpisem kwalifikowanym
            {request.contractor_signed_at
              ? ` · ${new Date(request.contractor_signed_at).toLocaleString("pl-PL", {
                  timeZone: "Europe/Warsaw",
                })}`
              : ""}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => download.mutate()}
          disabled={download.isPending}
        >
          {download.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Download className="h-4 w-4" aria-hidden />
          )}
          Pobierz do podpisu
        </Button>
      </div>
      <SignedPdfField
        id={`esign-company-${request.id}`}
        label="Plik z oboma podpisami"
        file={file}
        onFile={setFile}
        disabled={sign.isPending}
      />
      {sign.isError ? (
        <Alert
          variant="error"
          title="Podpis nie został przyjęty"
          description={apiErrorMessage(sign.error, "Spróbuj ponownie.")}
        />
      ) : null}
      <Button
        type="button"
        variant="primary"
        size="sm"
        disabled={!file || Boolean(problem) || sign.isPending}
        onClick={() => file && sign.mutate(file)}
      >
        {sign.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <FileSignature className="h-4 w-4" aria-hidden />
        )}
        Wgraj podpisaną za B2B Network
      </Button>
    </li>
  );
}

/** „Do podpisu za firmę” (makieta 6) — tylko gdy coś czeka na tę osobę. */
export function CompanySignaturesPanel() {
  const mine = useQuery({ queryKey: ESIGN_MINE_KEY, queryFn: b2bEsignApi.mine, staleTime: 30_000 });
  if (!mine.isSuccess || mine.data.length === 0) return null;
  return (
    <section
      className="mb-4 overflow-hidden rounded-xl border border-primary/30 bg-card"
      aria-label="Umowy do podpisu za B2B Network"
    >
      <div className="border-b border-border bg-primary/5 px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">
          Do podpisu za B2B Network ({mine.data.length})
        </h2>
        <p className="text-xs text-muted-foreground">
          Pobierz plik, podpisz go swoim podpisem kwalifikowanym (podpis dołoży się do podpisu
          kontraktora) i wgraj z powrotem.
        </p>
      </div>
      <ul>
        {mine.data.map((request) => (
          <SignRow key={request.id} request={request} />
        ))}
      </ul>
    </section>
  );
}
