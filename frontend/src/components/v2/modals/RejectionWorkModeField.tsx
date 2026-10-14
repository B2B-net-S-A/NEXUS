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

/** Co okno wysyła z ruchem, gdy wybrany jest ten powód. */
export interface RejectionWorkModeChoice {
  maxOnsiteDays: number;
  saveToProfile: boolean;
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
}

export function RejectionWorkModeField({
  job,
  profile,
  several,
  days,
  onDaysChange,
  saveToProfile,
  onSaveToProfileChange,
}: Props) {
  const choices = officeDaysChoices(job?.onsiteDaysPerWeek ?? null);
  const jobLine = jobWorkModeLine(job?.remotePolicy, job?.onsiteDaysPerWeek);
  const current = profile ? formatWorkMode(profile.modes, profile.days) : null;

  return (
    <div
      data-testid="rejection-work-mode"
      className="ml-6 space-y-2 rounded-md border border-border border-l-2 border-l-primary px-3 py-2.5"
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
