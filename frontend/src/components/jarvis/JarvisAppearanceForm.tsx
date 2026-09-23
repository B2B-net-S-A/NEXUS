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
import { Lock, X } from "lucide-react";
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
  /** „Pokaż wskazówki od nowa” — czyści listę obejrzanych ekranów. */
  onResetTips?: () => void;
}

const MAX_NOTES = 10;
const MAX_NOTE_CHARS = 200;
const NOTE_PATTERN = /^[^<>{}[\]`]+$/;

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
  onResetTips,
}: Props) {
  const [noteDraft, setNoteDraft] = useState("");
  const [tipsReset, setTipsReset] = useState(false);
  const [draft, setDraft] = useState<JarvisPrefs>({
    character: prefs.character,
    name: prefs.name,
    accent: prefs.accent,
    enabled: prefs.enabled,
    minimized: prefs.minimized,
    sound: prefs.sound,
    daily_brief: prefs.daily_brief,
    screen_tips: prefs.screen_tips ?? true,
    notes: prefs.notes ?? [],
  });
  const cleanNote = noteDraft.replace(/\s+/g, " ").trim();
  const noteError =
    cleanNote.length === 0
      ? null
      : cleanNote.length > MAX_NOTE_CHARS
        ? `Najwyżej ${MAX_NOTE_CHARS} znaków.`
        : !NOTE_PATTERN.test(cleanNote)
          ? "Bez znaków < > { } [ ] `."
          : null;
  const canAddNote = cleanNote.length > 0 && !noteError && draft.notes.length < MAX_NOTES;
  function addNote() {
    if (!canAddNote || draft.notes.includes(cleanNote)) return;
    setDraft((d) => ({ ...d, notes: [...d.notes, cleanNote] }));
    setNoteDraft("");
  }
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
          label="Wskazówki na nowych ekranach"
          hint="Przy pierwszej wizycie na ekranie dymek podpowie, co się tu robi (najwyżej 3 dziennie)."
          checked={draft.screen_tips}
          onChange={(v) => setDraft((d) => ({ ...d, screen_tips: v }))}
        />
        {onResetTips && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              {tipsReset ? "Wskazówki pokażą się znowu na każdym ekranie." : "Chcesz zobaczyć wskazówki jeszcze raz?"}
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                onResetTips();
                setTipsReset(true);
              }}
            >
              Pokaż wskazówki od nowa
            </Button>
          </div>
        )}
        <ToggleRow
          label="Dźwięk"
          hint="Krótki sygnał, gdy asystent skończy odpowiadać."
          checked={draft.sound}
          onChange={(v) => setDraft((d) => ({ ...d, sound: v }))}
        />
      </div>

      <fieldset className="space-y-2" data-testid="jarvis-notes">
        <legend className="text-sm font-medium">Co {cleanName || "asystent"} o mnie wie</legend>
        <p className="text-xs text-muted-foreground">
          Twoje preferencje, np. „odpowiadaj krótko”, „moi klienci to X i Y”. Asystent bierze je pod uwagę
          w każdej rozmowie. Nie wpisuj tu danych kandydatów.
        </p>
        {draft.notes.length > 0 ? (
          <ul className="space-y-1">
            {draft.notes.map((note) => (
              <li key={note} className="flex items-start gap-2 rounded-md border border-border px-2.5 py-1.5 text-sm">
                <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{note}</span>
                <button
                  type="button"
                  onClick={() => setDraft((d) => ({ ...d, notes: d.notes.filter((n) => n !== note) }))}
                  className="shrink-0 text-muted-foreground hover:text-destructive"
                  aria-label={`Usuń: ${note}`}
                >
                  <X className="h-4 w-4" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">Na razie nic.</p>
        )}
        <div className="flex gap-2">
          <input
            value={noteDraft}
            onChange={(e) => setNoteDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addNote();
              }
            }}
            maxLength={MAX_NOTE_CHARS + 20}
            disabled={draft.notes.length >= MAX_NOTES}
            placeholder={draft.notes.length >= MAX_NOTES ? `Najwyżej ${MAX_NOTES} pozycji` : "Dodaj preferencję…"}
            aria-label="Nowa preferencja"
            className="h-9 min-w-0 flex-1 rounded-md border border-border bg-background px-3 text-sm outline-none focus:border-primary"
          />
          <Button type="button" size="sm" variant="outline" disabled={!canAddNote} onClick={addNote}>
            Dodaj
          </Button>
        </div>
        {noteError && <p className="text-xs text-destructive">{noteError}</p>}
      </fieldset>

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
