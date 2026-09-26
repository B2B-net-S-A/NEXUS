"use client";

import EmailCompose from "@/components/emails/EmailCompose";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  candidateName: string;
  candidateEmail: string;
  requestId?: number;
}

/** The profile and pipeline use the same Microsoft 365 composer as email history. */
export function SendEmailV2({
  open,
  onOpenChange,
  candidateId,
  candidateName,
  candidateEmail,
  requestId,
}: Props) {
  if (!open) return null;
  return (
    <EmailCompose
      mode="new"
      candidateId={candidateId}
      candidateName={candidateName}
      defaultTo={candidateEmail}
      requestId={requestId}
      onClose={() => onOpenChange(false)}
    />
  );
}
