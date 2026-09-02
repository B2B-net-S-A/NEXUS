"use client";

/**
 * Zakładka „Treść i AI": klocki egzekwowane w kodzie + słownik + instrukcje
 * wolnym tekstem (PL / EN) z lintem przy zapisie.
 *
 * Klocki są PRZED instrukcjami celowo: to, co da się wyrazić przełącznikiem,
 * renderer domyka deterministycznie, a wolny tekst zostaje na resztę. Lint
 * jest opinią taniego modelu, nie bramką — pokazuje, która linia każe
 * dopisać fakt i zostanie przez generator zignorowana.
 */

import { useState } from "react";
import { AlertTriangle, CheckCircle2, HelpCircle, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  CV_RULE_DATE_FORMATS,
  CV_RULE_SECTIONS,
  GENERATOR_INSTRUCTIONS_MAX_LENGTH,
  cvRulesApi,
  type CvRuleForm,
  type CvRuleSectionKey,
  type LintFinding,
  type LintResponse,
} from "@/lib/cv-rules";
import { extractErrorMsg } from "@/lib/api";

import type { CvRuleTabProps } from "./CvRuleBasicsTab";

interface Props extends CvRuleTabProps {
  clientId: number;
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

export function CvRuleContentTab({ form, set, clientId }: Props) {
  const [lint, setLint] = useState<LintResponse | null>(null);
  const [lintBusy, setLintBusy] = useState(false);
  const [lintError, setLintError] = useState("");

  const toggleSection = (key: CvRuleSectionKey, on: boolean) => {
    const next = form.omit_sections.filter((k) => k !== key);
    set("omit_sections", on ? [...next, key] : next);
  };

  const updateGlossary = (index: number, field: "from" | "to", value: string) => {
    set(
      "glossary",
      form.glossary.map((g, i) => (i === index ? { ...g, [field]: value } : g)),
    );
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
    <div className="space-y-6">
      <fieldset className="space-y-2">
        <legend className="text-xs font-medium">Sekcje do pominięcia</legend>
        <div className="flex flex-wrap gap-3">
          {CV_RULE_SECTIONS.map((section) => (
            <label key={section.value} className="flex items-center gap-2 text-sm">
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
          Renderer usuwa te sekcje zawsze, niezależnie od tego, co napisze model.
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
        <label className="mb-1 block text-xs font-medium" htmlFor="cvrule-date-format">
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

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium">Słownik klienta</legend>
        <p className="text-xs text-muted-foreground">
          Nazewnictwo ról i technologii, jakiego używa klient. Zamiana całych
          słów w opisach, bez zmiany faktów.
        </p>
        <ul className="space-y-2">
          {form.glossary.map((entry, index) => (
            <li key={index} className="flex flex-wrap items-center gap-2">
              <input
                aria-label={`Słownik ${index + 1}: z`}
                value={entry.from}
                onChange={(e) => updateGlossary(index, "from", e.target.value)}
                placeholder="w źródle, np. Business Analyst"
                maxLength={80}
                className="w-56 rounded-md border px-2 py-1 text-sm"
              />
              <span className="text-muted-foreground">→</span>
              <input
                aria-label={`Słownik ${index + 1}: na`}
                value={entry.to}
                onChange={(e) => updateGlossary(index, "to", e.target.value)}
                placeholder="u klienta, np. Analityk Biznesowy"
                maxLength={80}
                className="w-56 rounded-md border px-2 py-1 text-sm"
              />
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
          disabled={form.glossary.length >= 50}
          onClick={() => set("glossary", [...form.glossary, { from: "", to: "" }])}
        >
          Dodaj parę
        </Button>
      </fieldset>

      <div>
        <label className="mb-1 block text-xs font-medium" htmlFor="cvrule-instructions">
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
        {lintError ? <p className="text-xs text-destructive">{lintError}</p> : null}
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
    </div>
  );
}
