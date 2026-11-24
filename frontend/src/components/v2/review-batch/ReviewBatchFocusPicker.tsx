"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { pluralPl } from "@/lib/plural-pl";
import {
  invalidateReviewBatch,
  setReviewBatchFocus,
  useReviewBatchFocusOptions,
  useReviewBatchFocusPreview,
  type ReviewBatchFocusOption,
  type ReviewBatchSource,
} from "@/lib/api/reviewBatch";
import { cn } from "@/lib/utils";

/**
 * „Nad którą rekrutacją pracujesz dziś?” (zgłoszenie rekruterów 16.11.2026):
 * zespół umawia się, kto robi który request, a porcja dzieli P0 po równo.
 * Po wyborze porcja bierze osoby najpierw z wybranej rekrutacji. Liczba osób
 * do decyzji się nie zmienia: z innych rekrutacji wraca do puli zespołu tylko
 * nadwyżka nieruszonych osób, a kto wybierze pierwszy, bierze najlepsze. Liczby
 * pod zaznaczoną rekrutacją liczy serwer tym samym planem co wybór, z pulą po
 * regułach dopełniania (`GET /api/review-batch/me/focus/{id}`).
 */

const GROUP_TITLE: Record<ReviewBatchSource, string> = {
  p0: "P0",
  p1: "P1 Pilne",
  p2: "Bez priorytetu",
  accepting: "Przyjmujemy kandydatów",
};
const GROUP_ORDER: ReviewBatchSource[] = ["p0", "p1", "p2", "accepting"];

