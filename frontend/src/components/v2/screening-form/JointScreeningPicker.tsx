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
 *
 * Bliźniaki (0614, 28.10.2026) są zaznaczone zawsze i bez odznaczania
 * („🔒 bliźniak”): weryfikacja idzie pod nie obowiązkowo. Bliźniak, w którym
 * osoby jeszcze nie ma, stoi z „+ Dodaj do bliźniaka” — bez tego bramka
 * „Zweryfikowany” zatrzyma przekazanie.
 *
 * W „Trybie rozmowy” (29.10.2026, zgłoszenie Artura: formularz za ciasny na
 * laptopie) lista stoi zwinięta do jednej linii z wybranymi rekrutacjami
 * i „Zmień” — na 1280 × 720 miała 388 px i spychała formularz poza ekran.
 * Bliźniak bez tej osoby, „Cofnij” po odznaczeniu i odmowa serwera
 * pokazują pełną listę, bo czekają na decyzję rekrutera.
 */

import { useState } from "react";
import { Check, Layers } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ClientReferenceTag } from "@/components/v2/jobs/JobPickName";
import { usePersonPanelConversationMode } from "@/components/v2/person/PersonPanelSide";
import {
  answersCameBack,
  answersStay,
  memoryChipLabel,
} from "@/components/v2/screening-form/ScreeningMemoryNotes";
import type { AlsoFitsJob } from "@/lib/also-fits-api";
import type { JointContextPair, JointMissingTwin } from "@/lib/api/screeningForm";
import { JOINT_MAX_OTHERS } from "@/lib/joint-screening";
import { TWIN_SKIP_REASONS, twinSkipLabel } from "@/lib/job-twins-api";
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
  /** Bliźniaki bez tej osoby — dodanie jak „+ Dodaj i dołącz”. */
  missingTwins?: readonly JointMissingTwin[];
  /** Bliźniaki pominięte w tej rozmowie: rekrutacja → kod powodu. */
  twinSkips?: ReadonlyMap<number, string>;
  /** „Nie bierze udziału…” przy bliźniaku; `null` = cofnij pominięcie. */
  onTwinSkip?: (jobId: number, reason: string | null) => void;
}

/**
 * Bliźniak, w którym osoba nie bierze udziału (kandydat nie chce, klient ją
 * odrzucił, konflikt) — powód idzie z ruchem na „Zweryfikowany” i zostaje
 * w Historii zdarzeń. Bez niego bliźniak jest w rozmowie obowiązkowo.
 */
