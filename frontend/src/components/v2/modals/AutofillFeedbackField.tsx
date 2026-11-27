"use client";

import type * as React from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  CLIENT_WIDE_REASONS,
  NOT_LOOKING_SPANS,
  autofillBucketHint,
  notLookingUntil as untilAfter,
  type AutofillLearnedFrom,
  type AutofillReason,
} from "@/lib/autofill-feedback";
import { OTHER_CLOSE_REASON, type CloseReasonGroup, type CloseReasonKey } from "@/lib/close-reasons";
import { formatIsoDatePl } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";
import { cn } from "@/lib/utils";

/**
 * Powód zamknięcia procesu w oknie odrzucenia. Od 19.11.2026 jeden słownik
 * (`lib/close-reasons.ts`) w każdej kolumnie: grupy liczy okno z „Kto
 * kończy?” i etapu (`groups`), „Inne” stoi zawsze na końcu. Przy osobie od
 * systemu (makieta A3, 23.10.2026) dochodzą „Skąd to wiesz?”, „Ile chce?”,
 * „na cały klient” i podpowiedź raportu. Powód z szablonu do raportu lejka
 * liczy okno (`closeTemplateReason`). Stan trzyma okno (`RejectionV2`);
 * `children` — pola pod powodem (stawka, tryb pracy, data „Nie szuka”).
 */
export function AutofillFeedbackField({
  learnedFrom,
  onLearnedFromChange,
  reason,
  onReasonChange,
  rate,
  onRateChange,
  rateKnown,
  several,
  askRate = true,
  wholeClient = false,
  onWholeClientChange,
  notLookingUntil = null,
  onNotLookingUntilChange,
  fromSystem = true,
  groups,
  children,
}: {
  learnedFrom: AutofillLearnedFrom | null;
  onLearnedFromChange: (value: AutofillLearnedFrom) => void;
  reason: CloseReasonKey | null;
  onReasonChange: (value: CloseReasonKey) => void;
  rate: string;
  onRateChange: (value: string) => void;
  /** Czy system znał stawkę w chwili dodania (jedna osoba). */
  rateKnown: boolean;
  /** Kilka osób od systemu naraz — ten sam powód, bez „Ile chce?”. */
  several: boolean;
  /** `false` — kwotę niesie pole pod powodem „za drogo” w oknie (26.10.2026). */
  askRate?: boolean;
  /** 27.10.2026: powód „klient” na cały klient (jedna osoba). */
  wholeClient?: boolean;
  onWholeClientChange?: (value: boolean) => void;
  /** 28.10.2026: „Nie szuka pracy” — do kiedy („RRRR-MM-DD”). */
  notLookingUntil?: string | null;
  onNotLookingUntilChange?: (value: string) => void;
  /** `false` — karta dodana ręcznie w „Nowych”/„Screeningu” (19.11.2026): ta
   *  sama lista powodów, ale bez „Skąd to wiesz?” i podpowiedzi raportu
   *  wyszukiwania — powód idzie tylko do raportu lejka. */
  fromSystem?: boolean;
  /** Grupy słownika dla tego, kto kończy, i etapu (`closeReasonGroups`). */
  groups: CloseReasonGroup[];
  children?: React.ReactNode;
}) {
  // Przy osobie od systemu (tylko odrzucenie) słownik daje powody dla systemu.
  const systemReason = fromSystem ? (reason as AutofillReason | null) : null;
  const hint = systemReason ? autofillBucketHint(systemReason, rateKnown) : null;
  return (
    <div className="space-y-3" data-testid="autofill-feedback">
      <FormField
        label="Powód"
        required
        description={
          fromSystem
            ? `${several ? "Wśród odrzucanych są osoby od systemu" : "To osoba od systemu"} — powód trafia do raportu lejka i uczy system, co poprawić w podpowiedziach.`
            : undefined
        }
      >
        <RadioGroup
          value={reason ?? ""}
          onValueChange={(v) => onReasonChange(v as CloseReasonKey)}
          className="grid gap-x-4 gap-y-2 sm:grid-cols-3"
          data-tour="rejection.close-reasons"
        >
          {reasonColumns(groups).map((column, index) => (
            <div key={index} className="min-w-0 space-y-2">
              {column.map((group) =>
                group ? (
                  <fieldset key={group.title} className="min-w-0 space-y-0.5">
                    <legend className="pb-0.5 text-xs font-semibold text-muted-foreground">{group.title}</legend>
                    {group.reasons.map((r) => (
                      <ReasonOption key={r.key} value={r.key} label={r.label} />
                    ))}
                  </fieldset>
                ) : (
                  <fieldset key="other" className="min-w-0 space-y-0.5">
                    <legend className="sr-only">Inne</legend>
                    <ReasonOption value={OTHER_CLOSE_REASON.key} label={OTHER_CLOSE_REASON.label} />
                  </fieldset>
                ),
              )}
            </div>
          ))}
        </RadioGroup>
      </FormField>
      {children}
      {systemReason && CLIENT_WIDE_REASONS.has(systemReason) && !several && onWholeClientChange ? (
        <label
          htmlFor="autofill-whole-client"
          className="flex cursor-pointer items-start gap-2 rounded-md border border-primary/30 bg-primary/5 p-2 text-sm"
          data-testid="autofill-whole-client"
        >
          <Checkbox
            id="autofill-whole-client"
            checked={wholeClient}
            onCheckedChange={(value) => onWholeClientChange(value === true)}
            className="mt-0.5"
          />
          <span>
            Dotyczy wszystkich rekrutacji tego klienta: zdejmij tę osobę z pozostałych (karty od
            systemu, których nikt nie ruszył) i nie podsuwaj jej więcej temu klientowi.
          </span>
        </label>
      ) : null}
      {reason === "not_looking" && onNotLookingUntilChange ? (
        <NotLookingUntilField
          value={notLookingUntil}
          onChange={onNotLookingUntilChange}
          several={several}
        />
      ) : null}
      {fromSystem && reason === "too_expensive" && !several && askRate ? (
        <FormField
          label="Ile chce? (zł/h, opcjonalnie)"
          description="Zapisze się jako „Stawka od” w profilu."
        >
          <Input
            inputMode="decimal"
            value={rate}
            onChange={(e) => onRateChange(e.target.value)}
            placeholder="np. 175"
            className="w-32"
            aria-label="Ile chce w złotych na godzinę"
          />
        </FormField>
      ) : null}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      {fromSystem ? (
      <FormField label="Skąd to wiesz?" required>
        <RadioGroup
          value={learnedFrom ?? ""}
          onValueChange={(v) => onLearnedFromChange(v as AutofillLearnedFrom)}
          className="grid gap-2 sm:grid-cols-2"
        >
          {(
            [
              { value: "profile", label: "Z CV i profilu, bez kontaktu" },
              { value: "call", label: "Z rozmowy z osobą" },
            ] as const
          ).map((o) => (
            <label
              key={o.value}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm",
                learnedFrom === o.value ? "border-primary bg-primary/5" : "border-border hover:bg-accent",
              )}
            >
              <RadioGroupItem value={o.value} />
              {o.label}
            </label>
          ))}
        </RadioGroup>
      </FormField>
      ) : null}
    </div>
  );
}

