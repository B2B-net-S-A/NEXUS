"use client";
// B · Aktywność — domyślna zakładka kierunku B. Łączy dawne „Notatki / Rozmowy”
// i „Timeline” w jeden strumień od najnowszych: notatki i rozmowy wyraźnie
// (inicjał autora, pełny tekst), zdarzenia zwarte i wyciszone w jednej linii.
// Kompozytor na górze zamiast formularza z natywną listą rodzaju. Przełącznik
// „Wszystko · Notatki i rozmowy · Zmiany” siedzi w adresie (`filtr=`), a
// `filtr=zmiany` pokazuje zmiany jako zwartą tabelę audytu (pole: przed → po).
import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { warsawDateOf } from "@/lib/warsaw-date";
import { useMkActivities, useMkNotes } from "../shared/data";
import { fmtDate, personFromEmail } from "../shared/format";
import { buildHistory, EventLine, groupHistory, warsawTime, type HistEvent, type HistGroup } from "./HistoriaA";
import type { TabProps } from "./types";

interface ContractNote {
  id: number;
  /** „note” albo „call”. */
  kind: string;
  at: string;
  summary: string | null;
  content: string | null;
  sub_type: string | null;
  status: string | null;
  author_name: string | null;
  duration_seconds: number | null;
}

/** Odpowiedź `/api/contracts/{id}/notes` — lista notatek i rozmów; nieznany kształt → pusta lista. */
function asNotes(raw: unknown): ContractNote[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (x): x is ContractNote =>
      typeof x === "object" && x !== null && typeof (x as ContractNote).id === "number" && typeof (x as ContractNote).at === "string",
  );
}

const NOTE_KIND: Record<string, string> = {
  general: "Notatka",
  call: "Rozmowa",
  meeting: "Spotkanie",
  email: "E-mail",
  interview: "Rozmowa kwalifikacyjna",
};
const CALL_KIND: Record<string, string> = {
  inbound: "Połączenie przychodzące",
  outbound: "Połączenie wychodzące",
};

function noteKind(n: ContractNote): string {
  if (n.kind === "call") return CALL_KIND[n.sub_type ?? ""] ?? "Rozmowa telefoniczna";
  return NOTE_KIND[n.sub_type ?? ""] ?? "Notatka";
}

function duration(seconds: number | null): string | null {
  if (!seconds) return null;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m ? `${m} min${s ? ` ${s} s` : ""}` : `${s} s`;
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p.charAt(0).toUpperCase())
    .join("");
}

const COMPOSER_KINDS = [
  { key: "general", label: "Notatka" },
  { key: "call", label: "Rozmowa" },
  { key: "meeting", label: "Spotkanie" },
  { key: "email", label: "E-mail" },
] as const;

type Mode = "all" | "notes" | "changes";

const MODES: { key: Mode; label: string; param: string | null }[] = [
  { key: "all", label: "Wszystko", param: null },
  { key: "notes", label: "Notatki i rozmowy", param: "notatki" },
  { key: "changes", label: "Zmiany", param: "zmiany" },
];

