"use client";

/**
 * Zakładka „Ustawienia" edytora reguł CV — jedna zakładka ułożona pod zadanie
 * Delivery Leada, zamiast trzech równorzędnych („Podstawy" + „Generator" +
 * „Treść i AI"), w których 25 pól różnej wagi leżało na jednym poziomie.
 *
 * Dwie grupy są ZAWSZE widoczne, bo to 90% pracy DL:
 *  1. „Plik i język" — nazwa pliku (z podglądem na żywo), język, obie wersje,
 *     zrzut zgody RODO;
 *  2. „Wskazówki dla generatora" — notatka (rekruter + model) i instrukcje AI
 *     z lintem.
 *
 * Reszta — blokady trybu, wymagane wejścia, polityka prezentacji egzekwowana
 * w kodzie, słownik — siedzi pod ZWINIĘTĄ sekcją „Zaawansowane" z licznikiem
 * „ile z nich jest aktywne", żeby ukryte ustawienia nie znikały z pola widzenia.
 * Wszystkie pola, ich klucze w `CvRuleForm` i teksty etykiet są 1:1 ze starymi
 * zakładkami — zmienia się układ, nie kontrakt zapisu (`formToPayload` nadal
 * wysyła KOMPLET pól).
 */

import { useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  FileText,
  HelpCircle,
  SlidersHorizontal,
  Sparkles,
  Wand2,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { extractErrorMsg } from "@/lib/api";
import { CV_CONTENT_MODES } from "@/lib/cv-generator";
import type { CvContentMode } from "@/lib/cv-generator";
import {
  CV_RULE_DATE_FORMATS,
  CV_RULE_SECTIONS,
  GENERATOR_INSTRUCTIONS_MAX_LENGTH,
  countActiveAdvanced,
  cvRulesApi,
  type CvRuleForm,
  type GlossaryEntry,
  type CvRuleSectionKey,
  type LintFinding,
  type LintResponse,
} from "@/lib/cv-rules";
import { Button } from "@/components/ui/button";

const TOKENS = ["{STANOWISKO}", "{IMIE_NAZWISKO}", "{PROJEKT}", "{DATA}"];

const MODE_LABEL: Record<CvContentMode, string> = Object.fromEntries(
  CV_CONTENT_MODES.map((m) => [m.value, m.label]),
) as Record<CvContentMode, string>;

export interface CvRuleSettingsTabProps {
  form: CvRuleForm;
  set: <K extends keyof CvRuleForm>(key: K, value: CvRuleForm[K]) => void;
  clientId: number;
  filenamePreview?: string | null;
  glossaryOptions?: GlossaryEntry[];
}

function Group({
  icon: Icon,
  title,
  subtitle,
  always,
  children,
}: {
  icon: LucideIcon;
  title: string;
  subtitle: string;
  always?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border">
      <header className="flex items-center gap-3 border-b bg-muted/40 px-4 py-3">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold">{title}</p>
          <p className="text-xs text-muted-foreground">{subtitle}</p>
        </div>
        {always ? (
          <span className="ml-auto rounded-md bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
            zawsze widoczne
          </span>
        ) : null}
      </header>
      <div className="flex flex-col gap-4 p-4">{children}</div>
    </section>
  );
}

function NumberField({
  id,
  label,
  value,
  onChange,
  min,
  max,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  min: number;
  max: number;
  hint?: string;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="bez limitu"
        className="w-32 rounded-md border px-2 py-1 text-sm"
      />
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

const VERDICT_LABEL: Record<LintFinding["verdict"], string> = {
  ok: "prezentacja",
  adds_facts: "dopisuje fakty — zostanie zignorowana",
  unclear: "niejednoznaczna",
};

function LintFindingRow({ finding }: { finding: LintFinding }) {
  const Icon =
    finding.verdict === "ok"
      ? CheckCircle2
      : finding.verdict === "adds_facts"
        ? AlertTriangle
        : HelpCircle;
  const tone =
    finding.verdict === "ok"
      ? "text-emerald-700 dark:text-emerald-400"
      : finding.verdict === "adds_facts"
        ? "text-destructive"
        : "text-amber-700 dark:text-amber-400";
  return (
    <li className="rounded-md border p-2 text-xs">
      <div className={`flex items-start gap-2 ${tone}`}>
        <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          <span className="font-medium">„{finding.line}”</span> —{" "}
          {VERDICT_LABEL[finding.verdict]}
        </span>
      </div>
      {finding.reason ? (
        <p className="mt-1 text-muted-foreground">{finding.reason}</p>
      ) : null}
      {finding.suggestion ? (
        <p className="mt-1">
          Propozycja: <span className="italic">{finding.suggestion}</span>
        </p>
      ) : null}
    </li>
  );
}

export function CvRuleSettingsTab({
  form,
  set,
  clientId,
  filenamePreview,
  glossaryOptions = [],
}: CvRuleSettingsTabProps) {
  // Otwarte od startu, gdy jakieś zaawansowane ustawienie już działa — ukryta
  // aktywna konfiguracja jest gorsza niż zwinięta pusta sekcja.
  const [advOpen, setAdvOpen] = useState(() => countActiveAdvanced(form) > 0);
  const [lint, setLint] = useState<LintResponse | null>(null);
  const [lintBusy, setLintBusy] = useState(false);
  const [lintError, setLintError] = useState("");

  const advCount = countActiveAdvanced(form);

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

  const toggleSection = (key: CvRuleSectionKey, on: boolean) => {
    const next = form.omit_sections.filter((k) => k !== key);
    set("omit_sections", on ? [...next, key] : next);
  };

  const runLint = async () => {
    setLintBusy(true);
    setLintError("");
    try {
      const res = await cvRulesApi.lint(clientId, {
        generator_instructions: form.generator_instructions.trim() || null,
        generator_instructions_en: form.generator_instructions_en.trim() || null,
        notes: form.notes.trim() || null,
      });
      setLint(res);
    } catch (err) {
      setLintError(extractErrorMsg(err) || "Nie udało się ocenić instrukcji.");
    } finally {
      setLintBusy(false);
    }
  };

  const hasText =
    !!form.generator_instructions.trim() ||
    !!form.generator_instructions_en.trim() ||
    !!form.notes.trim();

  return (
    <div className="space-y-4">
      {/* ── GRUPA 1: Plik i język (zawsze widoczne) ── */}
      <Group
        icon={FileText}
        title="Plik i język"
        subtitle="Jak klient chce dostać dokument. To ustawia się najczęściej."
        always
      >
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

        <div className="grid gap-4 sm:grid-cols-2">
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
              className="w-full rounded-md border px-3 py-2 text-sm"
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
          <div className="flex flex-col justify-center gap-3">
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
                onChange={(e) =>
                  set("requires_rodo_consent_block", e.target.checked)
                }
              />
              Wymagany zrzut zgody kandydata na dole CV
            </label>
          </div>
        </div>
      </Group>

      <Group icon={Wand2} title="Pogrubienia w CV" subtitle="Ta sama reguła w DOCX, HTML i publicznym CV; niezależnie od trybu redakcji." always>
        <label className="block text-xs font-medium" htmlFor="cvrule-highlights">Co pogrubiać</label>
        <select id="cvrule-highlights" value={form.highlight_policy}
          onChange={(event) => set("highlight_policy", event.target.value as CvRuleForm["highlight_policy"])}
          className="w-full rounded-md border px-3 py-2 text-sm">
          <option value="technologies">Technologie występujące w CV i źródłach</option>
          <option value="must">Technologie MUST z profilu Championa</option>
          <option value="must_nice">Technologie MUST i NICE z profilu Championa</option>
          <option value="explicit">Wskazana lista technologii</option>
          <option value="none">Bez wyróżnień technologii</option>
        </select>
        {form.highlight_policy === "explicit" ? <div>
          <label className="block text-xs font-medium" htmlFor="cvrule-highlight-terms">Wyróżniane technologie — po jednej w wierszu</label>
          <textarea id="cvrule-highlight-terms" value={form.highlight_terms}
            onChange={(event) => set("highlight_terms", event.target.value)} rows={4}
            className="w-full rounded-md border px-3 py-2 text-sm" placeholder={"Python\nPostgreSQL"} />
        </div> : null}
        <p className="text-xs text-muted-foreground">Wyróżnienie nie dopisuje umiejętności. Pozycje bez pokrycia w źródłach są pomijane; podgląd pokaże ostrzeżenie. Nagłówki sekcji zachowują swój styl.</p>
      </Group>

      {/* ── GRUPA 2: Wskazówki dla generatora ── */}
      <Group
        icon={Wand2}
        title="Wskazówki dla generatora"
        subtitle="Notatka dla rekrutera i dobór akcentów dla modelu AI."
      >
        <div>
          <label className="mb-1 block text-xs font-medium" htmlFor="cvrule-notes">
            Notatka Delivery Leada o standardach klienta{" "}
            <span className="ml-1 inline-flex items-center rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
              widzi rekruter + model AI
            </span>
          </label>
          <textarea
            id="cvrule-notes"
            value={form.notes}
            onChange={(e) => set("notes", e.target.value)}
            rows={3}
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

        <div>
          <label
            className="mb-1 block text-xs font-medium"
            htmlFor="cvrule-instructions"
          >
            Instrukcje dla generatora AI
          </label>
          <textarea
            id="cvrule-instructions"
            value={form.generator_instructions}
            onChange={(e) => set("generator_instructions", e.target.value)}
            rows={4}
            maxLength={GENERATOR_INSTRUCTIONS_MAX_LENGTH}
            className="w-full rounded-md border px-3 py-2 text-sm"
            placeholder={
              "Np. opisy obowiązków w formie rzeczownikowej; najpierw projekty " +
              "bankowe, jeśli są; bez skrótów wewnętrznych"
            }
          />
          <p className="mt-1 text-xs text-muted-foreground">
            Wyłącznie dobór i forma faktów, które kandydat ma w CV lub notatkach.
            Polecenie dopisania technologii, obowiązku czy lat model ignoruje i
            zgłasza w ostrzeżeniach. Układ dokumentu (szablon DOCX) się nie
            zmienia. {form.generator_instructions.length}/
            {GENERATOR_INSTRUCTIONS_MAX_LENGTH}
          </p>
        </div>

        <div>
          <label
            className="mb-1 block text-xs font-medium"
            htmlFor="cvrule-instructions-en"
          >
            Instrukcje dla CV angielskiego (opcjonalnie)
          </label>
          <textarea
            id="cvrule-instructions-en"
            value={form.generator_instructions_en}
            onChange={(e) => set("generator_instructions_en", e.target.value)}
            rows={3}
            maxLength={GENERATOR_INSTRUCTIONS_MAX_LENGTH}
            className="w-full rounded-md border px-3 py-2 text-sm"
            placeholder="Puste = dla CV po angielsku idą instrukcje powyżej."
          />
        </div>

        <div className="space-y-2 rounded-md border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-medium">
              Lint instrukcji — która linia zostanie zignorowana?
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              loading={lintBusy}
              disabled={!hasText || lintBusy}
              onClick={runLint}
            >
              <Sparkles className="h-3.5 w-3.5" />
              Sprawdź instrukcje
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Tani model ocenia każdą linię: prezentacja, dopisywanie faktów albo
            niejednoznaczna — z propozycją przepisania. Nie blokuje zapisu.
          </p>
          {lintError ? (
            <p className="text-xs text-destructive">{lintError}</p>
          ) : null}
          {lint ? (
            lint.findings.length === 0 ? (
              <p className="text-xs text-muted-foreground">Brak linii do oceny.</p>
            ) : (
              <>
                <p className="text-xs">
                  {lint.ok_count} OK · {lint.adds_facts_count} do przepisania ·{" "}
                  {lint.unclear_count} niejednoznacznych
                </p>
                <ul className="space-y-1">
                  {lint.findings.map((f) => (
                    <LintFindingRow key={`${f.field}-${f.index}`} finding={f} />
                  ))}
                </ul>
              </>
            )
          ) : null}
        </div>
      </Group>

      {/* ── ZAAWANSOWANE (zwinięte, z licznikiem) ── */}
      <section className="rounded-lg border">
        <button
          type="button"
          aria-expanded={advOpen}
          onClick={() => setAdvOpen((v) => !v)}
          className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/50"
        >
          <ChevronRight
            className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${advOpen ? "rotate-90" : ""}`}
          />
          <SlidersHorizontal className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0">
            <span className="text-sm font-semibold">Zaawansowane</span>
            <span className="text-xs text-muted-foreground">
              {" "}
              — blokady, polityka prezentacji, słownik. Rzadko ruszane.
            </span>
          </span>
          {advCount > 0 ? (
            <span className="ml-auto shrink-0 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-semibold text-primary">
              {advCount} aktywne
            </span>
          ) : (
            <span className="ml-auto shrink-0 text-xs text-muted-foreground">
              wszystko domyślne
            </span>
          )}
        </button>

        {advOpen ? (
          <div className="space-y-6 border-t px-4 pb-5 pt-4">
            {/* Tryb obróbki treści + sufit */}
            <fieldset className="space-y-2">
              <legend className="text-xs font-medium">Tryb obróbki treści</legend>
              <div
                className="flex flex-wrap gap-2"
                role="radiogroup"
                aria-label="Polityka trybu"
              >
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
                <label
                  className="mb-1 block text-xs font-medium"
                  htmlFor="cvrule-cap"
                >
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

            {/* Wymagane wejścia */}
            <fieldset className="space-y-2">
              <legend className="text-xs font-medium">
                Wymagane wejścia — bez nich generacja nie ruszy
              </legend>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <label htmlFor="cvrule-notes-min">
                  Notatki ze screeningu: co najmniej
                </label>
                <input
                  id="cvrule-notes-min"
                  type="number"
                  min={0}
                  max={20000}
                  step={50}
                  value={form.require_screening_notes_min_chars}
                  onChange={(e) =>
                    set("require_screening_notes_min_chars", e.target.value)
                  }
                  placeholder="0"
                  className="w-24 rounded-md border px-2 py-1 text-sm"
                />
                <span className="text-muted-foreground">
                  znaków (puste = bez wymogu)
                </span>
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
                  języka. To drugie wywołanie najdroższego modelu w produkcie —
                  osobny wiersz na liście, osobna kwota.
                </span>
              </span>
            </label>

            {/* Polityka prezentacji */}
            <fieldset className="space-y-2">
              <legend className="text-xs font-medium">Sekcje do pominięcia</legend>
              <div className="flex flex-wrap gap-3">
                {CV_RULE_SECTIONS.map((section) => (
                  <label
                    key={section.value}
                    className="flex items-center gap-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={form.omit_sections.includes(section.value)}
                      onChange={(e) => toggleSection(section.value, e.target.checked)}
                    />
                    {section.label}
                  </label>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                Renderer usuwa te sekcje zawsze, niezależnie od tego, co napisze
                model.
              </p>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-2">
              <NumberField
                id="cvrule-max-roles"
                label="Maks. liczba stanowisk"
                value={form.max_roles}
                onChange={(v) => set("max_roles", v)}
                min={1}
                max={30}
                hint="Najnowsze zostają."
              />
              <NumberField
                id="cvrule-max-bullets"
                label="Maks. punktów obowiązków na stanowisko"
                value={form.max_bullets_per_role}
                onChange={(v) => set("max_bullets_per_role", v)}
                min={1}
                max={20}
              />
              <NumberField
                id="cvrule-max-chars"
                label="Maks. znaków w punkcie"
                value={form.max_bullet_chars}
                onChange={(v) => set("max_bullet_chars", v)}
                min={40}
                max={600}
                hint="Dłuższy punkt jest skracany na granicy słowa."
              />
              <NumberField
                id="cvrule-why-max"
                label="Maks. punktów „dlaczego ten kandydat”"
                value={form.why_points_max}
                onChange={(v) => set("why_points_max", v)}
                min={1}
                max={12}
              />
            </div>

            <div>
              <label
                className="mb-1 block text-xs font-medium"
                htmlFor="cvrule-date-format"
              >
                Format dat
              </label>
              <select
                id="cvrule-date-format"
                value={form.date_format}
                onChange={(e) =>
                  set("date_format", e.target.value as CvRuleForm["date_format"])
                }
                className="rounded-md border px-3 py-2 text-sm"
              >
                <option value="">Jak w źródle</option>
                {CV_RULE_DATE_FORMATS.map((f) => (
                  <option key={f.value} value={f.value}>
                    {f.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Słownik */}
            <fieldset className="space-y-2">
              <legend className="text-xs font-medium">Słownik klienta</legend>
              <p className="text-xs text-muted-foreground">
                Wybierz sprawdzony odpowiednik językowy pełnej nazwy stanowiska.
                Zamiana działa tylko dla języka docelowego CV; nie zmienia
                umiejętności, certyfikatów, seniority ani opisów doświadczenia.
              </p>
              <ul className="space-y-2">
                {form.glossary.map((entry, index) => (
                  <li key={index} className="flex flex-wrap items-center gap-2">
                    <select
                      aria-label={`Tłumaczenie stanowiska ${index + 1}`}
                      value={glossaryOptions.findIndex((g) =>
                        g.from.toLocaleLowerCase() === entry.from.toLocaleLowerCase() &&
                        g.to.toLocaleLowerCase() === entry.to.toLocaleLowerCase())}
                      onChange={(e) => {
                        const selected = glossaryOptions[Number(e.target.value)];
                        if (selected) set("glossary", form.glossary.map((g, i) =>
                          i === index ? { from: selected.from, to: selected.to } : g));
                      }}
                      className="max-w-full rounded-md border px-2 py-1 text-sm"
                    >
                      <option value={-1} disabled>
                        {entry.from || entry.to
                          ? `Niedozwolony wpis: ${entry.from} → ${entry.to}`
                          : "Wybierz tłumaczenie stanowiska"}
                      </option>
                      {glossaryOptions.map((g, optionIndex) => (
                        <option key={optionIndex} value={optionIndex}>{g.from} → {g.to}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="text-xs text-destructive hover:underline"
                      onClick={() =>
                        set(
                          "glossary",
                          form.glossary.filter((_, i) => i !== index),
                        )
                      }
                    >
                      usuń
                    </button>
                  </li>
                ))}
              </ul>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={form.glossary.length >= 50 || glossaryOptions.length === 0}
                onClick={() =>
                  set("glossary", [...form.glossary, { from: "", to: "" }])
                }
              >
                Dodaj parę
              </Button>
            </fieldset>
          </div>
        ) : null}
      </section>
    </div>
  );
}