/**
 * Grupy w trzech kolumnach, każda do najkrótszej (liczą się wiersze z
 * nagłówkiem), „Inne” (`null`) na końcu najkrótszej. Przy 1280 × 720 siatka
 * wierszami zostawiała dziurę pod krótkimi „Warunkami” i spychała „Dane
 * w bazie” i „Inne” pod zgięcie okna.
 */
export function reasonColumns(groups: CloseReasonGroup[]): (CloseReasonGroup | null)[][] {
  const columns: (CloseReasonGroup | null)[][] = [[], [], []];
  const heights = [0, 0, 0];
  const shortest = () => heights.indexOf(Math.min(...heights));
  for (const group of groups) {
    const i = shortest();
    columns[i].push(group);
    heights[i] += group.reasons.length + 1;
  }
  columns[shortest()].push(null);
  return columns.filter((column) => column.length > 0);
}

function ReasonOption({ value, label }: { value: CloseReasonKey; label: string }) {
  return (
    <label
      className="flex cursor-pointer items-start gap-2 rounded-md px-1 py-0.5 text-sm hover:bg-primary/10"
      // Kropki „Nowość” przy powodach (`novelties.json`, `dot_anchor`); kotwica
      // musi stać dosłownie w tej linii (`novelty-anchors.test.ts`).
      data-tour={value === "accepted_other_offer" ? "rejection.employed-elsewhere" : value === "not_looking" ? "rejection.not-looking" : value === "outside_poland" ? "rejection.outside-poland" : value === "location_mode" ? "rejection.location-mode" : undefined}
    >
      <RadioGroupItem value={value} className="mt-0.5" />
      <span>{label}</span>
    </label>
  );
}

/**
 * „Do kiedy nie podsuwać?” przy „Nie szuka pracy” (makieta M1, 28.10.2026):
 * 9 z 44 odrzuceń, a te same osoby czekały w „Nowych” innych rekrutacji.
 */
/** „Do kiedy nie podsuwać?” — przy osobie od systemu i (19.11.2026) przy
 *  „Nie szuka pracy” na karcie dodanej ręcznie. */
export function NotLookingUntilField({
  value,
  onChange,
  several,
}: {
  value: string | null;
  onChange: (value: string) => void;
  several: boolean;
}) {
  const spans = NOT_LOOKING_SPANS.map((s) => ({ ...s, date: untilAfter(s.months) }));
  const custom = value != null && !spans.some((s) => s.date === value);
  // Serwer przyjmuje datę od jutra (dziś = „już szuka”).
  const tomorrow = new Date(`${warsawToday()}T00:00:00Z`);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  const chip = (active: boolean) =>
    cn(
      "rounded-full border px-3 py-1 text-sm",
      active ? "border-primary bg-primary/10 font-medium text-primary" : "border-border hover:bg-accent",
    );
  return (
    <FormField
      label="Do kiedy nie podsuwać?"
      description={`Zapiszemy w profilu „Nie szuka” i „Dostępny od ${formatIsoDatePl(value)}”. Do tej daty system nie doda ${
        several ? "tych osób" : "tej osoby"
      } do żadnej rekrutacji i zdejmie ${several ? "ich" : "jej"} karty od systemu z innych rekrutacji, których nikt nie ruszył.`}
    >
      <div className="flex flex-wrap items-center gap-2" data-testid="autofill-not-looking-until">
        {spans.map((s) => (
          <button
            key={s.months}
            type="button"
            className={chip(s.date === value)}
            aria-pressed={s.date === value}
            onClick={() => onChange(s.date)}
          >
            {s.label}
          </button>
        ))}
        <Input
          type="date"
          value={value ?? ""}
          min={tomorrow.toISOString().slice(0, 10)}
          max={untilAfter(24)}
          onChange={(e) => e.target.value && onChange(e.target.value)}
          className={cn("w-40", custom && "border-primary")}
          aria-label="Nie szuka do dnia"
        />
      </div>
    </FormField>
  );
}

/** „175”, „175,50” → 175.5; puste albo zło → `null`. */
export function parseRateInput(raw: string): number | null {
  const value = Number(raw.trim().replace(/\s/g, "").replace(",", "."));
  return raw.trim() && Number.isFinite(value) && value > 0 && value <= 10000 ? value : null;
}
