"use client";

/**
 * „Screening dla” (14.10.2026, makieta B1): pod które rekrutacje jest ta
 * rozmowa. Na liście inne rekrutacje osoby z „Nowych”/„Screeningu” (do
 * zaznaczenia), dalsze etapy i cudza rezerwacja (wyszarzone, z powodem) oraz
 * podpowiedzi „Pasuje też do” z „+ Dodaj i dołącz”. Zaznaczenie co najmniej
 * jednej innej rekrutacji przełącza panel na formularz wspólny.
 *
 * Od 16.10.2026 (D1 A) odznaczenie nie kasuje wpisów: odznaczona rekrutacja
 * z wpisami ma „N odpowiedzi w pamięci”, pod listą stoi „Odznaczono … · Cofnij”,
 * a ponowne zaznaczenie mówi, że wpisy wróciły.
 *
 * Od 22.10.2026 przed tytułem stoi numer u klienta (`ClientReferenceTag`), jak
 * w nagłówku rekrutacji i oknach wyboru — tytuły dla rekrutera są uogólnione.
 * Etykieta, nie przycisk kopiowania: klik w wiersz zaznacza rekrutację.
 */

import { Check, Layers } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ClientReferenceTag } from "@/components/v2/jobs/JobPickName";
import {
  answersCameBack,
  answersStay,
  memoryChipLabel,
} from "@/components/v2/screening-form/ScreeningMemoryNotes";
import type { AlsoFitsJob } from "@/lib/also-fits-api";
import type { JointContextPair } from "@/lib/api/screeningForm";
import { JOINT_MAX_OTHERS } from "@/lib/joint-screening";
import { cn } from "@/lib/utils";

const COLUMN_LABEL: Record<string, string> = { new: "Nowi", screening: "Screening" };

/** Ostatnia zmiana zaznaczenia — „Odznaczono … · Cofnij” albo „Wróciły …”. */
export interface JointPickerNotice {
  kind: "unchecked" | "restored";
  jobId: number;
  title: string;
  /** Ile odpowiedzi tej rekrutacji czeka w pamięci / wróciło. */
  answers: number;
}

function noticeText(notice: JointPickerNotice): string {
  if (notice.kind === "restored") {
    return notice.answers > 0
      ? `${answersCameBack(notice.answers)} z pamięci — ${notice.title}.`
      : `Wróciły wpisy z pamięci — ${notice.title}.`;
  }
  return notice.answers > 0
    ? `Odznaczono „${notice.title}” — ${answersStay(notice.answers)} w pamięci do zapisu.`
    : `Odznaczono „${notice.title}”.`;
}

export interface JointScreeningPickerProps {
  anchorTitle: string;
  anchorReference?: string | null;
  pairs: JointContextPair[];
  suggestions: AlsoFitsJob[];
  selected: ReadonlySet<number>;
  onToggle: (jobId: number) => void;
  onAddAndJoin: (jobId: number) => void;
  addingJobId: number | null;
  /** Odmowa „+ Dodaj i dołącz” (zamknięta karta, weto) — słowami serwera. */
  error?: string | null;
  /** Ile pytań padnie w rozmowie (po złożeniu wspólnych) — `null` = jeszcze nie wiadomo. */
  questionSummary?: { asked: number; total: number } | null;
  /** Pamięć rozmowy: `job_id` → ile odpowiedzi i czy cokolwiek czeka (16.10.2026). */
  memory?: ReadonlyMap<number, { answers: number; any: boolean }>;
  notice?: JointPickerNotice | null;
  /** „Cofnij” po odznaczeniu — zaznacza rekrutację z powrotem. */
  onUndo?: () => void;
}

function claimLine(pair: JointContextPair): string | null {
  if (!pair.claim) return null;
  const until = new Date(pair.claim.until).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
  return pair.claim.mine ? `Twoja rezerwacja do ${until}` : `rezerwacja: ${pair.claim.user_name ?? "ktoś z zespołu"} do ${until}`;
}

