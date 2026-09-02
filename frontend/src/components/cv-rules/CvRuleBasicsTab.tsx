"use client";

/**
 * Zakładka „Podstawy": nazwa pliku, język, obie wersje, zrzut zgody RODO,
 * notatka Delivery Leada. To warstwa z 0255 — jedyne, co reguła umiała
 * do 09.2026. Notatka od 02.09 trafia też do modelu (osobny blok
 * `<client_notes>` pod tą samą granicą co instrukcje), więc opis pola mówi
 * o tym wprost — DL ma wiedzieć, że pisze do dwóch odbiorców.
 */

import type { CvRuleForm } from "@/lib/cv-rules";
import { GENERATOR_INSTRUCTIONS_MAX_LENGTH } from "@/lib/cv-rules";

const TOKENS = ["{STANOWISKO}", "{IMIE_NAZWISKO}", "{PROJEKT}", "{DATA}"];

export interface CvRuleTabProps {
  form: CvRuleForm;
  set: <K extends keyof CvRuleForm>(key: K, value: CvRuleForm[K]) => void;
  filenamePreview?: string | null;
}

export function CvRuleBasicsTab({ form, set, filenamePreview }: CvRuleTabProps) {
  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-xs font-medium" htmlFor="cvrule-pattern">
          Wzór nazwy pliku CV
        </label>
        <input
          id="cvrule-pattern"
          value={form.filename_pattern}
          onChange={(e) => set("filename_pattern", e.target.value)}
          placeholder="B2B_{STANOWISKO}_{IMIE_NAZWISKO}"
          maxLength={300}
          className="w-full rounded-md border px-3 py-2 font-mono text-sm"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Dostępne pola: {TOKENS.join(", ")}. Puste = nazwa ogólna.
        </p>
        {filenamePreview ? (
          <p className="mt-1 text-xs text-muted-foreground">
            Przykład: <span className="font-mono">{filenamePreview}</span>
          </p>
        ) : null}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.spaces_to_underscores}
          onChange={(e) => set("spaces_to_underscores", e.target.checked)}
        />
        Spacje w nazwie zamień na podkreślenia
      </label>

      <div>
        <label className="mb-1 block text-xs font-medium" htmlFor="cvrule-lang">
          Wymagany język CV
        </label>
        <select
          id="cvrule-lang"
          value={form.cv_language}
          onChange={(e) =>
            set("cv_language", e.target.value as CvRuleForm["cv_language"])
          }
          className="rounded-md border px-3 py-2 text-sm"
        >
          <option value="">Bez wymogu</option>
          <option value="pl">Tylko polski</option>
          <option value="en">Tylko angielski</option>
        </select>
        <p className="mt-1 text-xs text-muted-foreground">
          Zostaw „bez wymogu", gdy klient oczekuje OBU wersji — wymuszenie
          jednego języka zablokowałoby wygenerowanie drugiej.
        </p>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.requires_en_copy}
          onChange={(e) => set("requires_en_copy", e.target.checked)}
        />
        Klient oczekuje CV po polsku ORAZ po angielsku
      </label>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.requires_rodo_consent_block}
          onChange={(e) => set("requires_rodo_consent_block", e.target.checked)}
        />
        Wymagany zrzut zgody kandydata na dole CV
      </label>

      <div>
        <label className="mb-1 block text-xs font-medium" htmlFor="cvrule-notes">
          Notatka Delivery Leada o standardach klienta
        </label>
        <textarea
          id="cvrule-notes"
          value={form.notes}
          onChange={(e) => set("notes", e.target.value)}
          rows={4}
          maxLength={GENERATOR_INSTRUCTIONS_MAX_LENGTH}
          className="w-full rounded-md border px-3 py-2 text-sm"
          placeholder="Np. klient ceni doświadczenie w bankowości; nie lubi długich opisów; maks. 3 rekomendacje na stanowisko…"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Widzi ją rekruter w generatorze po wybraniu klienta ORAZ dostaje ją
          model jako kontekst do doboru akcentów. Model może na jej podstawie
          wyeksponować lub przesunąć fakty, które kandydat ma w CV — nigdy
          dopisać nowych. Reguły szukania kandydatów („bierzemy tylko z
          bankowości”) zostaw w notatce, nie w instrukcjach.{" "}
          {form.notes.length}/{GENERATOR_INSTRUCTIONS_MAX_LENGTH}
        </p>
      </div>
    </div>
  );
}
