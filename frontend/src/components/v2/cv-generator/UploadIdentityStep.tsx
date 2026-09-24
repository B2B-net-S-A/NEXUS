"use client";

import { useId, useState } from "react";
import { ArrowLeft, FileText, Loader2, UserCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { FileDropZone } from "@/components/ds/FileDropZone";
import type { CvIdentifyMatch } from "@/lib/api";
import { CV_ACCEPT, MAX_UPLOAD_MB } from "@/lib/cv-generator";

import { StatusChip, StepCard } from "./GeneratorParts";

const MATCH_REASON_LABEL: Record<string, string> = {
  identical_file: "ten sam plik jest już w bazie",
  email_exact: "ten sam e-mail",
  phone_exact: "ten sam numer telefonu",
  email: "ten sam e-mail",
  phone: "ten sam numer telefonu",
};

/** Kody powodów z serwera po polsku; nieznany kod zostaje, jak przyszedł. */
export function matchReasonText(reasons: readonly string[]): string {
  return reasons.map((reason) => MATCH_REASON_LABEL[reason] ?? reason).join(", ");
}

export interface UploadIdentityStepProps {
  file: File | null;
  fileError: string | null;
  onPick: (file: File | null) => void;
  onFileError: (message: string) => void;
  onBack: () => void;
  identifying: boolean;
  matches: readonly CvIdentifyMatch[] | null;
  identifyError: string | null;
  onUseMatch: (match: CvIdentifyMatch) => void;
  /** Prawo dodania kandydata (`candidate.create`) — bez niego przycisk znika. */
  canAddToBase: boolean;
  onAddToBase: () => void;
  addingToBase: boolean;
  decision: "pending" | "without-adding";
  onGenerateWithoutAdding: () => void;
}

/**
 * Krok 1 dla osoby spoza bazy: plik z dysku → sprawdzenie, czy ktoś podobny
 * już jest w bazie → „użyj jej” / „Dodaj do bazy” / „Generuj bez dodawania”.
 * Sprawdzenie nie woła modelu — porównuje e-mail, telefon i nazwisko z pliku.
 */
export function UploadIdentityStep(props: UploadIdentityStepProps) {
  const inputId = useId();
  const [dismissed, setDismissed] = useState<number[]>([]);
  const visibleMatches = (props.matches ?? []).filter((m) => !dismissed.includes(m.candidate_id));

  return (
    <StepCard step={1} title="Kandydat spoza bazy">
      <Button type="button" variant="tertiary" size="sm" className="mb-3 px-0" onClick={props.onBack}>
        <ArrowLeft aria-hidden className="mr-1.5 h-4 w-4" />
        Wróć do wyszukiwania osoby
      </Button>

      {props.file ? (
        <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/40 p-3">
          <FileText aria-hidden className="h-5 w-5 flex-none text-primary" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold text-foreground">{props.file.name}</p>
            <p className="text-xs text-muted-foreground">
              {`${Math.max(1, Math.round(props.file.size / 1024))} KB`}
              {props.identifying ? " · sprawdzam bazę…" : props.matches ? " · odczytany" : ""}
            </p>
          </div>
          <Button type="button" variant="tertiary" size="sm" onClick={() => props.onPick(null)}>
            Podmień
          </Button>
        </div>
      ) : (
        <FileDropZone
          // `relative`: ukryty input (sr-only = absolute) zostaje przy etykiecie,
          // inaczej jego fokus przewijał dokument i spychał powłokę aplikacji.
          className="relative"
          inputId={inputId}
          file={null}
          accept={CV_ACCEPT}
          maxBytes={MAX_UPLOAD_MB * 1024 * 1024}
          label="Upuść plik CV (PDF albo DOCX) albo wybierz z dysku"
          hint={`PDF / DOCX, do ${MAX_UPLOAD_MB} MB. Sprawdzimy, czy tej osoby nie ma już w bazie.`}
          error={props.fileError}
          onError={props.onFileError}
          onPick={props.onPick}
        />
      )}
      {props.file && props.fileError ? (
        <p role="alert" className="mt-2 text-xs text-destructive">{props.fileError}</p>
      ) : null}

      {props.identifying ? (
        <p className="mt-3 flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> Sprawdzam, czy ta osoba jest w bazie…
        </p>
      ) : null}
      {props.identifyError ? (
        <p role="alert" className="mt-3 text-sm text-destructive">{props.identifyError}</p>
      ) : null}

      {visibleMatches.map((match) => (
        <div key={match.candidate_id} className="mt-3 rounded-lg border border-warning/30 bg-warning-muted p-3 text-sm text-warning-muted-foreground">
          <p>
            W bazie jest podobna osoba: <strong className="font-semibold">{match.full_name}</strong>.
            {match.match_reasons.length ? ` Zgadza się: ${matchReasonText(match.match_reasons)}.` : ""}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button type="button" size="sm" onClick={() => props.onUseMatch(match)}>
              <UserCheck aria-hidden className="mr-1.5 h-4 w-4" />
              To ta osoba — użyj jej
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setDismissed((ids) => [...ids, match.candidate_id])}>
              To ktoś inny
            </Button>
          </div>
        </div>
      ))}

      {props.file && !props.identifying && (props.matches || props.identifyError) && visibleMatches.length === 0 ? (
        props.decision === "without-adding" ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <StatusChip tone="neutral">bez dodawania do bazy</StatusChip>
            <span className="text-muted-foreground">
              CV nie będzie miało właściciela w NEXUSIE — trafi tylko na listę Moje CV.
            </span>
          </div>
        ) : (
          <div className="mt-4 flex flex-wrap gap-2">
            {props.canAddToBase ? (
              <Button type="button" onClick={props.onAddToBase} disabled={props.addingToBase}>
                {props.addingToBase ? <Loader2 aria-hidden className="mr-2 h-4 w-4 animate-spin" /> : null}
                Dodaj do bazy kandydatów
              </Button>
            ) : null}
            <Button type="button" variant="outline" onClick={props.onGenerateWithoutAdding}>
              Generuj bez dodawania
            </Button>
          </div>
        )
      ) : null}
      {props.file && !props.identifying && (props.matches || props.identifyError) && visibleMatches.length === 0 && props.decision === "pending" ? (
        <p className="mt-2 text-xs text-muted-foreground">
          {props.canAddToBase
            ? "Dodanie tworzy kandydata z danych w pliku — CV dostanie właściciela i trafi do jego historii."
            : "Nie masz prawa dodawania kandydatów — możesz wygenerować CV bez dodawania."}
        </p>
      ) : null}
    </StepCard>
  );
}
