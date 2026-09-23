"use client";

import dynamic from "next/dynamic";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Generator CV w oknie — ten sam formularz co strona `/cv-generator`
 * (profil kandydata, panel osoby, dok kanbanu). Formularz ładowany dopiero
 * przy otwarciu: to kilkaset linii z comboboxem i dropzone'em, których
 * powierzchnia rekrutacji nie potrzebuje przy starcie.
 */
const CvGenerator = dynamic(
  () => import("@/components/v2/cv-generator/CvGenerator").then((mod) => mod.CvGenerator),
  {
    ssr: false,
    loading: () => (
      <p className="p-6 text-sm text-muted-foreground">Ładowanie generatora CV…</p>
    ),
  },
);

export interface CvGeneratorDialogProps {
  open: boolean;
  onOpenChange(open: boolean): void;
  candidateId: number;
  candidateName?: string;
  jobId?: number | null;
  onEnqueued?(generatedId: number): void;
}

export function CvGeneratorDialog({
  open,
  onOpenChange,
  candidateId,
  candidateName,
  jobId,
  onEnqueued,
}: CvGeneratorDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="2xl" aria-describedby="cv-generator-dialog-desc">
        <DialogHeader className="border-b border-border px-6 py-4">
          <DialogTitle>
            Generuj CV{candidateName ? ` — ${candidateName}` : ""}
          </DialogTitle>
          <DialogDescription id="cv-generator-dialog-desc" className="text-sm text-muted-foreground">
            CV powstaje w tle. Gdy etap nie ma jeszcze CV do klienta, gotowy dokument zostanie do niego podpięty.
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {open && (
            <CvGenerator
              embedded
              prefillCandidateId={candidateId}
              prefillCandidateName={candidateName}
              prefillJobId={jobId ?? undefined}
              onEnqueued={onEnqueued}
            />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
