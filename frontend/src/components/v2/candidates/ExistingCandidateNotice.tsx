"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import type { CvDuplicateMatch } from "@/lib/add-candidate-cv";
import { cn } from "@/lib/utils";

/**
 * Ramka „ta osoba już jest w bazie” dla okien dodawania kandydata.
 *
 * Od 12.10.2026 ta sama osoba = ten sam e-mail (decyzja Artura): zamiast
 * listy „podobnych” ze „score” i „Zapisz mimo to” jest jedna osoba i to, co
 * z nią zrobić. `sameFile` = trafienie po identycznym pliku, nie po adresie —
 * wtedy nie ma czego dodawać do profilu.
 */
export function ExistingCandidateNotice({
  match,
  sameFile = false,
  onAttachCv,
  attaching = false,
  onOpenProfile,
  onReadAnyway,
  className,
}: {
  match: Pick<CvDuplicateMatch, "candidate_id" | "name" | "lastname" | "email">;
  sameFile?: boolean;
  /** Brak = bez przycisku (nie wybrano pliku albo plik już jest w profilu). */
  onAttachCv?: () => void;
  attaching?: boolean;
  onOpenProfile?: () => void;
  /** „Wczytaj mimo to” — odczyt CV z pominięciem sita. */
  onReadAnyway?: () => void;
  className?: string;
}) {
  const fullName = `${match.name} ${match.lastname}`.trim();
  return (
    <div
      role="alert"
      className={cn(
        "rounded-lg border border-warning/30 bg-warning-muted p-3 text-sm text-warning-muted-foreground",
        className,
      )}
    >
      <p className="font-semibold">
        {sameFile ? "To CV jest już w profilu" : "Ten kandydat już jest w bazie"}
      </p>
      <p className="mt-0.5 break-words">
        {fullName}
        {match.email ? ` · ${match.email}` : ""}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {onAttachCv ? (
          <Button type="button" size="sm" loading={attaching} onClick={onAttachCv}>
            Dodaj to CV do profilu
          </Button>
        ) : null}
        <Button asChild size="sm" variant="outline">
          <Link href={`/candidates/${match.candidate_id}`} onClick={onOpenProfile}>
            Otwórz profil
          </Link>
        </Button>
        {onReadAnyway ? (
          <Button type="button" size="sm" variant="ghost" disabled={attaching} onClick={onReadAnyway}>
            Wczytaj mimo to
          </Button>
        ) : null}
      </div>
    </div>
  );
}
