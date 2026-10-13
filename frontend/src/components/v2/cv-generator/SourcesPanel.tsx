"use client";

import { useId, useState, type ReactNode } from "react";
import { Check, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { FileDropZone } from "@/components/ds/FileDropZone";

import { StatusChip } from "./GeneratorParts";
import type { ChampionOverride, CvSourceFile } from "./useCvGenerator";

function SourceRow({ title, status, action, children }: {
  title: string;
  status?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="space-y-2 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        {status}
        {action ? <div className="ml-auto">{action}</div> : null}
      </div>
      {children}
    </div>
  );
}

function OkChip({ children }: { children: ReactNode }) {
  return (
    <StatusChip tone="ok">
      <Check aria-hidden className="h-3.5 w-3.5" />
      {children}
    </StatusChip>
  );
}

function formatUploaded(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString("pl-PL");
}

export interface ProcessSourcesProps {
  jobId: number | null;
  hasChampion: boolean;
  championOverride: ChampionOverride | null;
  championBusy: boolean;
  championMessage: string | null;
  onChampionFile: (file: File) => void;
  onChampionError: (message: string) => void;
  hasNotes: boolean;
  notesChars: number;
  noteDraft: string;
  onNoteDraftChange: (value: string) => void;
  sources: readonly CvSourceFile[];
  sourcesLoading: boolean;
  sourcesError: boolean;
  cvDocumentId: number | null;
  onSourceChange: (id: number) => void;
}

/**
 * Źródła CV osoby z bazy: Champion, notatki i plik CV. Brakującego Championa
 * i notatki uzupełnia się w miejscu — zapisują się w rekrutacji.
 */
export function ProcessSources(props: ProcessSourcesProps) {
  const championInputId = useId();
  const notesId = useId();
  const fileId = useId();
  const [adding, setAdding] = useState(false);
  const showNoteBox = adding || !!props.noteDraft || !props.hasNotes;

  return (
    <>
      <SourceRow
        title="Profil Championa"
        status={
          props.championOverride ? (
            <StatusChip tone="info">z pliku — tylko do tego CV</StatusChip>
          ) : props.hasChampion ? (
            <OkChip>z rekrutacji</OkChip>
          ) : (
            <StatusChip tone="warn">rekrutacja nie ma Championa</StatusChip>
          )
        }
        action={
          props.hasChampion && !props.championOverride && props.jobId ? (
            <a
              href={`/jobs/${props.jobId}?tab=champion`}
              target="_blank"
              rel="noreferrer"
              className="px-3 text-xs font-medium text-primary hover:underline"
            >
              Podejrzyj
            </a>
          ) : null
        }
      >
        {props.championOverride ? (
          <p role="status" className="text-xs text-muted-foreground">{props.championOverride.notice}</p>
        ) : null}
        {!props.hasChampion ? (
          <>
            <FileDropZone
              // `relative`: ukryty input (sr-only = absolute) zostaje przy etykiecie,
              // inaczej jego fokus przewijał dokument i spychał powłokę aplikacji.
              className="relative"
              inputId={championInputId}
              file={null}
              accept=".docx,.pdf"
              label={props.championBusy ? "Odczytuję plik Championa…" : "Upuść plik Championa (DOCX albo PDF) albo wybierz z dysku"}
              hint="Zapiszemy go w rekrutacji, więc kolejne CV do niej już go dostaną."
              disabled={props.championBusy}
              onError={props.onChampionError}
              onPick={(file) => file && props.onChampionFile(file)}
            />
            {props.championBusy ? (
              <p className="flex items-center gap-2 text-xs text-muted-foreground">
                <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" /> Odczytuję profil…
              </p>
            ) : null}
          </>
        ) : null}
        {props.championMessage ? (
          <p role="alert" className="text-xs text-destructive">{props.championMessage}</p>
        ) : null}
      </SourceRow>

      <SourceRow
        title="Notatki ze screeningu"
        status={
          props.hasNotes ? (
            <OkChip>{`${props.notesChars.toLocaleString("pl-PL")} znaków`}</OkChip>
          ) : (
            <StatusChip tone="warn">brak notatek w tej rekrutacji</StatusChip>
          )
        }
        action={
          props.hasNotes && !showNoteBox ? (
            <Button type="button" variant="tertiary" size="sm" onClick={() => setAdding(true)}>
              Dopisz
            </Button>
          ) : null
        }
      >
        {showNoteBox ? (
          <>
            <label htmlFor={notesId} className="sr-only">Notatka ze screeningu</label>
            <Textarea
              id={notesId}
              rows={4}
              value={props.noteDraft}
              onChange={(event) => props.onNoteDraftChange(event.target.value)}
              placeholder="Np. „3 lata z Kubernetes, prowadził migrację Jenkinsa do GitHub Actions…”"
            />
            <p className="text-xs text-muted-foreground">
              Zapiszemy ją jako notatkę kandydata w tej rekrutacji przed generacją.
            </p>
          </>
        ) : null}
      </SourceRow>

      <SourceRow title="Plik CV">
        <label htmlFor={fileId} className="sr-only">Plik CV do generacji</label>
        <select
          id={fileId}
          value={props.cvDocumentId ?? ""}
          disabled={props.sourcesLoading || props.sourcesError || props.sources.length === 0}
          onChange={(event) => props.onSourceChange(Number(event.target.value))}
          className="h-10 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
        >
          {props.sources.length === 0 ? (
            <option value="">
              {props.sourcesLoading ? "Wczytuję pliki CV…" : props.sourcesError ? "Nie udało się pobrać plików" : "Brak pliku CV na profilu"}
            </option>
          ) : null}
          {props.sources.map((source) => (
            <option key={source.id} value={source.id}>
              {[
                `${source.filename}${source.is_primary ? " — główny" : props.sources.length === 1 ? " — jedyny plik" : ""}`,
                formatUploaded(source.uploaded_at),
              ].filter(Boolean).join(" · ")}
            </option>
          ))}
        </select>
        {props.sourcesError ? (
          <p role="alert" className="text-xs text-destructive">Nie udało się pobrać plików CV. Odśwież stronę i spróbuj ponownie.</p>
        ) : !props.sourcesLoading && props.sources.length === 0 ? (
          <p className="text-xs text-muted-foreground">Kandydat nie ma pliku PDF ani DOCX — dodaj go na profilu kandydata.</p>
        ) : null}
      </SourceRow>
    </>
  );
}
