"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { SendEmailV2 } from "@/components/v2/modals/SendEmailV2";
import { candidatesApi, jobsApi, microsoft365Api } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { buildConsentRequest, consentMailStatus, isPkoClient, zobReference } from "@/lib/consent-mail";

interface ConsentRequestButtonProps {
  candidateId: number;
  /** Bez imienia (podgląd CV obok panelu) przycisk czyta je z profilu kandydata. */
  candidateName?: string;
  jobId: number;
}

interface ConsentRequestJob {
  title?: string | null;
  client_id?: number | null;
  client_name?: string | null;
  client_reference?: string | null;
}

export function consentRequestJobQuery(jobId: number) {
  return {
    queryKey: ["consent-request-job", jobId],
    queryFn: () => jobsApi.get(jobId).then((r) => r.data as ConsentRequestJob),
    staleTime: 60_000,
  };
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("pl-PL", { day: "2-digit", month: "2-digit", timeZone: "Europe/Warsaw" });
}

/**
 * „Poproś kandydata o zgodę” przy ramce „Zgoda RODO: brak zrzutu”: okno maila
 * NEXUSA z wypełnionym adresem i treścią. Tekst jest brzmieniem PKO BP, więc
 * przy innym kliencie z tym wymogiem przycisku nie ma.
 */
export function ConsentRequestButton({ candidateId, candidateName, jobId }: ConsentRequestButtonProps) {
  const [open, setOpen] = useState(false);
  const jobQuery = useQuery(consentRequestJobQuery(jobId));
  const threadsQuery = useQuery({
    // Prefiks klucza odświeża `EmailCompose` po wysyłce. Stan jest dodatkiem: bez
    // poczty (awaria, wyłączona integracja) przycisk działa dalej.
    queryKey: ["candidate-emails", candidateId, "consent-request"],
    queryFn: () => microsoft365Api.listCandidateThreads(candidateId).then((r) => r.data.items),
    staleTime: 60_000,
    retry: false,
    enabled: isPkoClient(jobQuery.data?.client_name),
  });
  const candidateQuery = useQuery({
    queryKey: candidateQueryKeys.detail(candidateId),
    queryFn: () =>
      candidatesApi
        .get(candidateId)
        .then((r) => r.data as { email?: string | null; name?: string | null; lastname?: string | null }),
    staleTime: 60_000,
    enabled: open || candidateName == null || (threadsQuery.data?.length ?? 0) > 0,
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
  const name =
    candidateName ?? [candidateQuery.data?.name, candidateQuery.data?.lastname].filter(Boolean).join(" ");
  if (!name) return null;
  const mail = buildConsentRequest(name, reference);
  const status = consentMailStatus(threadsQuery.data ?? [], reference, candidateQuery.data?.email);

  return (
    <>
      {status ? (
        <p className="w-full font-medium" data-testid="consent-request-status">
          {status.kind === "replied"
            ? `Kandydat odpisał ${formatDate(status.at)}. Sprawdź odpowiedź i wgraj jej zrzut.`
            : `Prośba wysłana ${formatDate(status.at)}. Czekamy na odpowiedź kandydata.`}
        </p>
      ) : null}
      <Button
        type="button"
        size="sm"
        variant={status ? "outline" : "primary"}
        data-tour="cv.consent-request"
        onClick={() => setOpen(true)}
      >
        <Mail aria-hidden className="h-3.5 w-3.5" /> {status ? "Poproś ponownie" : "Poproś kandydata o zgodę"}
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
          candidateName={name}
          candidateEmail={candidateQuery.data.email ?? ""}
          requestId={jobId}
          defaultSubject={mail.subject}
          defaultBody={mail.body}
        />
      ) : null}
    </>
  );
}
