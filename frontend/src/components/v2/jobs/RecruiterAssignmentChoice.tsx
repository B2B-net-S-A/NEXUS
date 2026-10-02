"use client";

import { useId } from "react";

import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  AUTOMATIC_PASSIVE_NOTE,
  RECRUITER_ASSIGNMENT_LABEL,
  automaticAssignmentHint,
  automaticAssignmentLabel,
  type AllocationMode,
  type RecruiterAssignment,
} from "@/lib/recruiter-assignment";

export interface RecruiterAssignmentChoiceProps {
  /** Wybór obowiązujący — `resolveRecruiterAssignment(...)`. */
  value: RecruiterAssignment;
  onChange: (value: RecruiterAssignment) => void;
  /** `id` widocznej etykiety pola („Rekruter”). */
  labelledBy: string;
  automaticAvailable: boolean;
  /**
   * Dlaczego opcja automatu jest nieaktywna — zdanie pod polem
   * (automat wyłączony, rekrutacja ma już rekrutera). `null`, gdy opcja jest
   * dostępna albo odczyt jeszcze trwa: wtedy jest nieaktywna bez wyjaśnienia.
   */
  unavailableReason: string | null;
  mode: AllocationMode | null | undefined;
  /** Priorytet „Przyjmujemy kandydatów” — automat nikogo wtedy nie proponuje. */
  passive?: boolean;
  /** Nazwa opcji ręcznej; domyślnie „Wybieram sam”. */
  manualLabel?: string;
  size?: "sm" | "md";
  disabled?: boolean;
}

/**
 * Automat albo osoba wskazana ręcznie — wspólne dla `/jobs/new` i „Przekaż do
 * searchu”. Nazwa opcji automatu i zdanie pod polem zależą od trybu: w „auto”
 * automat przydziela rekrutera prowadzącego od razu („Przydzieli automat”),
 * w „shadow” tylko proponuje i do akceptacji nikt nie jest przypisany
 * („Zaproponuje automat”).
 */
export function RecruiterAssignmentChoice({
  value,
  onChange,
  labelledBy,
  automaticAvailable,
  unavailableReason,
  mode,
  passive = false,
  manualLabel = RECRUITER_ASSIGNMENT_LABEL.person,
  size = "md",
  disabled = false,
}: RecruiterAssignmentChoiceProps) {
  const reasonId = useId();
  const reason = automaticAvailable ? null : unavailableReason;
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <SegmentedRadio<RecruiterAssignment>
        labelledBy={labelledBy}
        // Kolumna flex rozciąga dzieci — przełącznik ma mieć szerokość opcji.
        className="self-start"
        size={size}
        value={value}
        onChange={onChange}
        disabled={disabled}
        options={[
          {
            value: "automatic",
            label: automaticAssignmentLabel(mode),
            disabled: !automaticAvailable,
            describedBy: reason ? reasonId : undefined,
          },
          { value: "person", label: manualLabel },
        ]}
      />
      {value === "automatic" ? (
        passive ? (
          <p className="text-xs font-medium leading-snug text-warning-muted-foreground">
            {AUTOMATIC_PASSIVE_NOTE}
          </p>
        ) : (
          <p className="text-xs leading-snug text-muted-foreground">
            {automaticAssignmentHint(mode)}
          </p>
        )
      ) : null}
      {reason ? (
        <p id={reasonId} className="text-xs leading-snug text-muted-foreground">
          {reason}
        </p>
      ) : null}
    </div>
  );
}
