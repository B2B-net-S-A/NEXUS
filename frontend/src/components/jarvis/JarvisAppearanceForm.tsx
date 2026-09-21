"use client";

/**
 * Wygląd i zachowanie asystenta: postać (gotowe ilustracje), własne imię,
 * akcent, dźwięk, zwinięcie, poranny skrót. Prezentacyjny formularz — zapis
 * robi wołający (`PATCH /api/users/me/preferences`), harness pokazuje go bez sieci.
 *
 * Postaci zablokowane (Liga Mistrzów) są widoczne z kłódką i opisem, jak je
 * odblokować — ukrycie ich zabrałoby motywację, o którą w nich chodzi.
 */

import { useEffect, useState } from "react";
import { Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type { JarvisPrefs, JarvisPrefsResponse } from "@/lib/jarvis/types";
import { JARVIS_ACCENTS, JARVIS_CHARACTERS, JarvisCharacter } from "./characters/JarvisCharacter";

interface Props {
  prefs: JarvisPrefsResponse;
  saving?: boolean;
  error?: string | null;
  onSave: (next: Partial<JarvisPrefs>) => void;
  onCancel: () => void;
  /** Id formularza — przyciski mogą stać POZA nim (stopka okna) i wysyłać go przez `form=`. */
  formId?: string;
  /** W oknie przyciski są w stałej stopce, żeby nie dało się ich uciąć (zgłoszenie 21.09). */
  hideActions?: boolean;
  /** Informuje wołającego, czy imię jest poprawne (blokada „Zapisz” w stopce). */
  onValidityChange?: (valid: boolean) => void;
}

const NAME_PATTERN = /^[^<>{}[\]`]{1,24}$/;

export function JarvisAppearanceForm({
  prefs,
  saving = false,
  error,
  onSave,
  onCancel,
  formId,
  hideActions = false,
  onValidityChange,
}: Props) {
  const [draft, setDraft] = useState<JarvisPrefs>({
    character: prefs.character,
    name: prefs.name,
    accent: prefs.accent,
    enabled: prefs.enabled,
    minimized: prefs.minimized,
    sound: prefs.sound,
    daily_brief: prefs.daily_brief,
  });
  const cleanName = draft.name.replace(/\s+/g, " ").trim();
  const nameError =
    cleanName.length === 0
      ? "Podaj imię."
      : !NAME_PATTERN.test(cleanName)
        ? "Imię może mieć do 24 znaków, bez znaków specjalnych."
        : null;

  useEffect(() => {
    onValidityChange?.(!nameError);
  }, [nameError, onValidityChange]);

  return (
    <form
      id={formId}
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (!nameError) onSave({ ...draft, name: cleanName });
      }}
    >
      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Postać</legend>
        <div className="grid grid-cols-5 gap-2">
          {JARVIS_CHARACTERS.map((c) => {
            const unlocked = prefs.unlocked_characters.includes(c.id);
            const selected = draft.character === c.id;
            return (
              <button
                key={c.id}
                type="button"
                disabled={!unlocked}
                onClick={() => setDraft((d) => ({ ...d, character: c.id }))}
                aria-pressed={selected}
                aria-label={unlocked ? c.label : `${c.label} — zablokowana`}
                title={unlocked ? c.label : prefs.locked_characters[c.id] ?? "Zablokowana"}
                className={`relative flex flex-col items-center gap-1 rounded-lg border p-1.5 text-[10px] transition-colors ${
                  selected ? "border-primary bg-primary/10" : "border-border hover:bg-muted"
                } disabled:cursor-not-allowed`}
              >
                <span className={unlocked ? "" : "opacity-35 grayscale"}>
                  <JarvisCharacter id={c.id} accent={draft.accent} mood="idle" size={44} />
                </span>
                <span className="w-full truncate text-center">{c.label}</span>
                {!unlocked && <Lock className="absolute right-1 top-1 h-3 w-3 text-muted-foreground" aria-hidden />}
              </button>
            );
          })}
        </div>
        {Object.values(prefs.locked_characters).length > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            Postaci z kłódką odblokowujesz wynikiem w Lidze Mistrzów.
          </p>
        )}
      </fieldset>

      <div>
        <label htmlFor="jarvis-name" className="mb-1 block text-sm font-semibold">
          Imię asystenta
        </label>
        <input
          id="jarvis-name"
          value={draft.name}
          maxLength={24}
          onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-ring/30"
          aria-invalid={Boolean(nameError)}
        />
        {nameError && <p className="mt-1 text-xs text-destructive">{nameError}</p>}
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Kolor</legend>
        <div className="flex flex-wrap gap-2">
          {JARVIS_ACCENTS.map((a) => (
            <button
              key={a.id}
              type="button"
              onClick={() => setDraft((d) => ({ ...d, accent: a.id }))}
              aria-pressed={draft.accent === a.id}
              title={a.label}
              aria-label={a.label}
              className={`h-8 w-8 rounded-full border-2 ${draft.accent === a.id ? "border-foreground" : "border-transparent"}`}
              style={{ background: a.color }}
            />
          ))}
        </div>
      </fieldset>

      <div className="space-y-3">
        <ToggleRow
          label="Pokazuj asystenta"
          hint="Wyłączony nie pojawia się w rogu ekranu. Otworzysz go dalej skrótem ⌘J."
          checked={draft.enabled}
          onChange={(v) => setDraft((d) => ({ ...d, enabled: v }))}
        />
        <ToggleRow
          label="Mała ikona"
          hint="Zamiast postaci — dyskretna ikona w rogu."
          checked={draft.minimized}
          onChange={(v) => setDraft((d) => ({ ...d, minimized: v }))}
        />
        <ToggleRow
          label="Poranny skrót dnia"
          hint="Raz dziennie dymek z liczbą powiadomień i dzisiejszych spotkań."
          checked={draft.daily_brief}
          onChange={(v) => setDraft((d) => ({ ...d, daily_brief: v }))}
        />
        <ToggleRow
          label="Dźwięk"
          hint="Krótki sygnał, gdy asystent skończy odpowiadać."
          checked={draft.sound}
          onChange={(v) => setDraft((d) => ({ ...d, sound: v }))}
        />
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {!hideActions && (
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>
            Anuluj
          </Button>
          <Button type="submit" loading={saving} disabled={Boolean(nameError)}>
            Zapisz
          </Button>
        </div>
      )}
    </form>
  );
}

function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  const id = `jarvis-toggle-${label.replace(/\s+/g, "-").toLowerCase()}`;
  return (
    <div className="flex items-start justify-between gap-3">
      <div>
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onChange} />
    </div>
  );
}
