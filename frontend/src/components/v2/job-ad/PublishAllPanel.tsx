"use client";

/**
 * „Opublikuj ogłoszenie” — jeden przycisk na kanały, których jeszcze nie ma
 * (07.11.2026, makiety https://claude.ai/artifact/JMTL5qwBym7Twd2dU1uYsb, rekomendacja 1).
 *
 * Do tej daty okno miało trzy karty i cztery różne przyciski. Panel zbiera
 * kanały, które da się teraz opublikować, i prowadzi po kolei: strona kariery
 * od razu, potem okno JustJoin.IT (kategoria portalu), potem mail do opiekuna
 * Pracuj.pl (stawka). Karty kanałów pod spodem zostają — stan i szczegóły.
 * Kolejność kroków liczy `planPublish`; panel nie publikuje sam niczego poza
 * stroną kariery.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";

export type PublishChannel = "kariera" | "jjit" | "pracuj";

export interface PublishOption {
  channel: PublishChannel;
  label: string;
  hint: string;
  /** Domyślnie zaznaczony. */
  checked: boolean;
}

export interface PublishAvailability {
  career: boolean;
  /** Strona kariery jest potrzebna kandydatom (tryb linku, nie formularz JJIT). */
  careerNeededForJjit: boolean;
  jjit: boolean;
  pracuj: boolean;
}

/** Kanały do wyboru — tylko te, które da się teraz opublikować. */
export function publishOptions(a: PublishAvailability): PublishOption[] {
  const out: PublishOption[] = [];
  if (a.jjit) {
    out.push({
      channel: "jjit",
      label: "JustJoin.IT",
      hint: a.careerNeededForJjit
        ? "API; kandydat aplikuje przez stronę kariery."
        : "API, formularz JJIT — bez strony kariery.",
      checked: true,
    });
  }
  if (a.pracuj) {
    out.push({
      channel: "pracuj",
      label: "Pracuj.pl",
      hint: "Mail do opiekuna konta, stawkę wpiszesz w następnym kroku.",
      checked: true,
    });
  }
  if (a.career) {
    out.push({
      channel: "kariera",
      label: "Strona kariery",
      hint: a.careerNeededForJjit
        ? "Potrzebna, żeby kandydaci z JustJoin.IT mieli gdzie aplikować."
        : "Link do wysłania kandydatowi i przy poleceniu.",
      checked: a.careerNeededForJjit && a.jjit,
    });
  }
  return out;
}

/** Kolejność kroków: strona kariery najpierw (bez okna), potem okna portali. */
export function planPublish(selected: readonly PublishChannel[]): {
  career: boolean;
  dialogs: ("jjit" | "pracuj")[];
} {
  return {
    career: selected.includes("kariera"),
    dialogs: (["jjit", "pracuj"] as const).filter((c) => selected.includes(c)),
  };
}

export interface PublishAllPanelProps {
  options: readonly PublishOption[];
  busy?: boolean;
  onStart: (selected: PublishChannel[]) => void;
}

export function PublishAllPanel({ options, busy = false, onStart }: PublishAllPanelProps) {
  const [checked, setChecked] = useState<Set<PublishChannel>>(
    () => new Set(options.filter((o) => o.checked).map((o) => o.channel)),
  );
  // Mniej niż dwa kanały do wyboru = wystarczy przycisk na karcie kanału.
  if (options.length < 2) return null;
  const selected = options.map((o) => o.channel).filter((c) => checked.has(c));
  return (
    <section
      data-testid="publish-all"
      data-tour="job-ad.publish-all"
      aria-label="Opublikuj ogłoszenie"
      className="flex flex-col gap-2 rounded-md border border-primary/30 bg-primary/5 p-3"
    >
      <h2 className="text-sm font-semibold text-foreground">Opublikuj ogłoszenie</h2>
      <ul className="flex flex-col gap-1.5">
        {options.map((o) => (
          <li key={o.channel}>
            <label className="flex cursor-pointer items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 accent-[var(--primary)]"
                checked={checked.has(o.channel)}
                data-testid={`publish-all-${o.channel}`}
                onChange={(e) =>
                  setChecked((prev) => {
                    const next = new Set(prev);
                    if (e.target.checked) next.add(o.channel);
                    else next.delete(o.channel);
                    return next;
                  })
                }
              />
              <span>
                <span className="font-medium text-foreground">{o.label}</span>
                <span className="block text-xs text-muted-foreground">{o.hint}</span>
              </span>
            </label>
          </li>
        ))}
      </ul>
      <Button
        type="button"
        size="sm"
        className="self-start"
        disabled={selected.length === 0 || busy}
        loading={busy}
        data-testid="publish-all-start"
        onClick={() => onStart(selected)}
      >
        {selected.length === 0
          ? "Zaznacz kanał"
          : selected.length === 1
            ? "Opublikuj na 1 kanale"
            : `Opublikuj na ${selected.length} kanałach`}
      </Button>
    </section>
  );
}
