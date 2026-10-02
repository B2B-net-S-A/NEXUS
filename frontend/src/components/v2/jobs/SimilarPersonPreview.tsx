"use client";

/**
 * Karta osoby obok panelu „Podobne rekrutacje” (02.10.2026, makieta C:
 * https://claude.ai/artifact/Kj3gM7bCVBPePkXuQLmKc2).
 *
 * Cienka nakładka na wspólny `PersonPreview` (ten sam podgląd mają pozostałe
 * źródła w oknie „Kandydaci do dodania”): tu dochodzi wyłącznie to, co wie
 * rekrutacja źródłowa — status osoby u klienta i powód, dla którego nie da
 * się jej wybrać.
 */

import { PersonPreview } from "@/components/v2/recruitment/PersonPreview";
import type { SentPerson, SimilarJobItem } from "@/lib/similar-jobs-api";
import { personStatusLine } from "@/lib/similar-reassign";

export interface SimilarPersonPreviewProps {
  /** Rekrutacja, DO której przepinamy — do niej liczy się dopasowanie. */
  jobId: number;
  person: SentPerson;
  /** Rekrutacja, w której osoba była wysłana do klienta. */
  sourceJob: SimilarJobItem | null;
  position: { index: number; total: number };
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
  canOpenProfile: boolean;
  selection: { checked: boolean; disabled: boolean; onToggle: () => void };
}

export function SimilarPersonPreview({
  jobId,
  person,
  sourceJob,
  position,
  onPrev,
  onNext,
  onClose,
  canOpenProfile,
  selection,
}: SimilarPersonPreviewProps) {
  const lockedReason = !person.selectable
    ? person.already_in_job
      ? "Ta osoba jest już w tej rekrutacji."
      : "Pracuje u klienta — nie da się jej przepiąć."
    : null;
  const pickLabel =
    person.sent === false ? "Dodaj tę osobę do „Nowych”" : "Przepnij tę osobę do „Nowych”";
  return (
    <PersonPreview
      jobId={jobId}
      candidateId={person.candidate_id}
      name={person.name}
      source={{
        title: sourceJob ? `W rekrutacji: ${sourceJob.title}` : "W rekrutacji źródłowej",
        line: personStatusLine(person),
        subline: sourceJob
          ? [sourceJob.client_name, sourceJob.reference_number].filter(Boolean).join(" · ")
          : null,
      }}
      position={position}
      onPrev={onPrev}
      onNext={onNext}
      onClose={onClose}
      canOpenProfile={canOpenProfile}
      selection={{ ...selection, label: lockedReason ?? pickLabel }}
      data-testid="similar-person-preview"
    />
  );
}