function Composer() {
  const [text, setText] = useState("");
  const [kind, setKind] = useState<(typeof COMPOSER_KINDS)[number]["key"]>("general");
  return (
    <section className="rounded-xl border border-border bg-card p-3 shadow-xs">
      <label htmlFor="mk-activity-composer" className="sr-only">
        Nowa notatka albo rozmowa
      </label>
      <Textarea
        id="mk-activity-composer"
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Napisz notatkę albo zapisz rozmowę…"
        className="min-h-[60px] resize-none text-[13.5px]"
      />
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <div role="group" aria-label="Rodzaj wpisu" className="flex flex-wrap gap-1.5">
          {COMPOSER_KINDS.map((k) => {
            const active = k.key === kind;
            return (
              <button
                key={k.key}
                type="button"
                aria-pressed={active}
                onClick={() => setKind(k.key)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-[12px] font-medium",
                  active ? "border-primary/40 bg-primary/8 text-foreground" : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {k.label}
              </button>
            );
          })}
        </div>
        <span className="ml-auto text-[11.5px] text-muted-foreground">Trafi też do profilu kandydata</span>
        <Button type="button" size="sm" disabled={!text.trim()}>
          Zapisz
        </Button>
      </div>
    </section>
  );
}

function NoteRow({ note }: { note: ContractNote }) {
  const author = personFromEmail(note.author_name);
  const day = warsawDateOf(note.at);
  const meta = [noteKind(note), note.status, duration(note.duration_seconds)].filter(Boolean).join(" · ");
  return (
    <li className="flex gap-3 border-t border-border/50 py-3 first:border-t-0">
      <span
        aria-hidden
        className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[12px] font-semibold text-primary"
      >
        {initials(author)}
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
          <span className="font-semibold text-foreground">{author}</span>
          <span className="text-muted-foreground">{meta}</span>
          <time dateTime={note.at} className="ml-auto text-[12px] tabular-nums text-muted-foreground">
            {fmtDate(day)}, {warsawTime(note.at)}
          </time>
        </p>
        {note.summary ? <p className="mt-1 text-[13.5px] font-medium text-foreground">{note.summary}</p> : null}
        {note.content ? (
          <p className="mt-1 whitespace-pre-wrap text-[13.5px] leading-6 text-foreground">{note.content}</p>
        ) : null}
      </div>
    </li>
  );
}

/** Komórka „Zmiana”: najwyżej dwie linie „pole: przed → po”, reszta w dymku. */
function ChangeCell({ e }: { e: HistEvent }) {
  if (e.changes.length > 0) {
    const shown = e.changes.slice(0, 2);
    const rest = e.changes.length - shown.length;
    const all = e.changes.map((c) => (c.before === undefined ? `${c.label}: ${c.after}` : `${c.label}: ${c.before} → ${c.after}`)).join("\n");
    return (
      <span title={all}>
        {shown.map((c) => (
          <span key={c.field} className="block truncate">
            <span className="text-muted-foreground">{c.label}: </span>
            {c.before !== undefined ? (
              <>
                <span className="tabular-nums text-muted-foreground">{c.before === "—" ? "brak" : c.before}</span>
                <span className="text-muted-foreground"> → </span>
              </>
            ) : null}
            <span className="font-medium tabular-nums text-foreground">{c.after}</span>
            {c === shown[shown.length - 1] && rest > 0 ? <span className="text-muted-foreground"> +{rest}</span> : null}
          </span>
        ))}
      </span>
    );
  }
  if (e.doc?.name) {
    return (
      <span className="block truncate text-foreground" title={e.doc.name}>
        „{e.doc.name}”{e.doc.viaSharePoint ? <span className="text-muted-foreground"> z SharePointa</span> : null}
      </span>
    );
  }
  if (e.quiet) return <span className="text-muted-foreground">bez zmian</span>;
  return e.detail ? (
    <span className="line-clamp-2 text-foreground" title={e.detail}>
      {e.detail}
    </span>
  ) : (
    <span className="text-muted-foreground/50">—</span>
  );
}

function AuditTable({ events }: { events: HistEvent[] }) {
  return (
    <table className="w-full table-fixed text-[12.5px]">
      <colgroup>
        <col className="w-[84px]" />
        <col className="w-[126px]" />
        <col className="w-[148px]" />
        <col />
      </colgroup>
      <thead>
        <tr className="border-b border-border">
          <th className={cn(CALM_HEAD, "py-2 pr-3 text-left")}>Kiedy</th>
          <th className={cn(CALM_HEAD, "py-2 pr-3 text-left")}>Kto</th>
          <th className={cn(CALM_HEAD, "py-2 pr-3 text-left")}>Co</th>
          <th className={cn(CALM_HEAD, "py-2 text-left")}>Zmiana</th>
        </tr>
      </thead>
      <tbody>
        {events.map((e) => {
          const dim = e.automatic || e.quiet;
          return (
            <tr key={e.id} className={cn(CALM_ROW, "align-top")}>
              <td className="whitespace-nowrap py-2 pr-3 tabular-nums text-foreground">
                {fmtDate(e.day)}
                <span className={CALM_SUBLINE}>{e.time}</span>
              </td>
              <td className="py-2 pr-3">
                {e.automatic ? (
                  <span className="text-muted-foreground">
                    NEXUS
                    <span className={CALM_SUBLINE}>automatycznie</span>
                  </span>
                ) : (
                  <span className="text-foreground">{e.who}</span>
                )}
              </td>
              <td className={cn("py-2 pr-3", dim ? "text-muted-foreground" : "text-foreground")}>
                <span className="line-clamp-2">{e.title}</span>
              </td>
              <td className="min-w-0 py-2">
                <ChangeCell e={e} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

type StreamItem = { kind: "note"; at: string; note: ContractNote } | { kind: "group"; at: string; group: HistGroup };

export function AktywnoscB({ contractId }: TabProps) {
  const sp = useSearchParams();
  const actsQ = useMkActivities(contractId);
  const notesQ = useMkNotes(contractId);
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const mode: Mode = MODES.find((m) => m.param !== null && m.param === sp.get("filtr"))?.key ?? "all";

  const notes = asNotes(notesQ.data).sort((a, b) => b.at.localeCompare(a.at));
  const noteIds = new Set(notes.map((n) => n.id));
  // Wpis „Dodano notatkę” powtarzałby notatkę, która i tak stoi w strumieniu w całości.
  const events = buildHistory(actsQ.data ?? []).filter((e) => !(e.action === "note_added" && e.noteId != null && noteIds.has(e.noteId)));
  const groups = groupHistory(events);
  const stream: StreamItem[] = [
    ...notes.map((note) => ({ kind: "note" as const, at: note.at, note })),
    ...groups.map((group) => ({ kind: "group" as const, at: group.items[0].at, group })),
  ].sort((a, b) => b.at.localeCompare(a.at));

  const counts: Record<Mode, number> = { all: notes.length + events.length, notes: notes.length, changes: events.length };
  const stawki = sp.get("stawki") === "1" ? "&stawki=1" : "";
  const href = (m: (typeof MODES)[number]) =>
    `/contracts/${contractId}/makieta?w=b&tab=aktywnosc${m.param ? `&filtr=${m.param}` : ""}${stawki}`;
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const loading = actsQ.isLoading || notesQ.isLoading;
  const failures = [
    notesQ.isError ? "Nie udało się pobrać notatek i rozmów." : null,
    actsQ.isError ? "Nie udało się pobrać zmian kontraktu." : null,
  ].filter((m): m is string => Boolean(m));

  return (
    <div className="space-y-3">
      {mode !== "changes" ? <Composer /> : null}

      <div className="flex items-center justify-between gap-3">
        <nav aria-label="Co pokazać" className="inline-flex rounded-lg border border-border bg-muted/60 p-0.5">
          {MODES.map((m) => {
            const active = m.key === mode;
            return (
              <Link
                key={m.key}
                href={href(m)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-[12.5px] font-medium",
                  active ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {m.label}
                <span className="text-[11px] tabular-nums text-muted-foreground">{loading ? "…" : counts[m.key]}</span>
              </Link>
            );
          })}
        </nav>
        {mode === "changes" ? (
          <p className="text-[12px] text-muted-foreground">Każdy wpis osobno, od najnowszych</p>
        ) : (
          <p className="text-[12px] text-muted-foreground">Zdarzenia automatyczne wyszarzone</p>
        )}
      </div>

      {failures.map((f) => (
        <p key={f} role="alert" className="text-[13px] text-destructive">
          {f}
        </p>
      ))}

      <section className="rounded-xl border border-border bg-card px-4 py-1 shadow-xs">
        {loading ? (
          <p className="py-3 text-[13px] text-muted-foreground">Ładowanie aktywności…</p>
        ) : mode === "changes" ? (
          events.length === 0 ? (
            <p className="py-3 text-[13px] text-muted-foreground">Kontrakt nie ma jeszcze zapisanych zmian.</p>
          ) : (
            <AuditTable events={events} />
          )
        ) : mode === "notes" ? (
          notes.length === 0 ? (
            <p className="py-3 text-[13px] text-muted-foreground">
              Przy tym kontrakcie nie ma jeszcze notatek ani rozmów. Pierwszą można zapisać w polu wyżej; trafi też do profilu
              kandydata.
            </p>
          ) : (
            <ol>
              {notes.map((n) => (
                <NoteRow key={`n-${n.id}`} note={n} />
              ))}
            </ol>
          )
        ) : (
          <>
            {notes.length === 0 && !notesQ.isError ? (
              <p className="border-b border-border/50 py-2.5 text-[12.5px] text-muted-foreground">
                Notatek ani rozmów jeszcze nie ma — poniżej same zmiany kontraktu.
              </p>
            ) : null}
            {stream.length === 0 ? (
              <p className="py-3 text-[13px] text-muted-foreground">Na tym kontrakcie nic się jeszcze nie wydarzyło.</p>
            ) : (
              <ol>
                {stream.map((item) =>
                  item.kind === "note" ? (
                    <NoteRow key={`n-${item.note.id}`} note={item.note} />
                  ) : (
                    <EventLine
                      key={item.group.key}
                      group={item.group}
                      open={open.has(item.group.key)}
                      onToggle={() => toggle(item.group.key)}
                      dateFormat="full"
                    />
                  ),
                )}
              </ol>
            )}
          </>
        )}
      </section>
    </div>
  );
}
