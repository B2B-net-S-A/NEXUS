"use client";

/**
 * Powód „Nie akceptuje trybu pracy” w oknie odrzucenia (14.10.2026, D2–D3).
 *
 * Po wybraniu powodu okno pyta, ile dni w biurze kandydat akceptuje (domyślnie
 * „Tylko zdalnie”, do wyboru tylko mniej, niż wymaga rekrutacja), i pokazuje,
 * co trafi na profil. Zapis robi serwer przy ruchu karty
 * (`work_mode_max_onsite_days`, `work_mode_save_to_profile`); bez tego
 * rekruter wybierał „Inne” i pisał „zdalnie” w notatce, której nie widziało
 * ani wyszukiwanie, ani profil.
 */

import type * as React from "react";

import { FormField } from "@/components/ui/form-field";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  formatWorkMode,
  jobWorkModeLine,
  officeDaysChoiceLabel,
  officeDaysChoices,
  workModeAfterRejection,
  type WorkMode,
} from "@/lib/work-mode";

export interface RejectionWorkModeJob {
  remotePolicy: string | null;
  onsiteDaysPerWeek: number | null;
}

export interface RejectionWorkModeProfile {
  modes: WorkMode[];
  days: number | null;
}

/** „Co nie pasuje?” przy „Lokalizacja lub tryb pracy” (wariant D, 27.11.2026). */
export type RejectionWorkModeIssue = "distance" | "office_days";

/** Co okno wysyła z ruchem, gdy wybrany jest ten powód. Pola od 27.11.2026
 *  (karta dojazdu) są opcjonalne: formularze bez pytania „Co nie pasuje?”
 *  wysyłają same dni, jak dotąd. */
export interface RejectionWorkModeChoice {
  /** `null` — stare wywołania bez pytania „Co nie pasuje?”. */
  issue?: RejectionWorkModeIssue | null;
  /** Przy „Za daleko do biura” opcjonalne („Nie pytałem” = `null`). */
  maxOnsiteDays: number | null;
  saveToProfile: boolean;
  residenceCity?: string | null;
  officeCities?: string[];
  occasionalCommute?: boolean | null;
  relocationWilling?: boolean | null;
  relocationTargets?: string[];
  acceptsMoreOfficeDays?: boolean | null;
}

/** Pola ruchu karty (`PipelineMove`) z wyboru okna; `null` i puste listy
 *  pomijamy — serwer czyta brak pola jako „nie pytano”. */
export function rejectionWorkModeMoveFields(choice: RejectionWorkModeChoice | null | undefined): {
  work_mode_issue?: RejectionWorkModeIssue;
  work_mode_max_onsite_days?: number;
  work_mode_save_to_profile?: boolean;
  residence_city?: string;
  commute_office_cities?: string[];
  occasional_commute?: boolean;
  relocation_willing?: boolean;
  relocation_targets?: string[];
  accepts_more_office_days?: boolean;
} {
  if (!choice) return {};
  const days =
    choice.maxOnsiteDays != null ? { work_mode_max_onsite_days: choice.maxOnsiteDays } : {};
  // Bez „Co nie pasuje?” serwer odrzuca pola karty dojazdu (422) — same dni.
  if (!choice.issue) return { ...days, work_mode_save_to_profile: choice.saveToProfile };
  const city = choice.residenceCity?.trim();
  const cities = (list: string[] | undefined) =>
    (list ?? []).map((c) => c.trim()).filter(Boolean);
  const officeCities = cities(choice.officeCities);
  const targets = cities(choice.relocationTargets);
  return {
    work_mode_issue: choice.issue,
    ...days,
    work_mode_save_to_profile: choice.saveToProfile,
    ...(city ? { residence_city: city } : {}),
    ...(officeCities.length ? { commute_office_cities: officeCities } : {}),
    ...(choice.occasionalCommute != null ? { occasional_commute: choice.occasionalCommute } : {}),
    ...(choice.relocationWilling != null ? { relocation_willing: choice.relocationWilling } : {}),
    ...(choice.relocationWilling === true && targets.length
      ? { relocation_targets: targets }
      : {}),
    ...(choice.acceptsMoreOfficeDays != null
      ? { accepts_more_office_days: choice.acceptsMoreOfficeDays }
      : {}),
  };
}

