"use client";

/**
 * Zakładka „Generator": blokady, przez które rekruter przestaje wybierać.
 *
 * Tryb obróbki treści ma trzy stany: wolny wybór, domyślny (zaznaczony,
 * rekruter może zmienić) i zablokowany (serwer NADPISUJE żądanie, kafelki
 * w generatorze są wyłączone). Sufit z karty klienta jest nakładany PO
 * blokadzie i nadal wygrywa — dlatego oba pola są tu obok siebie.
 *
 * Wymagane wejścia blokują generację czytelnym 422 PRZED naliczeniem kwoty,
 * tym samym kanałem co zrzut zgody u PKO BP.
 */

import { CV_CONTENT_MODES } from "@/lib/cv-generator";
import type { CvContentMode } from "@/lib/cv-generator";
import type { CvRuleForm } from "@/lib/cv-rules";

import type { CvRuleTabProps } from "./CvRuleBasicsTab";

const MODE_LABEL: Record<CvContentMode, string> = Object.fromEntries(
  CV_CONTENT_MODES.map((m) => [m.value, m.label]),
) as Record<CvContentMode, string>;

export function CvRuleGeneratorTab({ form, set }: CvRuleTabProps) {
  const modePolicy: "free" | "default" | "locked" = !form.content_mode
    ? "free"
    : form.content_mode_locked
      ? "locked"
      : "default";

  const setModePolicy = (policy: "free" | "default" | "locked") => {
    if (policy === "free") {
      set("content_mode", "");
      set("content_mode_locked", false);
      return;
    }
    if (!form.content_mode) set("content_mode", "polished");
    set("content_mode_locked", policy === "locked");
  };

  return (
    <div className="space-y-6">
      <fieldset className="space-y-2">
        <legend className="text-xs font-medium">Tryb obróbki treści</legend>
        <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Polityka trybu">
          {(
            [
              ["free", "Wolny wybór rekrutera"],
              ["default", "Domyślny, rekruter może zmienić"],
              ["locked", "Zawsze ten tryb"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={modePolicy === value}
              onClick={() => setModePolicy(value)}
              className={
                modePolicy === value
                  ? "rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground"
                  : "rounded-md border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-muted"
              }
            >
              {label}
            </button>
          ))}
        </div>
        {modePolicy !== "free" ? (
          <select
            aria-label="Tryb obróbki treści"
            value={form.content_mode}
            onChange={(e) =>
              set("content_mode", e.target.value as CvRuleForm["content_mode"])
            }
            className="rounded-md border px-3 py-2 text-sm"
          >
            {CV_CONTENT_MODES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        ) : null}
        <p className="text-xs text-muted-foreground">
          {modePolicy === "locked"
            ? `Rekruter zobaczy kafelki wyłączone z dopiskiem „ustalone przez Delivery Leada” — serwer i tak zastosuje „${MODE_LABEL[form.content_mode as CvContentMode] ?? ""}”.`
            : modePolicy === "default"
              ? "Kafelek będzie zaznaczony po wybraniu klienta; rekruter może go zmienić."
              : "Rekruter wybiera tryb sam, w granicach sufitu poniżej."}
        </p>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium" htmlFor="cvrule-cap">
            Sufit trybu treści (karta klienta)
          </label>
          <select
            id="cvrule-cap"
            value={form.cv_content_mode_cap}
            onChange={(e) =>
              set(
                "cv_content_mode_cap",
                e.target.value as CvRuleForm["cv_content_mode_cap"],
              )
            }
            className="rounded-md border px-3 py-2 text-sm"
          >
            <option value="">Bez sufitu</option>
            {CV_CONTENT_MODES.map((m) => (
              <option key={m.value} value={m.value}>
                maks. {m.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-muted-foreground">
            Obietnica złożona klientowi („nie profilujcie pod ogłoszenie”).
            Wygrywa z każdym wyborem i z blokadą powyżej.
          </p>
        </div>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={form.cv_interactive_enabled}
            onChange={(e) => set("cv_interactive_enabled", e.target.checked)}
          />
          <span>
            Interaktywna wersja CV na linku dla klienta
            <span className="block text-xs text-muted-foreground">
              Kafelki must/nice-have z dowodami z CV + chat AI. Wyłącz, jeśli
              klient ma dostawać wyłącznie klasyczny widok dokumentu.
            </span>
          </span>
        </label>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium">
          Wymagane wejścia — bez nich generacja nie ruszy
        </legend>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="cvrule-notes-min">Notatki ze screeningu: co najmniej</label>
          <input
            id="cvrule-notes-min"
            type="number"
            min={0}
            max={20000}
            step={50}
            value={form.require_screening_notes_min_chars}
            onChange={(e) => set("require_screening_notes_min_chars", e.target.value)}
            placeholder="0"
            className="w-24 rounded-md border px-2 py-1 text-sm"
          />
          <span className="text-muted-foreground">znaków (puste = bez wymogu)</span>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.require_project_ref}
            onChange={(e) => set("require_project_ref", e.target.checked)}
          />
          Wymagany numer / nazwa projektu
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.require_position}
            onChange={(e) => set("require_position", e.target.checked)}
          />
          Wymagane stanowisko (tryb upload; z procesu bierze się samo)
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.require_champion}
            onChange={(e) => set("require_champion", e.target.checked)}
          />
          Wymagany Profil Championa (wymagania must / nice-to-have)
        </label>
      </fieldset>

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={form.auto_second_language}
          onChange={(e) => set("auto_second_language", e.target.checked)}
          disabled={!form.requires_en_copy || !!form.cv_language}
        />
        <span>
          Drugą wersję językową generuj automatycznie
          <span className="block text-xs text-muted-foreground">
            Działa tylko przy „klient oczekuje obu wersji” i bez wymuszonego
            języka. To drugie wywołanie najdroższego modelu w produkcie — osobny
            wiersz na liście, osobna kwota.
          </span>
        </span>
      </label>
    </div>
  );
}