function TwinSkipControl({
  jobId,
  title,
  reason,
  onTwinSkip,
}: {
  jobId: number;
  title: string;
  reason: string | undefined;
  onTwinSkip?: (jobId: number, reason: string | null) => void;
}) {
  const [choosing, setChoosing] = useState(false);
  if (!onTwinSkip) return null;
  if (reason) {
    return (
      <span className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]" data-testid={`twin-skip-${jobId}`}>
        <span className="rounded bg-muted px-1.5 py-0.5 font-semibold text-muted-foreground">
          Nie bierze udziału: {twinSkipLabel(reason)}
        </span>
        <button type="button" className="font-semibold text-primary hover:underline" onClick={() => onTwinSkip(jobId, null)}>
          Cofnij
        </button>
      </span>
    );
  }
  if (!choosing) {
    return (
      <button
        type="button"
        className="mt-1 block text-[11px] font-semibold text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
        onClick={() => setChoosing(true)}
      >
        Nie bierze udziału w tej rekrutacji…
      </button>
    );
  }
  return (
    <select
      autoFocus
      aria-label={`Powód — ${title}`}
      className="mt-1 w-full rounded-md border border-border bg-card px-2 py-1 text-xs"
      defaultValue=""
      onChange={(e) => {
        if (e.target.value) onTwinSkip(jobId, e.target.value);
        setChoosing(false);
      }}
      onBlur={() => setChoosing(false)}
    >
      <option value="">Dlaczego nie bierze udziału?</option>
      {TWIN_SKIP_REASONS.map((r) => (
        <option key={r.code} value={r.code}>
          {r.label}
        </option>
      ))}
    </select>
  );
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
  missingTwins = [],
  twinSkips,
  onTwinSkip,
}: JointScreeningPickerProps) {
  const conversation = usePersonPanelConversationMode();
  const [listOpen, setListOpen] = useState(false);
  if (pairs.length === 0 && suggestions.length === 0 && missingTwins.length === 0) return null;
  const count = selected.size + 1;
  const full = selected.size >= JOINT_MAX_OTHERS;
  const needsDecision = missingTwins.length > 0 || notice != null || Boolean(error) || addingJobId != null;
  if (conversation?.on && !listOpen && !needsDecision) {
    const others = pairs.filter((pair) => selected.has(pair.job_id));
    return (
      <section
        aria-label="Screening dla"
        data-testid="joint-screening-picker"
        data-collapsed=""
        className="flex min-w-0 items-center gap-2 rounded-xl border border-primary/30 bg-primary/5 px-3 py-1.5 text-xs"
      >
        <Layers className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
        <span className="shrink-0 text-sm font-semibold text-foreground">Screening dla</span>
        <span
          className="min-w-0 flex-1 truncate text-muted-foreground"
          title={[anchorTitle, ...others.map((pair) => pair.title)].join(" · ")}
        >
          <ClientReferenceTag className="mr-1.5 align-text-bottom" reference={anchorReference} />
          <span className="font-semibold text-foreground">{anchorTitle}</span>
          {others.length > 0 ? ` + ${others.length} ${others.length === 1 ? "rekrutacja" : "rekrutacje"}` : null}
        </span>
        {suggestions.length > 0 ? (
          <span className="shrink-0 text-muted-foreground">pasuje też do {suggestions.length}</span>
        ) : null}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 shrink-0 px-2"
          aria-label="Zmień rekrutacje w tej rozmowie"
          onClick={() => setListOpen(true)}
        >
          Zmień
        </Button>
      </section>
    );
  }
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
        {conversation?.on && listOpen && !needsDecision ? (
          <button
            type="button"
            onClick={() => setListOpen(false)}
            className="ml-auto self-center rounded-md px-1.5 py-0.5 text-xs font-medium text-muted-foreground hover:bg-background hover:text-foreground"
          >
            Zwiń do linii
          </button>
        ) : null}
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
          const skipped = pair.twin === true ? twinSkips?.get(pair.job_id) : undefined;
          const locked = pair.twin === true && pair.selectable;
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
                disabled={!pair.selectable || blockedByLimit || locked}
                aria-label={skipped ? `${pair.title} — nie bierze udziału` : undefined}
                onChange={() => onToggle(pair.job_id)}
                aria-describedby={locked ? `${id}-twin` : undefined}
              />
              <div className="min-w-0 flex-1">
              <label htmlFor={id} className="block">
                <span className="block font-semibold text-foreground">
                  <ClientReferenceTag className="mr-1.5 align-text-bottom" reference={pair.client_reference} />
                  {pair.title}
                  {pair.client_name ? <span className="font-normal text-muted-foreground"> · {pair.client_name}</span> : null}
                  {pair.twin ? (
                    <span
                      id={`${id}-twin`}
                      className="ml-1.5 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-semibold text-primary"
                    >
                      🔒 bliźniak
                    </span>
                  ) : null}
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
              {/* Poza etykietą: wybór powodu w etykiecie zablokowanego pola
                  nie dawał się kliknąć (przeklikanie na stagingu 29.10). */}
              {pair.twin && pair.selectable ? (
                <TwinSkipControl jobId={pair.job_id} title={pair.title} reason={skipped} onTwinSkip={onTwinSkip} />
              ) : null}
              </div>
            </li>
          );
        })}
        {missingTwins.map((twin) => {
          const skipped = twinSkips?.get(twin.job_id);
          return (
          <li
            key={`t-${twin.job_id}`}
            data-testid={`joint-missing-twin-${twin.job_id}`}
            className="flex items-center gap-2 rounded-lg border border-primary/40 bg-background px-2.5 py-2 text-xs"
          >
            <span className="min-w-0 flex-1">
              <span className="block font-semibold text-foreground">
                <ClientReferenceTag className="mr-1.5 align-text-bottom" reference={twin.client_reference} />
                {twin.title}
                <span className="ml-1.5 rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-semibold text-primary">
                  🔒 bliźniak
                </span>
              </span>
              {skipped ? null : (
                <span className="text-muted-foreground">
                  Osoby tu jeszcze nie ma — dodaj ją, żeby przekazać dalej w obu rekrutacjach.
                </span>
              )}
              <TwinSkipControl jobId={twin.job_id} title={twin.title} reason={skipped} onTwinSkip={onTwinSkip} />
            </span>
            {skipped ? null : (
              <Button
                type="button"
                size="sm"
                className="h-7 shrink-0 px-2 text-xs"
                disabled={addingJobId != null}
                onClick={() => onAddAndJoin(twin.job_id)}
              >
                {addingJobId === twin.job_id ? "Dodaję…" : "+ Dodaj do bliźniaka"}
              </Button>
            )}
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