interface Props {
  /** Tryb pracy rekrutacji; `null` — nieznany (do wyboru 0–4 dni). */
  job: RejectionWorkModeJob | null;
  /** Tryb pracy z profilu — tylko przy jednej osobie. `undefined` = nie
   *  pokazujemy „Teraz na profilu” (kilka osób albo profil niewczytany). */
  profile?: RejectionWorkModeProfile | null;
  several: boolean;
  days: number;
  onDaysChange: (days: number) => void;
  saveToProfile: boolean;
  onSaveToProfileChange: (save: boolean) => void;
  /** Wcięcie pod pozycją listy powodów (okno odrzucenia); bez listy — `false`. */
  inset?: boolean;
  /** `false` — bez własnej ramki (pole w ramce „Co nie pasuje?”). */
  framed?: boolean;
  /** Dodatkowe pytanie między dniami a zapisem na profilu. */
  extra?: React.ReactNode;
  /** Dodatkowa pozycja zapisu na profilu, np. zgoda na więcej dni. */
  saveExtra?: string | null;
}

export function RejectionWorkModeField({
  job,
  profile,
  several,
  days,
  onDaysChange,
  saveToProfile,
  onSaveToProfileChange,
  inset = true,
  framed = true,
  extra,
  saveExtra,
}: Props) {
  const choices = officeDaysChoices(job?.onsiteDaysPerWeek ?? null);
  const jobLine = jobWorkModeLine(job?.remotePolicy, job?.onsiteDaysPerWeek);
  const current = profile ? formatWorkMode(profile.modes, profile.days) : null;

  return (
    <div
      data-testid="rejection-work-mode"
      className={
        framed
          ? `${inset ? "ml-6 " : ""}space-y-2 rounded-md border border-border border-l-2 border-l-primary px-3 py-2.5`
          : "space-y-2"
      }
    >
      <FormField
        label="Ile dni w biurze kandydat akceptuje?"
        required
        description={jobLine ? `Ta rekrutacja: ${jobLine}.` : undefined}
      >
        <RadioGroup
          value={String(days)}
          onValueChange={(value) => onDaysChange(Number(value))}
          aria-label="Ile dni w biurze kandydat akceptuje"
          className="flex flex-wrap gap-2"
        >
          {choices.map((choice) => (
            <label
              key={choice}
              className={`flex cursor-pointer items-center gap-2 rounded-full border px-3 py-1 text-sm ${
                days === choice
                  ? "border-primary bg-primary/5 font-medium"
                  : "border-border hover:bg-accent"
              }`}
            >
              <RadioGroupItem value={String(choice)} />
              {officeDaysChoiceLabel(choice)}
            </label>
          ))}
        </RadioGroup>
      </FormField>

      {extra}

      <label className="flex cursor-pointer items-start gap-2 rounded-md p-1.5 text-sm hover:bg-primary/10">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))] text-primary focus:ring-primary"
          checked={saveToProfile}
          onChange={(e) => onSaveToProfileChange(e.target.checked)}
        />
        <span>
          {several ? "Zapisz na profilach kandydatów" : "Zapisz na profilu kandydata"}:{" "}
          <span className="font-medium">Tryb pracy → {workModeAfterRejection(days)}</span>
          {saveExtra ? (
            <span className="block font-medium" data-testid="rejection-work-mode-save-extra">
              {saveExtra}
            </span>
          ) : null}
          {!several && profile !== undefined ? (
            <span
              data-testid="rejection-work-mode-current"
              className="block text-xs text-muted-foreground"
            >
              Teraz na profilu: {current ?? "Nie uzupełniono"}
            </span>
          ) : null}
        </span>
      </label>
    </div>
  );
}