function hhmm(iso: string): string {
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function people(n: number): string {
  return `${n} ${pluralPl(n, "osoba", "osoby", "osób")}`;
}

/** „4 nieruszone osoby z innych rekrutacji wracają do puli zespołu.” */
export function releasedLine(n: number): string {
  return `${n} ${pluralPl(
    n,
    "nieruszona osoba z innych rekrutacji wraca",
    "nieruszone osoby z innych rekrutacji wracają",
    "nieruszonych osób z innych rekrutacji wraca",
  )} do puli zespołu.`;
}

function OptionRow({
  option,
  selected,
  current,
  onSelect,
}: {
  option: ReviewBatchFocusOption;
  selected: boolean;
  current: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <label
        className={cn(
          "flex cursor-pointer gap-2 px-3 py-2 text-sm",
          selected ? "bg-primary/5" : "hover:bg-muted/40",
        )}
      >
        <input
          type="radio"
          name="review-focus"
          checked={selected}
          onChange={onSelect}
          className="mt-1 accent-[hsl(var(--primary))]"
        />
        <span className="min-w-0 flex-1">
          <span className="flex items-start gap-1.5">
            <span className="line-clamp-2 min-w-0 flex-1 font-medium leading-snug">{option.title}</span>
            {current ? (
              <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                wybrana
              </span>
            ) : null}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground tabular-nums">
            {option.pending > 0 ? <span>Twoich teraz: {option.pending}</span> : null}
            <span>Przypisanych: {option.team_size}</span>
          </span>
          {option.picked_by.map((pick) => (
            <span
              key={pick.user_id}
              className="mt-0.5 block text-xs text-muted-foreground"
              data-testid="review-focus-picked-by"
            >
              Wybór na dziś: {pick.name}, {hhmm(pick.at)} · ma stąd {people(pick.cards)}
            </span>
          ))}
          {selected && !current ? <Summary option={option} /> : null}
        </span>
      </label>
    </li>
  );
}

/** Co się stanie po wyborze: pod zaznaczoną rekrutacją, liczby z serwera. */
function Summary({ option }: { option: ReviewBatchFocusOption }) {
  const preview = useReviewBatchFocusPreview(option.job_id);
  if (preview.isError) {
    return (
      <span className="mt-1 block text-xs text-destructive" role="alert">
        {apiErrorMessage(preview.error, "Nie udało się policzyć, ile osób przyjdzie.")}
      </span>
    );
  }
  if (!preview.isSuccess) {
    return <span className="mt-1 block text-xs text-muted-foreground">Liczę, ile osób przyjdzie…</span>;
  }
  const { take, release, available } = preview.data;
  const picked = option.picked_by.length > 0;
  return (
    <span
      className={cn(
        "mt-1 block rounded px-1.5 py-1 text-xs leading-snug text-foreground",
        take === 0 ? "bg-warning/15" : "bg-primary/10",
      )}
      data-testid="review-focus-summary"
    >
      {take > 0
        ? `Przyjdzie stąd ${people(take)}.`
        : available > 0
          ? "Masz już stąd całą porcję."
          : picked
            ? "Stąd nie przyjdzie nikt nowy: wolne osoby są już u tych, którzy wybrali ją wcześniej."
            : "Stąd nie przyjdzie nikt nowy: nikt z puli nie przechodzi reguł tej rekrutacji."}
      {release > 0
        ? ` ${releasedLine(release)}`
        : take > 0
          ? " Reszta Twojej porcji zostaje."
          : ""}
      {picked && take > 0
        ? " Kto wybrał wcześniej, ma już najlepsze osoby; Tobie przyjdą kolejne."
        : ""}
    </span>
  );
}

export function ReviewBatchFocusPicker({
  onClose,
  onChosen,
}: {
  onClose: () => void;
  /** Po wyborze: ekran przechodzi do „Do decyzji”, żeby od razu była osoba z wybranej. */
  onChosen?: () => void;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const options = useReviewBatchFocusOptions(true);
  const [picked, setPicked] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  if (options.isError) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {apiErrorMessage(options.error, "Nie udało się wczytać Twoich rekrutacji.")}
      </p>
    );
  }
  if (!options.isSuccess) {
    return <p className="text-sm text-muted-foreground">Ładowanie rekrutacji…</p>;
  }
  const { items, seats, focus } = options.data;
  const current = picked ?? focus?.job_id ?? null;
  const chosen = items.find((item) => item.job_id === current) ?? null;
  const groups = GROUP_ORDER.map((key) => ({
    key,
    jobs: items.filter((item) => (item.group ?? "p2") === key),
  })).filter((group) => group.jobs.length > 0);

  const choose = async () => {
    if (!chosen) return;
    setBusy(true);
    try {
      const result = await setReviewBatchFocus(chosen.job_id);
      invalidateReviewBatch(queryClient);
      showSuccess(
        `Doszło ${people(result.added)} z „${chosen.title}”.` +
          (result.released > 0 ? ` ${releasedLine(result.released)}` : ""),
      );
      onChosen?.();
      onClose();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wybrać rekrutacji."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2" data-testid="review-focus-picker">
      <div className="rounded-lg border border-primary/40 bg-primary/5 px-3 py-2">
        <div className="text-sm font-semibold">Nad którą rekrutacją pracujesz dziś?</div>
        <p className="mt-0.5 text-xs leading-snug text-muted-foreground">
          Porcja weźmie osoby najpierw z niej. Dziś dalej {people(seats)} do decyzji. Kto wybierze
          pierwszy, bierze najlepsze wolne osoby.
        </p>
        <div className="mt-2 flex gap-2">
          <Button
            size="sm"
            disabled={!chosen || busy || chosen.job_id === focus?.job_id}
            onClick={choose}
          >
            Biorę tę rekrutację
          </Button>
          <Button size="sm" variant="outline" onClick={onClose}>
            Anuluj
          </Button>
        </div>
      </div>
      {items.length === 0 ? (
        <p className="px-1 text-sm text-muted-foreground">
          Nie masz dziś rekrutacji, z których porcja może brać osoby.
        </p>
      ) : null}
      {groups.map((group) => (
        <section key={group.key}>
          <h2 className="mb-1 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {GROUP_TITLE[group.key]} <span className="tabular-nums opacity-70">{group.jobs.length}</span>
          </h2>
          <ul
            className={cn(
              "divide-y divide-border rounded-lg border bg-card",
              group.key === "p0" ? "border-destructive/40" : "border-border",
            )}
          >
            {group.jobs.map((option) => (
              <OptionRow
                key={option.job_id}
                option={option}
                selected={option.job_id === current}
                current={option.job_id === focus?.job_id}
                onSelect={() => setPicked(option.job_id)}
              />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** Koniec linii „Twoja porcja dziś”: wybór rekrutacji albo to, co wybrano. */
export function FocusLine({
  focusTitle,
  onChoose,
  onReset,
  resetting,
}: {
  focusTitle: string | null;
  onChoose: () => void;
  onReset: () => void;
  resetting: boolean;
}) {
  if (!focusTitle) {
    return (
      <button
        type="button"
        onClick={onChoose}
        className="text-xs font-semibold text-primary hover:underline"
        data-testid="review-focus-open"
        data-tour="review-batch.focus"
      >
        Wybierz rekrutację na dziś
      </button>
    );
  }
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-1 text-xs" data-testid="review-focus-line">
      <span className="text-muted-foreground">Najpierw z wybranej na dziś:</span>
      <span className="max-w-[360px] truncate rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
        {focusTitle}
      </span>
      <button type="button" onClick={onChoose} className="font-medium text-primary hover:underline">
        Zmień
      </button>
      <span className="text-muted-foreground">·</span>
      <button
        type="button"
        onClick={onReset}
        disabled={resetting}
        className="text-muted-foreground hover:underline disabled:opacity-60"
      >
        Wróć do zwykłej kolejności
      </button>
    </span>
  );
}
