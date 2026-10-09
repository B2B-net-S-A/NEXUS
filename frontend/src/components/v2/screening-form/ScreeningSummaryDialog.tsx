"use client";

/**
 * Okno „Screening” osoby w jednej rekrutacji — tylko do odczytu (09.10.2026).
 *
 * Otwiera je profil kandydata przy notatce, z której system odczytał ustalenia
 * z rozmowy. Ten sam widok co dok osoby i przegląd Delivery Leada; edycja jest
 * w formularzu screeningu („Edytuj w screeningu” — panel osoby w rekrutacji).
 */

import Link from "next/link";
import { PencilLine } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { useScreeningFormState } from "@/lib/api/screeningForm";
import { screeningFormHref } from "@/lib/screening-summary";

import { ScreeningSummarySection } from "./ScreeningSummaryView";

export interface ScreeningSummaryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  jobId: number;
  candidateName: string;
  /** Rekrutacja, której dotyczy screening — w podtytule obok nazwiska. */
  jobTitle?: string | null;
  /** Bez „Edytuj w screeningu” (profil bez prawa zapisu). */
  readOnly?: boolean;
}

export function ScreeningSummaryDialog({
  open,
  onOpenChange,
  candidateId,
  jobId,
  candidateName,
  jobTitle,
  readOnly = false,
}: ScreeningSummaryDialogProps) {
  // Ten sam klucz co sekcja w środku — jedno zapytanie na okno.
  const state = useScreeningFormState(candidateId, jobId, open).data;
  const canEdit = !readOnly && state?.editable === true;
  const description = [candidateName, jobTitle?.trim()].filter(Boolean).join(" · ");

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Screening"
      description={description}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
          {canEdit ? (
            <Button asChild>
              <Link href={screeningFormHref(jobId, candidateId)}>
                <PencilLine className="size-3.5" aria-hidden /> Edytuj w screeningu
              </Link>
            </Button>
          ) : null}
        </>
      }
    >
      <ScreeningSummarySection candidateId={candidateId} jobId={jobId} enabled={open} />
    </AppModal>
  );
}

export default ScreeningSummaryDialog;
