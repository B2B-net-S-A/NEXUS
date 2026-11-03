"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";
import { candidatesApi, jobsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { buildConsentRequest, isPkoClient, zobReference } from "@/lib/consent-mail";

interface ConsentRequestButtonProps {
  candidateId: number;
  candidateName: string;
  jobId: number;
}

interface ConsentRequestJob {
  title?: string | null;
  client_name?: string | null;
  client_reference?: string | null;
}

/**
 * „Poproś kandydata o zgodę” przy ramce „Zgoda RODO: brak zrzutu”: okno maila
 * NEXUSA z wypełnionym adresem i treścią. Tekst jest brzmieniem PKO BP, więc
 * przy innym kliencie z tym wymogiem przycisku nie ma.
 */
export function ConsentRequestButton({ candidateId, candidateName, jobId }: ConsentRequestButtonProps) {
  const [open, setOpen] = useState(false);
  const jobQuery = useQuery({
    queryKey: ["consent-request-job", jobId],
    queryFn: () => jobsApi.get(jobId).then((r) => r.data as ConsentRequestJob),
    staleTime: 60_000,
  });
  const candidateQuery = useQuery({
    queryKey: candidateQueryKeys.detail(candidateId),
    queryFn: () => candidatesApi.get(candidateId).then((r) => r.data as { email?: string | null }),
    staleTime: 60_000,
    enabled: open,
  });

  if (jobQuery.isError) {
    return (
      <p role="alert" className="w-full">
        Nie udało się przygotować prośby o zgodę: {apiErrorMessage(jobQuery.error, "błąd serwera")}.
      </p>
    );
  }
  if (!jobQuery.isSuccess || !isPkoClient(jobQuery.data.client_name)) return null;

  const reference = zobReference(jobQuery.data.client_reference, jobQuery.data.title);
  if (!reference) {
    return <p className="w-full">Prośba o zgodę wymaga numeru ZOB: uzupełnij „Numer u klienta” w Profilu Championa.</p>;
  }
  const mail = buildConsentRequest(candidateName, reference);

  return (
    <>
      <Button type="button" size="sm" data-tour="cv.consent-request" onClick={() => setOpen(true)}>
        <Mail aria-hidden className="h-3.5 w-3.5" /> Poproś kandydata o zgodę
      </Button>
      {open && candidateQuery.isError ? (
        <p role="alert" className="w-full">
          Nie udało się wczytać adresu kandydata: {apiErrorMessage(candidateQuery.error, "błąd serwera")}.
        </p>
      ) : null}
      {open && candidateQuery.data ? (
        <SendEmailV2
          open
          onOpenChange={setOpen}
          candidateId={candidateId}
          candidateName={candidateName}
          candidateEmail={candidateQuery.data.email ?? ""}
          requestId={jobId}
          defaultSubject={mail.subject}
          defaultBody={mail.body}
        />
      ) : null}
    </>
  );
}
