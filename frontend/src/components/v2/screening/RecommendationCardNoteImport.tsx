"use client";

/**
 * Odczyt notatki rekrutera (0421, decyzje D1–D5 z 06.10.2026): plik albo
 * tekst + „Odczytaj notatkę”.
 *
 * Od 0424 (07.10.2026) notatka wypełnia jeden formularz screeningu na miejscu
 * („Uzupełnij z notatki”, `screening-form/NoteFillBar.tsx`) — wybór źródła
 * i osobny przegląd propozycji w oknie karty zniknęły. Komponent jest
 * prezentacyjny; zapytanie trzyma pasek formularza.
 */

import { Loader2 } from "lucide-react";

import { FileDropZone } from "@/components/ds/FileDropZone";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export type NoteSource = "file" | "text";

export const NOTE_FILE_ACCEPT = ".docx,.pdf,.txt";
export const NOTE_FILE_MAX_BYTES = 5 * 1024 * 1024;

export function NoteSourceInput({
  source,
  file,
  onFileChange,
  text,
  onTextChange,
  fileError,
  onFileError,
  reading,
  blockedReason,
  onRead,
}: {
  source: "file" | "text";
  file: File | null;
  onFileChange: (file: File | null) => void;
  text: string;
  onTextChange: (text: string) => void;
  fileError: string | null;
  onFileError: (message: string | null) => void;
  reading: boolean;
  /** Powód, dla którego odczyt jest zablokowany (niezapisane zmiany). */
  blockedReason?: string | null;
  onRead: () => void;
}) {
  const ready = source === "file" ? file != null : text.trim().length >= 30;
  return (
    <div className="space-y-3">
      {source === "file" ? (
        <FileDropZone
          inputId="card-note-file"
          file={file}
          onPick={(next) => {
            onFileError(null);
            onFileChange(next);
          }}
          accept={NOTE_FILE_ACCEPT}
          maxBytes={NOTE_FILE_MAX_BYTES}
          label="Notatka z rozmowy"
          hint="Przeciągnij plik albo wybierz z dysku. Pliku nie zapisujemy — tylko jego tekst trafi do historii kandydata."
          error={fileError}
          onError={onFileError}
          disabled={reading}
        />
      ) : (
        <div className="space-y-1">
          <label
            htmlFor="card-note-text"
            className="text-xs font-medium text-foreground"
          >
            Notatka z rozmowy
          </label>
          <Textarea
            id="card-note-text"
            rows={8}
            value={text}
            disabled={reading}
            placeholder="Wklej notatkę — może być hasłami: stawka, dostępność, tryb pracy, odpowiedzi na pytania…"
            onChange={(event) => onTextChange(event.target.value)}
          />
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        NEXUS wpisze to, co znajdzie w notatce, w puste pola formularza, a przy
        wypełnionych pokaże propozycję „Użyj”. Nic nie zapisuje się bez
        „Zapisz”. Narodowość odczytujemy wyłącznie ze wzoru działu — nie
        wysyłamy jej do AI.
      </p>
      {blockedReason ? (
        <p
          role="status"
          className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
        >
          {blockedReason}
        </p>
      ) : null}
      <Button
        type="button"
        onClick={onRead}
        disabled={!ready || reading || Boolean(blockedReason)}
      >
        {reading ? (
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
        ) : null}
        {reading ? "Czytam notatkę…" : "Odczytaj notatkę"}
      </Button>
    </div>
  );
}
