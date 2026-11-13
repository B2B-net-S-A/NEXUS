"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Download, PlayCircle, Search, Star } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import type {
  LibraryFile,
  LibraryRecording,
  TrainingLibrary as Library,
  TranscriptSearch,
} from "@/lib/api/trainings";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { chapterTime, fileExtension, isPlayable } from "./training-model";

interface TrainingLibraryProps {
  library: Library;
  /** Adres odtwarzania z biletem; `null` = nie da się teraz odtworzyć. */
  getMediaUrl: (file: LibraryFile) => Promise<string | null>;
  onDownload: (file: LibraryFile) => void;
  /** 0697: wyszukiwanie w transkrypcie nagrania (gdy jest). */
  onSearchTranscript?: (id: number, q: string) => Promise<TranscriptSearch | null>;
  /** 0697: ocena 1–5 od osoby zapisanej na szkolenie. */
  onRate?: (id: number, rating: number) => Promise<boolean>;
  busy?: boolean;
}

function clock(second: number): string {
  const h = Math.floor(second / 3600);
  const m = Math.floor((second % 3600) / 60);
  const s = second % 60;
  const mm = String(m).padStart(h ? 2 : 1, "0");
  return `${h ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

function TranscriptBox({
  recordingId,
  onSearch,
  onSeekSecond,
}: {
  recordingId: number;
  onSearch: (id: number, q: string) => Promise<TranscriptSearch | null>;
  onSeekSecond: (second: number) => void;
}) {
  const [q, setQ] = useState("");
  const [result, setResult] = useState<TranscriptSearch | null>(null);
  const [failed, setFailed] = useState(false);
  const search = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!q.trim()) return;
    const found = await onSearch(recordingId, q.trim());
    setFailed(found === null);
    setResult(found);
  };
  return (
    <Card size="sm" className="space-y-2 p-4">
      <h4 className="text-sm font-semibold">Szukaj w tym, co padło na szkoleniu</h4>
      <form onSubmit={search} className="flex gap-2">
        <Input
          aria-label="Szukaj w transkrypcie"
          placeholder="np. RODO"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
        <Button size="sm" type="submit" variant="outline">
          Szukaj
        </Button>
      </form>
      {failed ? <p className="text-sm text-destructive">Nie udało się przeszukać transkryptu.</p> : null}
      {result && !result.available ? (
        <p className="text-sm text-muted-foreground">To nagranie nie ma transkryptu.</p>
      ) : null}
      {result && result.available ? (
        result.hits.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nic nie pasuje do „{q.trim()}”.</p>
        ) : (
          <ol className="space-y-1 text-sm">
            {result.hits.map((hit) => (
              <li key={`${hit.second}-${hit.text}`}>
                <button
                  type="button"
                  className="flex w-full gap-3 rounded px-1 py-0.5 text-left hover:bg-muted"
                  onClick={() => onSeekSecond(hit.second)}
                >
                  <span className="w-14 shrink-0 tabular-nums text-muted-foreground">{clock(hit.second)}</span>
                  <span>{hit.text}</span>
                </button>
              </li>
            ))}
          </ol>
        )
      ) : null}
    </Card>
  );
}

function Rating({ onRate }: { onRate: (rating: number) => Promise<boolean> }) {
  const [given, setGiven] = useState<number | null>(null);
  return (
    <div className="flex flex-wrap items-center gap-1 text-sm">
      <span className="mr-1 text-muted-foreground">Jak było?</span>
      {[1, 2, 3, 4, 5].map((value) => (
        <button
          key={value}
          type="button"
          aria-label={`Oceń na ${value} z 5`}
          aria-pressed={given === value}
          className="rounded p-0.5 hover:bg-muted"
          onClick={async () => {
            if (await onRate(value)) setGiven(value);
          }}
        >
          <Star
            className={cn("h-4 w-4", given !== null && value <= given ? "fill-warning text-warning" : "text-muted-foreground")}
            aria-hidden
          />
        </button>
      ))}
      {given ? <span className="ml-1 text-xs text-muted-foreground">Dziękujemy.</span> : null}
    </div>
  );
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

/** Biblioteka szkoleń: na żywo z zapisem, nagranie na górze, rozdziały i materiały pod spodem. */
export function TrainingLibrary({
  library,
  getMediaUrl,
  onDownload,
  onSearchTranscript,
  onRate,
}: TrainingLibraryProps) {
  const [query, setQuery] = useState("");
  const [topic, setTopic] = useState<string | null>(null);
  const needle = query.trim().toLocaleLowerCase("pl");
  const topics = useMemo(
    () => [...new Set(library.recordings.map((recording) => recording.topic).filter(Boolean))].sort(),
    [library.recordings],
  );
  const recordings = useMemo(
    () =>
      library.recordings.filter(
        (recording) => matches(recording, needle) && (topic === null || recording.topic === topic),
      ),
    [library.recordings, needle, topic],
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

  const seekSecond = (second: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = second;
    void video.play().catch(() => undefined);
  };
  const seek = (minute: number) => seekSecond(minute * 60);

  return (
    <div className="space-y-5">
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

        {topics.length > 1 ? (
          <div className="flex flex-wrap gap-1" role="group" aria-label="Tematy">
            {[null, ...topics].map((value) => (
              <button
                key={value ?? "all"}
                type="button"
                aria-pressed={topic === value}
                onClick={() => setTopic(value)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs",
                  topic === value ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground",
                )}
              >
                {value ?? "Wszystkie"}
              </button>
            ))}
          </div>
        ) : null}

        {library.recordings.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            W bibliotece nie ma jeszcze nagrań. Pojawią się po opublikowaniu szkolenia.
          </p>
        ) : recordings.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nic nie pasuje do „{query.trim()}”.</p>
        ) : selected ? (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
            <div className="min-w-0 space-y-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-lg font-semibold text-foreground">{selected.title}</h3>
                  {selected.scope === "registered" ? (
                    <Badge variant="info" size="md">
                      dla zapisanych
                    </Badge>
                  ) : null}
                </div>
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
              {selected.registered && onRate ? (
                <Rating key={`rate-${selected.id}`} onRate={(rating) => onRate(selected.id, rating)} />
              ) : null}
              {selected.description ? (
                <p className="whitespace-pre-line text-sm text-foreground">{selected.description}</p>
              ) : null}
              {recordingFile && onSearchTranscript ? (
                <TranscriptBox key={`transcript-${selected.id}`} recordingId={selected.id} onSearch={onSearchTranscript} onSeekSecond={seekSecond} />
              ) : null}
              <div className="grid grid-cols-[minmax(0,1fr)] gap-4 md:grid-cols-[repeat(2,minmax(0,1fr))]">
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
