"use client";

/**
 * Bliźniaki zaznaczane na liście rekrutacji (prośba Olafa, HoR, 11.11.2026):
 * pole przy wierszu, pasek na dole „⇄ Połącz jako bliźniaki”. Olaf chciał sam
 * wybierać requesty, które łączy — na liście, którą i tak przegląda, bez
 * szukania menu i wpisywania numerów.
 *
 * Pierwsza zaznaczona rekrutacja to kotwica, każda kolejna łączy się z nią
 * w osobnym oknie porównania (pary pytań są per para). Najwyżej 4 naraz:
 * kotwica + 3 bliźniaki — tyle mieści jedna rozmowa (`max_twins`). Kto może
 * połączyć, sprawdza serwer jak dotąd (`job_twins.can_link`).
 */

import { useCallback, useMemo, useState } from "react";
import { ArrowLeftRight, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";

import { TwinLinkDialog } from "./TwinLinkDialog";

export interface PickedJob {
  id: number;
  /** Numer u klienta albo nasz — to, po czym ludzie rozpoznają request. */
  ref: string;
  title: string;
}

/** Kotwica + 3 bliźniaki: tyle mieści jedna rozmowa w „Screening dla”. */
export const TWIN_PICK_MAX = 4;

export interface TwinPick {
  picked: readonly PickedJob[];
  isPicked: (id: number) => boolean;
  toggle: (job: PickedJob) => void;
  clear: () => void;
}

export function useTwinPick(): TwinPick {
  const [picked, setPicked] = useState<readonly PickedJob[]>([]);
  const ids = useMemo(() => new Set(picked.map((job) => job.id)), [picked]);
  const toggle = useCallback((job: PickedJob) => {
    setPicked((current) =>
      current.some((item) => item.id === job.id)
        ? current.filter((item) => item.id !== job.id)
        : [...current, job],
    );
  }, []);
  const clear = useCallback(() => setPicked([]), []);
  return { picked, isPicked: (id) => ids.has(id), toggle, clear };
}

/** Zdanie pod przyciskiem, gdy połączyć jeszcze (albo już) nie można. */
export function twinPickHint(count: number): string | null {
  if (count < 2) return "Zaznacz jeszcze jedną rekrutację";
  if (count > TWIN_PICK_MAX) return `Najwyżej ${TWIN_PICK_MAX} naraz — tyle mieści jedna rozmowa`;
  return null;
}

/** Pole w wierszu listy. Klik nie otwiera rekrutacji. */
export function TwinPickCheckbox({ job, pick }: { job: PickedJob; pick: TwinPick }) {
  return (
    <span className="flex items-center" onClick={(e) => e.stopPropagation()}>
      <Checkbox
        checked={pick.isPicked(job.id)}
        onCheckedChange={() => pick.toggle(job)}
        aria-label={`Zaznacz ${job.ref} do połączenia jako bliźniaki`}
        data-testid={`twin-pick-${job.id}`}
      />
    </span>
  );
}

export interface TwinPickBarViewProps {
  picked: readonly PickedJob[];
  onRemove: (job: PickedJob) => void;
  onClear: () => void;
  onLink: () => void;
}

/** Sam wygląd paska — test bez zapytań. */
export function TwinPickBarView({ picked, onRemove, onClear, onLink }: TwinPickBarViewProps) {
  if (picked.length === 0) return null;
  const hint = twinPickHint(picked.length);
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-40 flex justify-center px-4 sm:bottom-5">
      <div
        role="region"
        aria-label="Zaznaczone do połączenia jako bliźniaki"
        data-testid="twin-pick-bar"
        className="pointer-events-auto flex max-w-full animate-slide-in-bottom flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-foreground shadow-md"
      >
        <ArrowLeftRight className="h-4 w-4 text-primary" aria-hidden="true" />
        <span className="text-sm font-semibold">Bliźniaki:</span>
        <ul className="flex min-w-0 flex-wrap items-center gap-1.5">
          {picked.map((job, index) => (
            <li
              key={job.id}
              className="inline-flex max-w-[220px] items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs text-primary"
              title={job.title}
            >
              <span className="font-mono font-semibold">{job.ref}</span>
              {index === 0 && picked.length > 1 ? <span className="text-[10px] uppercase">pierwsza</span> : null}
              <button
                type="button"
                onClick={() => onRemove(job)}
                className="rounded p-0.5 hover:bg-primary/15"
                aria-label={`Odznacz ${job.ref}`}
              >
                <X className="h-3 w-3" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
        <span className="h-4 w-px bg-border" aria-hidden="true" />
        <div className="flex flex-col items-center">
          <Button size="sm" onClick={onLink} disabled={hint != null} aria-describedby="twin-pick-hint">
            <ArrowLeftRight className="h-3.5 w-3.5" aria-hidden="true" />
            Połącz jako bliźniaki
          </Button>
          {hint ? (
            <span id="twin-pick-hint" className="mt-0.5 text-[10px] text-muted-foreground">
              {hint}
            </span>
          ) : null}
        </div>
        <Button size="sm" variant="ghost" onClick={onClear}>
          Wyczyść
        </Button>
      </div>
    </div>
  );
}

/**
 * Pasek z oknami łączenia: pierwsza zaznaczona + każda kolejna, po kolei.
 * Zamknięcie okna przechodzi do następnej pary; po ostatniej zaznaczenie znika.
 */
export function TwinPickBar({ pick }: { pick: TwinPick }) {
  const [queue, setQueue] = useState<{ anchor: PickedJob; others: readonly PickedJob[]; index: number } | null>(null);
  const current = queue ? queue.others[queue.index] : null;
  return (
    <>
      {queue ? null : (
        <TwinPickBarView
          picked={pick.picked}
          onRemove={pick.toggle}
          onClear={pick.clear}
          onLink={() => {
            const [anchor, ...others] = pick.picked;
            if (anchor && others.length > 0) setQueue({ anchor, others, index: 0 });
          }}
        />
      )}
      {queue && current ? (
        <TwinLinkDialog
          key={current.id}
          jobId={queue.anchor.id}
          otherJobId={current.id}
          anchorLabel={
            queue.others.length > 1
              ? `${queue.anchor.ref} ${queue.anchor.title} · para ${queue.index + 1} z ${queue.others.length}`
              : undefined
          }
          open
          onOpenChange={(next) => {
            if (next) return;
            if (queue.index + 1 < queue.others.length) {
              setQueue({ ...queue, index: queue.index + 1 });
            } else {
              setQueue(null);
              pick.clear();
            }
          }}
        />
      ) : null}
    </>
  );
}
