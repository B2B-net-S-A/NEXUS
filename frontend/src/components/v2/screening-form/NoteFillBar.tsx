"use client";

/**
 * „Uzupełnij z notatki” nad formularzem screeningu (0424, 07.10.2026).
 *
 * Rekruter wkleja albo wgrywa notatkę z rozmowy; NEXUS czyta ją (reguła wzoru
 * działu, potem Luna — `POST /api/recommendation-cards/note/read[-file]`, bez
 * zapisu) i wypełnia PUSTE pola formularza na miejscu, z plakietką „z notatki”.
 * Tam, gdzie coś już jest wpisane, stoi propozycja „Użyj”. Zapis — razem
 * z tekstem notatki do historii kandydata — robi dopiero „Zapisz”.
 *
 * Odczyt trwa do minuty: wynik liczy się tylko dla osoby, dla której ruszył.
 */

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ClipboardPaste, FileUp, Undo2, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { NoteSourceInput } from "@/components/v2/screening/RecommendationCardNoteImport";
import { apiErrorMessage } from "@/lib/api-error";
import { recommendationCardsApi, type NoteProposal } from "@/lib/api/recommendationCards";
import type { NoteImport } from "@/lib/screening-form";
import { countPl } from "@/lib/plural-pl";

export interface NoteFillSummary {
  /** Ile pól i odpowiedzi wypełniono. */
  filled: number;
  /** Ile propozycji czeka na „Użyj” (pole było już wypełnione). */
  offers: number;
  sourceName: string | null;
}

export interface NoteFillBarProps {
  candidateId: number;
  jobId: number;
  /** Notatka już wypełniła formularz — pasek pokazuje skrót i „Cofnij wypełnienie”. */
  applied: NoteFillSummary | null;
  onProposal: (proposal: NoteProposal, source: NoteImport) => void;
  onUndo: () => void;
  disabled?: boolean;
}

type Mode = "idle" | "text" | "file";

export function NoteFillBar({
  candidateId,
  jobId,
  applied,
  onProposal,
  onUndo,
  disabled = false,
}: NoteFillBarProps) {
  const { showError } = useToast();
  const [mode, setMode] = useState<Mode>("idle");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const scopeRef = useRef("");
  scopeRef.current = `${candidateId}:${jobId}`;

  const read = useMutation({
    mutationFn: async (source: { kind: "text"; text: string } | { kind: "file"; file: File }) => {
      const scope = `${candidateId}:${jobId}`;
      const proposal =
        source.kind === "file"
          ? await recommendationCardsApi.readNoteFile(candidateId, jobId, source.file)
          : await recommendationCardsApi.readNote(candidateId, jobId, source.text);
      return { scope, proposal, sourceName: source.kind === "file" ? source.file.name : null };
    },
    onSuccess: ({ scope, proposal, sourceName }) => {
      if (scope !== scopeRef.current) return;
      if (proposal.message && !proposal.available) showError(proposal.message);
      onProposal(proposal, { text: proposal.text, source_name: sourceName });
      setMode("idle");
      setText("");
      setFile(null);
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się odczytać notatki. Spróbuj ponownie.")),
  });

  if (applied) {
    return (
      <div
        role="status"
        data-testid="note-fill-summary"
        className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-foreground"
      >
        <p className="min-w-0 flex-1">
          Z notatki{applied.sourceName ? ` (plik ${applied.sourceName})` : ""} wypełniono{" "}
          {countPl(applied.filled, "miejsce", "miejsca", "miejsc")}
          {applied.offers > 0
            ? ` · ${countPl(applied.offers, "propozycja czeka", "propozycje czekają", "propozycji czeka")} na „Użyj”`
            : ""}
          . Notatka trafi do historii kandydata przy zapisie formularza.
        </p>
        <Button type="button" size="sm" variant="ghost" onClick={onUndo}>
          <Undo2 className="h-3.5 w-3.5" aria-hidden /> Cofnij wypełnienie
        </Button>
      </div>
    );
  }

  return (
    <section
      aria-label="Uzupełnij z notatki"
      className="space-y-3 rounded-lg border border-border bg-muted/30 px-3 py-2.5"
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="mr-auto text-xs text-muted-foreground">
          Masz notatkę z rozmowy? NEXUS wypełni z niej puste pola formularza.
        </p>
        <Button
          type="button"
          size="sm"
          variant={mode === "text" ? "primary" : "outline"}
          aria-pressed={mode === "text"}
          disabled={disabled || read.isPending}
          onClick={() => setMode(mode === "text" ? "idle" : "text")}
        >
          <ClipboardPaste className="h-3.5 w-3.5" aria-hidden /> Wklej tekst
        </Button>
        <Button
          type="button"
          size="sm"
          variant={mode === "file" ? "primary" : "outline"}
          aria-pressed={mode === "file"}
          disabled={disabled || read.isPending}
          onClick={() => setMode(mode === "file" ? "idle" : "file")}
        >
          <FileUp className="h-3.5 w-3.5" aria-hidden /> Wgraj plik
        </Button>
        {mode !== "idle" && !read.isPending ? (
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            aria-label="Zamknij odczyt notatki"
            onClick={() => setMode("idle")}
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </Button>
        ) : null}
      </div>
      {mode !== "idle" ? (
        <div className="@container">
          <NoteSourceInput
            source={mode}
            file={file}
            onFileChange={setFile}
            text={text}
            onTextChange={setText}
            fileError={fileError}
            onFileError={setFileError}
            reading={read.isPending}
            onRead={() =>
              mode === "file" && file
                ? read.mutate({ kind: "file", file })
                : read.mutate({ kind: "text", text })
            }
          />
        </div>
      ) : null}
    </section>
  );
}
