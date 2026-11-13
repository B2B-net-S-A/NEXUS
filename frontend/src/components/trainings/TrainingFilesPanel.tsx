"use client";

import { useRef, useState } from "react";
import { Download, Play, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type { TrainingFileKind, TrainingFileRow } from "@/lib/api/trainings";
import { formatDateTimePl } from "@/lib/date-pl";

import { formatBytes, isPlayable } from "./training-model";

const KIND_LABELS: Record<TrainingFileKind, string> = {
  deliverable: "Od trenera",
  recording: "Nagranie",
  invoice: "Faktura",
  internal: "Wewnętrzny",
};

type UploadKind = "recording" | "internal";

interface TrainingFilesPanelProps {
  files: TrainingFileRow[];
  canManage: boolean;
  onDownload: (file: TrainingFileRow) => void;
  onToggleParticipants: (input: { fileId: number; value: boolean }) => Promise<boolean>;
  onUpload: (input: {
    kind: UploadKind;
    file: File;
    onProgress: (fraction: number) => void;
  }) => Promise<boolean>;
  /** Adres odtwarzania (bilet jednego pliku); `null` = nie da się odtworzyć. */
  getMediaUrl: (file: TrainingFileRow) => Promise<string | null>;
  busy?: boolean;
}

/** Faktura i pliki wewnętrzne nigdy nie idą do uczestników (serwer i tak odmówi). */
function canShare(file: TrainingFileRow): boolean {
  return file.kind === "deliverable" || file.kind === "recording";
}

export function TrainingFilesPanel({
  files,
  canManage,
  onDownload,
  onToggleParticipants,
  onUpload,
  getMediaUrl,
  busy,
}: TrainingFilesPanelProps) {
  const [progress, setProgress] = useState<{ kind: UploadKind; fraction: number } | null>(null);
  const [player, setPlayer] = useState<{ fileId: number; url: string; video: boolean } | null>(null);
  const recordingInput = useRef<HTMLInputElement>(null);
  const internalInput = useRef<HTMLInputElement>(null);
  const visible = files.filter((file) => file.status !== "replaced");

  const upload = async (kind: UploadKind, file: File | undefined) => {
    if (!file) return;
    setProgress({ kind, fraction: 0 });
    try {
      await onUpload({ kind, file, onProgress: (fraction) => setProgress({ kind, fraction }) });
    } finally {
      setProgress(null);
      if (recordingInput.current) recordingInput.current.value = "";
      if (internalInput.current) internalInput.current.value = "";
    }
  };

  const play = async (file: TrainingFileRow) => {
    const url = await getMediaUrl(file);
    if (url) setPlayer({ fileId: file.id, url, video: !file.content_type?.startsWith("audio/") });
  };

  return (
    <div className="space-y-3">
      {visible.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nie ma jeszcze plików.</p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th className="sticky left-0 bg-card py-2 pr-3 font-medium">Plik</th>
                <th className="py-2 pr-3 font-medium">Rodzaj</th>
                <th className="py-2 pr-3 font-medium">Wgrany</th>
                <th className="py-2 pr-3 font-medium">Dla uczestników</th>
                <th className="py-2 font-medium">
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {visible.map((file) => (
                <tr key={file.id} className="border-b border-border/60">
                  <td className="sticky left-0 max-w-[18rem] bg-card py-2 pr-3">
                    <span className="block truncate" title={file.file_name}>
                      {file.file_name}
                    </span>
                    <span className="text-xs text-muted-foreground">{formatBytes(file.size_bytes)}</span>
                  </td>
                  <td className="py-2 pr-3">{KIND_LABELS[file.kind]}</td>
                  <td className="py-2 pr-3 text-xs text-muted-foreground">
                    {formatDateTimePl(file.uploaded_at)}
                  </td>
                  <td className="py-2 pr-3">
                    {canShare(file) ? (
                      <Switch
                        aria-label={`Dla uczestników: ${file.file_name}`}
                        checked={file.for_participants}
                        disabled={!canManage || busy}
                        onCheckedChange={(value) =>
                          onToggleParticipants({ fileId: file.id, value })
                        }
                      />
                    ) : (
                      <span className="text-xs text-muted-foreground">nie</span>
                    )}
                  </td>
                  <td className="py-2 text-right">
                    <span className="inline-flex gap-1">
                      {isPlayable(file.content_type, file.kind) ? (
                        <Button size="sm" variant="ghost" onClick={() => play(file)}>
                          <Play className="h-3.5 w-3.5" aria-hidden /> Obejrzyj
                        </Button>
                      ) : null}
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        aria-label={`Pobierz ${file.file_name}`}
                        onClick={() => onDownload(file)}
                      >
                        <Download className="h-4 w-4" aria-hidden />
                      </Button>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {player ? (
        <div className="space-y-1">
          {player.video ? (
            <video
              key={player.url}
              src={player.url}
              controls
              preload="metadata"
              className="aspect-video w-full rounded-md bg-foreground"
            />
          ) : (
            <audio key={player.url} src={player.url} controls className="w-full" />
          )}
          <Button size="sm" variant="ghost" onClick={() => setPlayer(null)}>
            Zamknij odtwarzacz
          </Button>
        </div>
      ) : null}
      {canManage ? (
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={recordingInput}
            type="file"
            accept="video/*,audio/*"
            className="sr-only"
            aria-label="Plik nagrania"
            onChange={(event) => upload("recording", event.target.files?.[0])}
          />
          <input
            ref={internalInput}
            type="file"
            className="sr-only"
            aria-label="Plik wewnętrzny"
            onChange={(event) => upload("internal", event.target.files?.[0])}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={progress !== null}
            onClick={() => recordingInput.current?.click()}
          >
            <Upload className="h-3.5 w-3.5" aria-hidden /> Wgraj nagranie z Teams
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={progress !== null}
            onClick={() => internalInput.current?.click()}
          >
            <Upload className="h-3.5 w-3.5" aria-hidden /> Plik wewnętrzny
          </Button>
          {progress ? (
            <div className="flex min-w-[12rem] flex-1 items-center gap-2" role="status">
              <progress
                className="h-2 w-full accent-primary"
                max={1}
                value={progress.fraction}
                aria-label="Postęp wysyłki"
              />
              <span className="text-xs tabular-nums text-muted-foreground">
                {Math.round(progress.fraction * 100)}%
              </span>
            </div>
          ) : null}
        </div>
      ) : null}
      <p className="text-xs text-muted-foreground">
        Pliki wewnętrzne (obecność, ankieta, źródła) nie trafiają do uczestników. Nagranie publikuje
        druga osoba, nie ta, która je wgrała.
      </p>
    </div>
  );
}
