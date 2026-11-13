"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Download, PlayCircle, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { LibraryFile, LibraryRecording, LiveTraining, TrainingLibrary as Library } from "@/lib/api/trainings";
import { formatIsoDatePl } from "@/lib/date-pl";
import { safeExternalHref } from "@/lib/safe-href";
import { cn } from "@/lib/utils";

import { chapterTime, fileExtension, isPlayable } from "./training-model";

interface TrainingLibraryProps {
  library: Library;
  onRegister: (id: number, join: boolean) => Promise<boolean>;
  /** Adres odtwarzania z biletem; `null` = nie da się teraz odtworzyć. */
  getMediaUrl: (file: LibraryFile) => Promise<string | null>;
  onDownload: (file: LibraryFile) => void;
  busy?: boolean;
}

function hours(minutes: number | null): string | null {
  if (!minutes) return null;
  if (minutes < 60) return `${minutes} min`;
  const h = minutes / 60;
  return `${Number.isInteger(h) ? h : h.toFixed(1).replace(".", ",")} h`;
}

function matches(recording: LibraryRecording, needle: string): boolean {
  if (!needle) return true;
  const haystack = [
    recording.title,
    recording.topic,
    recording.description,
    ...recording.chapters.map((c) => c.title),
    ...recording.files.map((f) => f.file_name),
  ]
    .join(" ")
    .toLocaleLowerCase("pl");
  return haystack.includes(needle);
}

function LiveRow({
  item,
  onRegister,
  busy,
}: {
  item: LiveTraining;
  onRegister: TrainingLibraryProps["onRegister"];
  busy?: boolean;
}) {
  const join = item.join_url ? safeExternalHref(item.join_url) : null;
  return (
    <li className="grid items-center gap-2 rounded-lg border border-border bg-card px-4 py-3 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:gap-4">
      <span className="inline-flex w-fit rounded-full bg-info-muted px-2.5 py-0.5 text-xs font-medium text-info-muted-foreground">
        Na żywo {formatIsoDatePl(item.session_date)}
        {item.time_from ? ` · ${item.time_from}` : ""}
      </span>
      <span className="min-w-0 text-sm">
        <span className="font-medium text-foreground">{item.title}</span>
        <span className="text-muted-foreground">
          {item.time_from && item.time_to ? ` · ${item.time_from}–${item.time_to}` : ""}
          {item.platform ? ` · ${item.platform}` : ""}
        </span>
      </span>
      <span className="flex flex-wrap items-center gap-2">
        {item.registered && join ? (
          <a
            href={join}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-medium text-primary hover:underline"
          >
            Dołącz
          </a>
        ) : null}
        <Button
          size="sm"
          variant={item.registered ? "outline" : "primary"}
          disabled={busy}
          onClick={() => onRegister(item.id, !item.registered)}
        >
          {item.registered ? "Wypisz się" : "Zapisz się"}
        </Button>
      </span>
    </li>
  );
}