export function JointScreeningPicker({
  anchorTitle,
  anchorReference,
  pairs,
  suggestions,
  selected,
  onToggle,
  onAddAndJoin,
  addingJobId,
  error,
  questionSummary,
  memory,
  notice,
  onUndo,
}: JointScreeningPickerProps) {
  if (pairs.length === 0 && suggestions.length === 0) return null;
  const count = selected.size + 1;
  const full = selected.size >= JOINT_MAX_OTHERS;
  return (
    <section
      aria-label="Screening dla"
      data-testid="joint-screening-picker"
      className="rounded-xl border border-primary/30 bg-primary/5 p-3"
    >
      <p className="flex items-baseline gap-2 text-sm font-semibold text-foreground">
        <Layers className="h-3.5 w-3.5 self-center text-primary" aria-hidden="true" />
        Screening dla
        <span className="text-xs font-normal text-muted-foreground">
          {count === 1 ? "1 rekrutacja" : `${count} rekrutacje`} · jedna rozmowa
        </span>
      </p>
      <ul className="mt-2 space-y-1.5">
        <li className="flex items-start gap-2 rounded-lg border border-border bg-background px-2.5 py-2 text-xs">
          <span
            aria-hidden="true"
            className="mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded bg-primary text-primary-foreground"
          >
            <Check className="h-3 w-3" />
          </span>
          <span className="min-w-0">
            <span className="block font-semibold text-foreground">
              <ClientReferenceTag className="mr-1.5 align-text-bottom" reference={anchorReference} />
              {anchorTitle}
            </span>
            <span className="text-muted-foreground">ta Tablica</span>
          </span>
        </li>
        {pairs.map((pair) => {
          const id = `joint-pair-${pair.job_id}`;
          const claim = claimLine(pair);
          const blockedByLimit = pair.selectable && full && !selected.has(pair.job_id);
          const remembered = selected.has(pair.job_id) ? null : memory?.get(pair.job_id);
          return (
            <li
              key={pair.job_id}
              className={cn(
                "flex items-start gap-2 rounded-lg border px-2.5 py-2 text-xs",
                pair.selectable ? "border-border bg-background" : "border-transparent opacity-70",
              )}
            >
              <input
                id={id}
                type="checkbox"
                className="mt-0.5 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]"
                checked={selected.has(pair.job_id)}
                disabled={!pair.selectable || blockedByLimit}
                onChange={() => onToggle(pair.job_id)}
              />
              <label htmlFor={id} className="min-w-0 flex-1">
                <span className="block font-semibold text-foreground">
                  <ClientReferenceTag className="mr-1.5 align-text-bottom" reference={pair.client_reference} />
                  {pair.title}
                  {pair.client_name ? <span className="font-normal text-muted-foreground"> · {pair.client_name}</span> : null}
                </span>
                <span className="text-muted-foreground">
                  {pair.selectable
                    ? [COLUMN_LABEL[pair.board_column ?? ""] ?? pair.board_column, claim].filter(Boolean).join(" · ")
                    : (pair.reason_message ?? "Nie do wyboru")}
                </span>
                {remembered?.any ? (
                  <span className="mt-1 flex w-fit rounded-full bg-info-muted px-2 py-0.5 text-[11px] font-semibold text-info-muted-foreground">
                    {memoryChipLabel(remembered.answers)}
                    {pair.selectable && !blockedByLimit ? " · zaznacz, żeby wróciły" : ""}
                  </span>
                ) : null}
              </label>
            </li>
          );
        })}
        {suggestions.map((job) => (
          <li
            key={`s-${job.job_id}`}
            className="flex items-center gap-2 rounded-lg border border-dashed border-border px-2.5 py-2 text-xs"
          >
            <span className="min-w-0 flex-1">
              <span className="block font-semibold text-foreground">
                <ClientReferenceTag className="mr-1.5 align-text-bottom" reference={job.client_reference} />
                {job.title}
                {job.client_name ? <span className="font-normal text-muted-foreground"> · {job.client_name}</span> : null}
              </span>
              <span className="text-muted-foreground">pasuje {job.score}% · jeszcze nie w tej rekrutacji</span>
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-7 shrink-0 px-2 text-xs"
              disabled={addingJobId != null || full}
              onClick={() => onAddAndJoin(job.job_id)}
            >
              {addingJobId === job.job_id ? "Dodaję…" : "+ Dodaj i dołącz"}
            </Button>
          </li>
        ))}
      </ul>
      {notice ? (
        <p
          role="status"
          data-testid="joint-picker-notice"
          className={cn(
            "mt-2 flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs",
            notice.kind === "unchecked"
              ? "bg-info-muted text-info-muted-foreground"
              : "bg-success-muted text-success-muted-foreground",
          )}
        >
          <span className="min-w-0 flex-1">{noticeText(notice)}</span>
          {notice.kind === "unchecked" && onUndo ? (
            <Button type="button" size="sm" variant="outline" className="h-7 shrink-0 px-2 text-xs" onClick={onUndo}>
              Cofnij
            </Button>
          ) : null}
        </p>
      ) : null}
      {full && (pairs.some((p) => p.selectable && !selected.has(p.job_id)) || suggestions.length > 0) ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Najwyżej {JOINT_MAX_OTHERS + 1} rekrutacje w jednej rozmowie — odznacz jedną, żeby dodać inną.
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-2 text-xs text-destructive-muted-foreground">
          {error}
        </p>
      ) : null}
      {questionSummary && selected.size > 0 && questionSummary.asked < questionSummary.total ? (
        <p className="mt-2 border-t border-border pt-2 text-xs">
          <strong>
            {questionSummary.asked} {questionSummary.asked === 1 ? "pytanie" : "pytań"} zamiast {questionSummary.total}
          </strong>
          <span className="text-muted-foreground"> — wspólne pytania zadasz raz.</span>
        </p>
      ) : null}
    </section>
  );
}
