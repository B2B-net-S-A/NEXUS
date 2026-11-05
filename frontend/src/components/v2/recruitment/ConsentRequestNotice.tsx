"use client";

import { useQuery } from "@tanstack/react-query";

import { useCentralPolicy } from "@/components/cv-rules/CentralPolicyView";
import { useClientCvRule } from "@/components/v2/cv-generator/ClientCvRuleBanner";
import { ConsentRequestButton, consentRequestJobQuery } from "@/components/v2/recruitment/ConsentRequestButton";
import { useStageBrandedCv } from "@/hooks/useStageBrandedCv";
import { consentClientLabel } from "@/lib/consent-mail";

interface ConsentRequestNoticeProps {
  stageId: number;
  candidateId: number;
  candidateName: string;
  jobId: number;
  /** Screening: mowa o rozmowie. Karta bez CV: sama prośba. */
  moment: "screening" | "cv";
}

const NEXT_STEP: Record<ConsentRequestNoticeProps["moment"], string> = {
  screening: "Powiedz o tym na rozmowie i wyślij prośbę; zrzut odpowiedzi wgrasz przy generowaniu CV.",
  cv: "Poproś o nią już teraz; zrzut odpowiedzi wgrasz przy generowaniu CV.",
};

/**
 * Prośba o zgodę, zanim powstanie CV (uwaga Delivery Leada z 05.11.2026): ramka
 * przy gotowym CV pojawia się dopiero pod koniec ścieżki. Pasek jest podpowiedzią:
 * bez odczytu reguły klienta go nie ma, a pobranie i tak blokuje serwer.
 */
export function ConsentRequestNotice(props: ConsentRequestNoticeProps) {
  const jobQuery = useQuery(consentRequestJobQuery(props.jobId));
  const clientId = jobQuery.data?.client_id;
  if (clientId == null) return null;
  return <ClientConsentNotice {...props} clientId={clientId} clientName={jobQuery.data?.client_name} />;
}

function ClientConsentNotice({
  stageId,
  candidateId,
  candidateName,
  jobId,
  moment,
  clientId,
  clientName,
}: ConsentRequestNoticeProps & { clientId: number; clientName?: string | null }) {
  const policyQuery = useCentralPolicy(clientId);
  const ruleQuery = useClientCvRule(clientId);
  const { query: brandedQuery } = useStageBrandedCv(stageId);
  const required =
    policyQuery.data?.effective_policy?.requires_rodo_consent_block === true ||
    (ruleQuery.data?.is_active === true && ruleQuery.data.requires_rodo_consent_block === true);
  if (!required || brandedQuery.data?.consent_attached === true) return null;
  return (
    <div
      role="note"
      data-testid="consent-request-notice"
      data-tour="cv.consent-notice"
      className="flex flex-col items-start gap-2 rounded-md border border-warning/30 bg-warning-muted px-2.5 py-2 text-xs text-warning-muted-foreground"
    >
      <span>
        {consentClientLabel(clientName)} przyjmuje CV tylko ze zgodą kandydata. {NEXT_STEP[moment]}
      </span>
      <ConsentRequestButton candidateId={candidateId} candidateName={candidateName} jobId={jobId} />
    </div>
  );
}