/** Biblioteka szkoleń: na żywo z zapisem, nagranie na górze, rozdziały i materiały pod spodem. */
export function TrainingLibrary({ library, onRegister, getMediaUrl, onDownload, busy }: TrainingLibraryProps) {
  const [query, setQuery] = useState("");
  const needle = query.trim().toLocaleLowerCase("pl");
  const recordings = useMemo(
    () => library.recordings.filter((recording) => matches(recording, needle)),
    [library.recordings, needle],
  );
  const [selectedId, setSelectedId] = useState<number | null>(library.recordings[0]?.id ?? null);
  const selected =
    recordings.find((recording) => recording.id === selectedId) ?? recordings[0] ?? null;
  const recordingFile = selected?.files.find((file) => file.kind === "recording") ?? null;
  const materials = selected?.files.filter((file) => file !== recordingFile) ?? [];

  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [mediaFailed, setMediaFailed] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    let cancelled = false;
    setMediaUrl(null);
    setMediaFailed(false);
    if (!recordingFile) return;
    getMediaUrl(recordingFile).then(
      (url) => {
        if (!cancelled) {
          setMediaUrl(url);
          setMediaFailed(url === null);
        }
      },
      () => {
        if (!cancelled) setMediaFailed(true);
      },
    );
    return () => {
      cancelled = true;
    };
    // Bilet zależy od pliku, nie od tożsamości funkcji z rodzica.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordingFile?.id]);

  const seek = (minute: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = minute * 60;
    void video.play().catch(() => undefined);
  };

  return (
    <div className="space-y-5">
      {library.live.length > 0 ? (
        <section aria-label="Na żywo" className="space-y-2">
          <h2 className="text-sm font-semibold text-foreground">Na żywo</h2>
          <ul className="space-y-2">
            {library.live.map((item) => (
              <LiveRow key={item.id} item={item} onRegister={onRegister} busy={busy} />
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-label="Nagrania" className="space-y-3" data-tour="trainings.library">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-foreground">Nagrania</h2>
          <div className="relative w-full sm:w-72">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              aria-label="Szukaj w nagraniach i materiałach"
              placeholder="Szukaj w nagraniach i materiałach…"
              className="pl-8"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
        </div>

        {library.recordings.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            W bibliotece nie ma jeszcze nagrań. Pojawią się po opublikowaniu szkolenia.
          </p>
        ) : recordings.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nic nie pasuje do „{query.trim()}”.</p>
        ) : selected ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
            <div className="min-w-0 space-y-3">
              <div>
                <h3 className="text-lg font-semibold text-foreground">{selected.title}</h3>
                <p className="text-sm text-muted-foreground">
                  {[
                    selected.session_date ? `Szkolenie ${formatIsoDatePl(selected.session_date)}` : null,
                    hours(selected.duration_minutes),
                    selected.trainer_kind === "consultant"
                      ? "prowadzi trener z Talent Community"
                      : "prowadzi osoba z zespołu",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              {recordingFile ? (
                mediaUrl ? (
                  <video
                    ref={videoRef}
                    key={mediaUrl}
                    src={mediaUrl}
                    controls
                    preload="metadata"
                    className="aspect-video max-h-[60dvh] w-full rounded-lg bg-foreground"
                  />
                ) : (
                  <div className="flex aspect-video max-h-[60dvh] w-full flex-col items-center justify-center gap-2 rounded-lg border border-border bg-card text-sm text-muted-foreground">
                    <PlayCircle className="h-10 w-10" aria-hidden />
                    {mediaFailed
                      ? "Nie udało się przygotować odtwarzania. Odśwież stronę."
                      : "Przygotowuję odtwarzanie…"}
                  </div>
                )
              ) : (
                <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
                  To szkolenie ma same materiały, bez nagrania.
                </p>
              )}
              {selected.description ? (
                <p className="whitespace-pre-line text-sm text-foreground">{selected.description}</p>
              ) : null}
              <div className="grid gap-4 md:grid-cols-2">
                <Card size="sm" className="space-y-2 p-4">
                  <h4 className="text-sm font-semibold">Rozdziały</h4>
                  {selected.chapters.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Bez rozdziałów.</p>
                  ) : (
                    <ol className="space-y-1 text-sm">
                      {selected.chapters.map((chapter, index) => (
                        <li key={`${chapter.title}-${index}`}>
                          <button
                            type="button"
                            className="flex w-full gap-3 rounded px-1 py-0.5 text-left hover:bg-muted"
                            onClick={() => seek(chapter.start_minute)}
                          >
                            <span className="w-12 shrink-0 tabular-nums text-muted-foreground">
                              {chapterTime(chapter.start_minute)}
                            </span>
                            <span>{chapter.title}</span>
                          </button>
                        </li>
                      ))}
                    </ol>
                  )}
                </Card>
                <Card size="sm" className="space-y-2 p-4">
                  <h4 className="text-sm font-semibold">Materiały</h4>
                  {materials.length === 0 ? (
                    <p className="text-sm text-muted-foreground">Bez materiałów do pobrania.</p>
                  ) : (
                    <ul className="space-y-1 text-sm">
                      {materials.map((file) => (
                        <li key={file.id} className="flex items-center gap-2">
                          <span className="w-10 shrink-0 text-xs font-semibold text-muted-foreground">
                            {fileExtension(file.file_name)}
                          </span>
                          <span className="min-w-0 flex-1 truncate" title={file.file_name}>
                            {file.file_name}
                          </span>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => onDownload(file)}
                            aria-label={`${isPlayable(file.content_type) ? "Słuchaj" : "Pobierz"} ${file.file_name}`}
                          >
                            <Download className="h-3.5 w-3.5" aria-hidden />
                            {isPlayable(file.content_type) ? "słuchaj" : "pobierz"}
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
            </div>
            <nav aria-label="Lista nagrań" className="min-w-0">
              <ul className="space-y-1">
                {recordings.map((recording) => (
                  <li key={recording.id}>
                    <button
                      type="button"
                      aria-current={recording.id === selected.id ? "true" : undefined}
                      onClick={() => setSelectedId(recording.id)}
                      className={cn(
                        "w-full rounded-md border px-3 py-2 text-left text-sm",
                        recording.id === selected.id
                          ? "border-primary bg-primary/10"
                          : "border-border hover:bg-muted",
                      )}
                    >
                      <span className="block truncate font-medium text-foreground">{recording.title}</span>
                      <span className="text-xs text-muted-foreground">
                        {formatIsoDatePl(recording.session_date)}
                        {recording.topic ? ` · ${recording.topic}` : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
          </div>
        ) : null}
      </section>
    </div>
  );
}
