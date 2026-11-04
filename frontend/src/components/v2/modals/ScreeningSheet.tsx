"use client";

/**
 * Formularz screeningu jako wysuwany panel.
 *
 * Od 0424 (07.10.2026) to TEN SAM formularz co w panelu osoby na Tablicy
 * (`ScreeningFullForm`: pytania z Profilu Championa, warunki kandydata ze
 * stawką i pola karty rekomendacji, ocena rekrutera, historia zmian) — tylko
 * bez podglądu CV obok. Zostaje dla miejsc, które nie mają panelu osoby:
 * zakładka „Rozmowy” (`JobInterviewsTab`) i Tablica bez kontekstu warsztatów.
 */

import { ClipboardCheck, User } from "lucide-react";

import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ScreeningFullForm } from "@/components/v2/screening-form/ScreeningFullForm";
import { hasSectionAccess } from "@/lib/section-access";
import { useAuthStore } from "@/store/auth";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  jobId: number;
  candidateName: string;
  /** Budżet PLN/h rekrutacji — ocena stawki kandydata w formularzu. */
  jobBudgetHourly?: number | null;
  readOnly?: boolean;
  /** Po udanym zapisie (okno zamyka się samo). */
  onSaved?: () => void;
  /** Po ruchu karty z formularza („Zapisz i przekaż dalej”, „Odrzuć”). */
  onMoved?: () => void;
}

export function ScreeningSheet({
  open,
  onOpenChange,
  candidateId,
  jobId,
  candidateName,
  jobBudgetHourly = null,
  readOnly = false,
  onSaved,
  onMoved,
}: Props) {
  // Lustro `canWritePipeline` ze strony rekrutacji: bez prawa zapisu (albo
  // w podglądzie jako) formularz jest tylko do odczytu.
  const canWrite = useAuthStore(
    (s) => s.realUser === null && hasSectionAccess(s.user, "pipeline", "write"),
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" size="xl">
        <SheetHeader>
          <div className="flex items-center gap-2">
            <ClipboardCheck className="h-4 w-4 text-primary" />
            <SheetTitle>Formularz screeningu</SheetTitle>
          </div>
          <SheetDescription>
            <span className="inline-flex items-center gap-1.5">
              <User className="h-3.5 w-3.5" />
              {candidateName}
            </span>
          </SheetDescription>
        </SheetHeader>
        <SheetBody>
          {open ? (
            <ScreeningFullForm
              candidateId={candidateId}
              jobId={jobId}
              candidateName={candidateName}
              jobBudgetHourly={jobBudgetHourly}
              readOnly={readOnly || !canWrite}
              onSaved={() => onSaved?.()}
              onMoved={() => {
                onMoved?.();
                onOpenChange(false);
              }}
              onCancel={() => onOpenChange(false)}
              closeOnSave
            />
          ) : null}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
