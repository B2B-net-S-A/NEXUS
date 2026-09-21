"use client";

/**
 * Okno „Baza pytań" — dawna zakładka `?tab=questions`, bez zmian w treści.
 * `QuestionBankTab` dostaje dokładnie te propsy, które dawała mu strona.
 */

import { QuestionBankTab } from "@/components/prep/QuestionBankTab";

import { RecruitmentSheet } from "./RecruitmentSheet";

export interface QuestionBankSlideOverProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  clientId: number | null;
  readOnly?: boolean;
}

export function QuestionBankSlideOver({
  open,
  onOpenChange,
  jobId,
  clientId,
  readOnly = false,
}: QuestionBankSlideOverProps) {
  return (
    <RecruitmentSheet
      open={open}
      onOpenChange={onOpenChange}
      title="Baza pytań"
      description="Pytania, które klient zadawał na rozmowach — do przygotowania kandydata."
      data-testid="question-bank-slideover"
    >
      <QuestionBankTab jobId={jobId} clientId={clientId} readOnly={readOnly} />
    </RecruitmentSheet>
  );
}
