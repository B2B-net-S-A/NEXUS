"use client";

/**
 * Okna otwierane z menu „⋯” karty osoby (04.10.2026). Rzeczy, które do tej
 * pory stały stale na widoku profilu, choć używa się ich rzadko:
 *
 * - „Tagi i pule” — tagi z nagłówka i „Sugerowane pule” z paska Rekrutacji,
 * - „Konflikty i weta” — konflikty z klientami i weta hiring managerów
 *   (dawniej „Dane handlowe” w pasku Rekrutacji),
 * - „Ustalenia z notatek” — karta „Z notatek rekruterów” z „Zapisz w profilu”
 *   (dawniej osobna karta na zakładce Profil; otwiera ją link pod
 *   „Podsumowaniem”).
 *
 * Komponenty w środku są te same co wcześniej — zmienia się tylko miejsce.
 */

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConflictsWidget } from "@/components/ConflictsWidget";
import { HiringManagerVetoesWidget } from "@/components/HiringManagerVetoesWidget";
import { SuggestedPoolsWidget } from "@/components/candidates/SuggestedPoolsWidget";
import { CandidateNotesFactsCard } from "@/components/v2/pages/CandidateNotesFactsCard";
import { CandidateTagsEditor } from "./CandidateTagsEditor";

interface DialogBaseProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
}

export function TagsPoolsDialog({
  open,
  onOpenChange,
  candidateId,
  tags,
  canEdit,
}: DialogBaseProps & { tags: unknown; canEdit: boolean }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" aria-describedby="candidate-tags-pools-description">
        <DialogHeader>
          <DialogTitle>Tagi i pule</DialogTitle>
          <DialogDescription id="candidate-tags-pools-description">
            Tagi pomagają znaleźć kandydata na liście. Pule zbierają osoby
            o podobnym profilu.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-5">
          <section aria-labelledby="candidate-tags-heading" className="space-y-2">
            <h3 id="candidate-tags-heading" className="text-sm font-semibold text-foreground">
              Tagi
            </h3>
            <CandidateTagsEditor candidateId={candidateId} tags={tags} canEdit={canEdit} />
            {!canEdit && !(Array.isArray(tags) && tags.length > 0) ? (
              <p className="text-sm text-muted-foreground">Kandydat nie ma tagów.</p>
            ) : null}
          </section>
          <section aria-label="Pule" className="space-y-2">
            <SuggestedPoolsWidget
              candidateId={candidateId}
              canAdd={canEdit}
              emptyText="Żadna pula nie pasuje teraz do tego profilu."
            />
          </section>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

export function ConflictsVetoesDialog({ open, onOpenChange, candidateId }: DialogBaseProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" aria-describedby="candidate-conflicts-description">
        <DialogHeader>
          <DialogTitle>Konflikty i weta</DialogTitle>
          <DialogDescription id="candidate-conflicts-description">
            Konflikty z klientami (czarna lista, NDA, konkurent) i weta
            hiring managerów. Konflikt ostrzega przy dodawaniu do rekrutacji,
            weto blokuje ruch.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <ConflictsWidget candidateId={candidateId} hideWhenEmpty={false} />
          <HiringManagerVetoesWidget candidateId={candidateId} hideWhenEmpty />
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

export function NotesFactsDialog({
  open,
  onOpenChange,
  candidateId,
  readOnly,
}: DialogBaseProps & { readOnly: boolean }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" aria-describedby="candidate-notes-facts-description">
        <DialogHeader>
          <DialogTitle>Ustalenia z notatek</DialogTitle>
          <DialogDescription id="candidate-notes-facts-description">
            Fakty, które AI wyczytało z notatek rekruterów. Sprawdź je, zanim
            zapiszesz w profilu.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <CandidateNotesFactsCard candidateId={candidateId} readOnly={readOnly} />
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
