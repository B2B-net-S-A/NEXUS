import { TriangleAlert } from "lucide-react";
import Link from "next/link";

/**
 * Model przeczytał w tym CV inną osobę niż w profilu, a człowiek jeszcze nie
 * rozstrzygnął (09.11.2026). Pomiar: identyczny plik z Traffita wisiał pod
 * osobami o innych nazwiskach, a rekruter oceniał kandydata po cudzym CV.
 */
export function CvIdentityDoubtNotice({ candidateId, className }: { candidateId: number; className?: string }) {
  return (
    <div
      role="status"
      data-testid="cv-identity-doubt"
      className={`flex gap-2 rounded-md border border-warning/40 bg-warning-muted px-2.5 py-1.5 text-xs text-warning-muted-foreground ${className ?? ""}`}
    >
      <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <p>
        <strong>To CV może należeć do innej osoby.</strong> Imię i nazwisko w pliku są inne niż w profilu. Sprawdź to,
        zanim ocenisz kandydata.{" "}
        <Link href={`/candidates/${candidateId}?tab=documents`} className="underline">
          Pliki w profilu
        </Link>
      </p>
    </div>
  );
}
