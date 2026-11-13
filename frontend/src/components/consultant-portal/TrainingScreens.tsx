"use client";

/**
 * Zakładka „Szkolenia” w panelu konsultanta: biblioteka nagrań, szkolenia na żywo z zapisem
 * i „Prowadzę” (szkolenia, które konsultant prowadzi jako trener). Ekran jednego szkolenia
 * trenera jest w `TrainingDetail.tsx`.
 */
import Link from "next/link";
import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarClock, Download, Headphones, PlayCircle, Search, Video } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { safeExternalHref } from "@/lib/safe-href";
import {
  portalApi,
  portalKeys,
  usePortalQuery,
  type LibraryFile,
  type LibraryLive,
  type LibraryRecording,
  type PortalTrainingRow,
  type PortalTrainings,
} from "@/lib/api/consultant-portal";
import { cn } from "@/lib/utils";

import { Failure, Loading, Panel, ScreenTitle } from "./PanelScreens";
import { saveBlob } from "./portal-model";
import { clockLabel, isPlayable, extensionLabel, minutesLabel, moneyLabel, shortDay, stageOf, warsawToday } from "./training-model";

export type TrainingsTab = "recordings" | "live" | "mine";

const TABS: { key: TrainingsTab; label: string }[] = [
  { key: "recordings", label: "Nagrania" },
  { key: "live", label: "Na żywo" },
  { key: "mine", label: "Prowadzę" },
];

const TICKET_TTL = 5 * 60 * 60 * 1000;

/** Adres pliku dla odtwarzacza: bilet ważny kilka godzin, więc bez odświeżania przy powrocie do karty. */
function useTicket(fileId: number | null) {
  return useQuery({
    queryKey: portalKeys.ticket(fileId ?? 0),
    queryFn: () => portalApi.fileTicket(fileId as number),
    enabled: fileId !== null,
    staleTime: TICKET_TTL,
    gcTime: TICKET_TTL,
    refetchOnWindowFocus: false,
    retry: 1,
  });
}

/** Zakładka startowa: trener z ruchem po swojej stronie trafia od razu do „Prowadzę”. */
export function defaultTab(data: PortalTrainings, today: string): TrainingsTab {
  return data.mine.some((row) => stageOf(row, today).yours) ? "mine" : "recordings";
}

function matches(recording: LibraryRecording, query: string): boolean {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const text = [
    recording.title,
    recording.topic,
    recording.description,
    ...recording.chapters.map((chapter) => chapter.title),
    ...recording.files.map((file) => file.file_name),
  ]
    .join(" ")
    .toLowerCase();
  return words.every((word) => text.includes(word));
}

// ── Prowadzę ─────────────────────────────────────────────────────────────────

const STAGE_ACTION: Partial<Record<PortalTrainingRow["status"], string>> = {
  ordered: "Wyceń",
  returned: "Popraw",
  accepted: "Podpisz",
};

export function MyTrainings({ rows, applied, today }: { rows: PortalTrainingRow[]; applied: boolean; today: string }) {
  if (rows.length === 0) {
    return (
      <Panel title="Twoje szkolenia">
        {applied ? (
          <p className="text-sm text-muted-foreground">
            Gdy zamówimy u Ciebie szkolenie, zobaczysz je tutaj. Dostaniesz też mail.
          </p>
        ) : (
          <div className="space-y-2 text-sm">
            <p className="text-muted-foreground">
              Chcesz prowadzić szkolenia dla konsultantów? Wyślij zgłoszenie, a gdy będziemy mieli dla Ciebie
              szkolenie, zamówienie pojawi się tutaj.
            </p>
            <Button size="sm" asChild>
              <Link href="/konsultant/trener">Zostań trenerem</Link>
            </Button>
          </div>
        )}
      </Panel>
    );
  }
  return (
    <Panel title="Twoje szkolenia">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="sticky left-0 bg-card py-1.5 pr-3 font-medium">Szkolenie</th>
              <th className="py-1.5 pr-3 font-medium">Termin</th>
              <th className="py-1.5 pr-3 font-medium">Stan</th>
              <th className="py-1.5 pr-3 text-right font-medium">Netto</th>
              <th className="py-1.5" />
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((row) => {
              const stage = stageOf(row, today);
              const action = (row.paid_at ? null : STAGE_ACTION[row.status]) ?? "Otwórz";
              return (
                <tr key={row.id}>
                  <td className="sticky left-0 bg-card py-2.5 pr-3 font-medium">{row.title}</td>
                  <td className="py-2.5 pr-3 text-muted-foreground">{shortDay(row.session_date) || "do ustalenia"}</td>
                  <td className="py-2.5 pr-3">
                    <Badge variant={stage.tone}>{stage.label}</Badge>
                  </td>
                  <td className="py-2.5 pr-3 text-right">{moneyLabel(row.total)}</td>
                  <td className="py-2.5 text-right">
                    <Button size="sm" variant={stage.yours ? "primary" : "outline"} asChild>
                      <Link href={`/konsultant/szkolenia/${row.id}`}>{action}</Link>
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

// ── Na żywo ──────────────────────────────────────────────────────────────────

function liveWhen(row: LibraryLive): string {
  const day = shortDay(row.session_date);
  return row.time_from ? `${day}, ${row.time_from}${row.time_to ? `–${row.time_to}` : ""}` : day;
}

/** Zapis i wypis na szkolenie na żywo; lista odświeża się z serwera. */
function useRegistration(row: LibraryLive) {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = async () => {
    setBusy(true);
    setError(null);
    try {
      await portalApi.register(row.id, !row.registered);
      await client.invalidateQueries({ queryKey: portalKeys.trainings });
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się zapisać zmiany. Spróbuj ponownie."));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, toggle };
}

function LiveRow({ row }: { row: LibraryLive }) {
  const { busy, error, toggle } = useRegistration(row);
  const joinHref = row.registered ? safeExternalHref(row.join_url) : null;
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0 text-sm">
          <span className="block font-medium">{row.title}</span>
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <CalendarClock aria-hidden className="size-3.5" /> {liveWhen(row)}
            {row.platform ? `, ${row.platform}` : ""}
            {row.registered ? <Badge variant="success" className="ml-1">Zapisano</Badge> : null}
          </span>
        </span>
        <span className="flex flex-wrap gap-2">
          {joinHref ? (
            <Button size="sm" asChild>
              <a href={joinHref} target="_blank" rel="noreferrer noopener">
                <Video aria-hidden className="size-3.5" /> Dołącz
              </a>
            </Button>
          ) : null}
          <Button size="sm" variant={row.registered ? "ghost" : "outline"} disabled={busy} onClick={toggle}>
            {row.registered ? "Wypisz się" : "Zapisz się"}
          </Button>
        </span>
      </div>
      {error ? (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export function LiveList({ rows }: { rows: LibraryLive[] }) {
  return (
    <Panel title="Na żywo">
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nie ma teraz zapowiedzianych szkoleń. Damy znać mailem o kolejnych.</p>
      ) : (
        <ul className="divide-y">
          {rows.map((row) => (
            <LiveRow key={row.id} row={row} />
          ))}
        </ul>
      )}
      <p className="mt-3 border-t pt-3 text-xs text-muted-foreground">
        Link do spotkania zobaczysz tutaj po zapisaniu się.
      </p>
    </Panel>
  );
}

// ── Nagrania ─────────────────────────────────────────────────────────────────

function sizeLabel(bytes: number | null): string {
  if (!bytes) return "";
  return bytes >= 1024 * 1024 ? `${Math.round(bytes / (1024 * 1024))} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function MaterialRow({ file }: { file: LibraryFile }) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ticket = useTicket(listening ? file.id : null);
  const audio = isPlayable(file) === "audio";
  const download = async () => {
    setError(null);
    try {
      saveBlob(await portalApi.trainingFile(file.id), file.file_name);
    } catch (failure) {
      setError(apiErrorMessage(failure, "Nie udało się pobrać pliku."));
    }
  };
  return (
    <li className="py-2 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="flex min-w-0 items-center gap-2">
          <Badge variant="outline" className="shrink-0">
            {extensionLabel(file.file_name)}
          </Badge>
          <span className="min-w-0 break-all">{file.file_name}</span>
          <span className="shrink-0 text-xs text-muted-foreground">{sizeLabel(file.size_bytes)}</span>
        </span>
        <span className="flex gap-1">
          {audio ? (
            <Button size="sm" variant="ghost" onClick={() => setListening((now) => !now)}>
              <Headphones aria-hidden className="size-3.5" /> {listening ? "Zamknij" : "Słuchaj"}
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={download}>
            <Download aria-hidden className="size-3.5" /> Pobierz
          </Button>
        </span>
      </div>
      {listening && ticket.data ? (
        <audio controls preload="metadata" src={ticket.data.url} className="mt-2 w-full" aria-label={file.file_name} />
      ) : null}
      {listening && ticket.isError ? (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {apiErrorMessage(ticket.error, "Nie udało się otworzyć pliku.")}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </li>
  );
}

export function RecordingView({ recording, onBack }: { recording: LibraryRecording; onBack: () => void }) {
  const video = recording.files.find((file) => file.kind === "recording" && isPlayable(file) === "video") ?? null;
  const materials = recording.files.filter((file) => file !== video);
  const ticket = useTicket(video?.id ?? null);
  const player = useRef<HTMLVideoElement>(null);
  const [chapter, setChapter] = useState<number | null>(null);

  const seek = (index: number, minute: number) => {
    setChapter(index);
    const element = player.current;
    if (!element) return;
    element.currentTime = minute * 60;
    void element.play().catch(() => undefined);
  };

  const meta = [
    shortDay(recording.session_date),
    recording.duration_minutes ? minutesLabel(recording.duration_minutes) : null,
    recording.trainer_kind === "consultant" ? "prowadzi trener z Talent Community" : "prowadzi zespół B2B Network",
  ].filter(Boolean);

  return (
    <div className="min-w-0 space-y-4">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft aria-hidden className="size-3.5" /> Wszystkie nagrania
      </button>
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{recording.title}</h2>
        <p className="text-sm text-muted-foreground">{meta.join(", ")}</p>
      </div>
      <div className="grid min-w-0 grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 space-y-4">
          <div className="overflow-hidden rounded-xl border bg-card">
            {video && ticket.data ? (
              <video
                ref={player}
                controls
                preload="metadata"
                src={ticket.data.url}
                className="aspect-video w-full bg-foreground"
                aria-label={`Nagranie: ${recording.title}`}
              />
            ) : (
              <div className="flex aspect-video w-full items-center justify-center bg-muted p-4 text-center text-sm text-muted-foreground">
                {!video
                  ? "Nagranie tego szkolenia nie jest jeszcze dostępne."
                  : ticket.isError
                    ? apiErrorMessage(ticket.error, "Nie udało się otworzyć nagrania. Odśwież stronę.")
                    : "Wczytujemy nagranie…"}
              </div>
            )}
          </div>
          {recording.description ? (
            <p className="whitespace-pre-line text-sm text-muted-foreground">{recording.description}</p>
          ) : null}
          <Panel title="Materiały">
            {materials.length === 0 ? (
              <p className="text-sm text-muted-foreground">To szkolenie nie ma materiałów do pobrania.</p>
            ) : (
              <ul className="divide-y">
                {materials.map((file) => (
                  <MaterialRow key={file.id} file={file} />
                ))}
              </ul>
            )}
          </Panel>
        </div>
        <Panel title="Rozdziały">
          {recording.chapters.length === 0 ? (
            <p className="text-sm text-muted-foreground">To nagranie nie ma rozdziałów.</p>
          ) : (
            <ol className="space-y-0.5">
              {recording.chapters.map((row, index) => (
                <li key={`${row.start_minute}-${index}`}>
                  <button
                    type="button"
                    disabled={!video}
                    onClick={() => seek(index, row.start_minute)}
                    className={cn(
                      "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-accent disabled:cursor-default disabled:hover:bg-transparent",
                      chapter === index && "bg-primary/10 text-primary",
                    )}
                  >
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">{clockLabel(row.start_minute)}</span>
                    <span className="min-w-0">{row.title}</span>
                  </button>
                </li>
              ))}
            </ol>
          )}
        </Panel>
      </div>
    </div>
  );
}

function NextLive({ row }: { row: LibraryLive }) {
  const { busy, error, toggle } = useRegistration(row);
  return (
    <div className="rounded-xl border bg-card p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="min-w-0">
          <Badge variant="info" className="mr-2">
            Na żywo
          </Badge>
          <span className="font-medium">{liveWhen(row)}</span> {row.title}
        </span>
        {row.registered ? (
          <Badge variant="success">Zapisano</Badge>
        ) : (
          <Button size="sm" variant="outline" disabled={busy} onClick={toggle}>
            Zapisz się
          </Button>
        )}
      </div>
      {error ? (
        <p role="alert" className="mt-1 text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function RecordingsList({
  rows,
  next,
  onOpen,
}: {
  rows: LibraryRecording[];
  next: LibraryLive | null;
  onOpen: (id: number) => void;
}) {
  const [query, setQuery] = useState("");
  const found = useMemo(() => rows.filter((row) => matches(row, query)), [rows, query]);
  return (
    <div className="min-w-0 space-y-4">
      {next ? <NextLive row={next} /> : null}
      <div className="relative">
        <Search aria-hidden className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          aria-label="Szukaj w nagraniach i materiałach"
          placeholder="Szukaj w nagraniach i materiałach…"
          className="pl-9"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {rows.length === 0 ? (
        <Panel>
          <p className="text-sm text-muted-foreground">Pierwsze nagrania pojawią się tu po szkoleniach.</p>
        </Panel>
      ) : found.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nic nie pasuje do wyszukiwania.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {found.map((row) => (
            <li key={row.id}>
              <button
                type="button"
                onClick={() => onOpen(row.id)}
                className="flex h-full w-full items-start gap-3 rounded-xl border bg-card p-4 text-left hover:border-primary"
              >
                <PlayCircle aria-hidden className="mt-0.5 size-5 shrink-0 text-primary" />
                <span className="min-w-0">
                  <span className="block font-medium">{row.title}</span>
                  <span className="block text-xs text-muted-foreground">
                    {[shortDay(row.session_date), row.duration_minutes ? minutesLabel(row.duration_minutes) : null, row.topic]
                      .filter(Boolean)
                      .join(", ")}
                  </span>
                  {row.files.length ? (
                    <span className="mt-1 block text-xs text-muted-foreground">Pliki: {row.files.length}</span>
                  ) : null}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Ekran zakładki ───────────────────────────────────────────────────────────

export function TrainingsView({
  data,
  today = warsawToday(),
  initialTab,
  initialRecording = null,
}: {
  data: PortalTrainings;
  today?: string;
  initialTab?: TrainingsTab;
  initialRecording?: number | null;
}) {
  const [tab, setTab] = useState<TrainingsTab>(initialTab ?? defaultTab(data, today));
  const [open, setOpen] = useState<number | null>(initialRecording);
  const recording = data.library.recordings.find((row) => row.id === open) ?? null;
  return (
    <div className="min-w-0 space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <ScreenTitle title="Szkolenia" lead="Nagrania i materiały ze szkoleń, zapisy na szkolenia na żywo i szkolenia, które prowadzisz." />
        <Button size="sm" variant="ghost" asChild>
          <Link href="/konsultant/trener">{data.applied ? "Zgłoszenie trenera" : "Zostań trenerem"}</Link>
        </Button>
      </div>
      <div role="tablist" aria-label="Szkolenia" className="flex gap-1 border-b">
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={tab === item.key}
            onClick={() => {
              setTab(item.key);
              setOpen(null);
            }}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm",
              tab === item.key
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
            {item.key === "mine" && data.mine.some((row) => stageOf(row, today).yours) ? (
              <span aria-label="czeka na Ciebie" className="ml-1.5 inline-block size-1.5 rounded-full bg-primary align-middle" />
            ) : null}
          </button>
        ))}
      </div>
      {tab === "recordings" && recording ? <RecordingView recording={recording} onBack={() => setOpen(null)} /> : null}
      {tab === "recordings" && !recording ? (
        <RecordingsList rows={data.library.recordings} next={data.library.live[0] ?? null} onOpen={setOpen} />
      ) : null}
      {tab === "live" ? <LiveList rows={data.library.live} /> : null}
      {tab === "mine" ? <MyTrainings rows={data.mine} applied={data.applied} today={today} /> : null}
    </div>
  );
}

export function TrainingsScreen() {
  const query = usePortalQuery(portalKeys.trainings, portalApi.trainings);
  if (query.isLoading) return <Loading />;
  if (query.isError) return <Failure error={query.error} text="Nie udało się wczytać szkoleń. Odśwież stronę." />;
  return query.isSuccess ? <TrainingsView data={query.data} /> : null;
}
