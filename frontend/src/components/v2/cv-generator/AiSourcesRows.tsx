"use client";

import { useId } from "react";
import { Loader2 } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import {
  aiSourceRows,
  type CvAiSourceKey,
  type CvAiSourceRow,
  type CvAiSourceToggles,
  type CvAiSources,
} from "@/lib/cv-ai-sources";
import { cn } from "@/lib/utils";

import { StatusChip } from "./GeneratorParts";

export interface AiSourcesRowsProps {
  title: string;
  data: CvAiSources | undefined;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
  /** Bieżące przełączniki; `null`, dopóki źródła się nie wczytały. */
  value: CvAiSourceToggles | null;
  onChange: (key: CvAiSourceKey, on: boolean) => void;
  disabled?: boolean;
  /**
   * Okno generatora pokazuje plik CV i Championa wyżej, w źródłach procesu —
   * tu tylko przełączniki i notatki ze stawką.
   */
  togglesOnly?: boolean;
  className?: string;
}

const TOGGLE_KEYS: ReadonlySet<string> = new Set(["answers", "notes", "transcripts", "prep"]);

function isToggle(row: CvAiSourceRow): row is CvAiSourceRow & { id: CvAiSourceKey } {
  return row.mode === "toggle" && TOGGLE_KEYS.has(row.id);
}

/**
 * „Z czego powstało” (D4, 13.10.2026): co model przeczyta przy generacji.
 * Oryginalne CV i Champion wchodzą zawsze, odpowiedzi, notatki, transkrypty
 * i prep rekruter włącza sam, notatki ze stawką są zawsze wycinane.
 */
export function AiSourcesRows({
  title,
  data,
  loading,
  error,
  onRetry,
  value,
  onChange,
  disabled = false,
  togglesOnly = false,
  className,
}: AiSourcesRowsProps) {
  const headingId = useId();
  const rows = data ? aiSourceRows(data).filter((row) => !togglesOnly || row.mode === "toggle" || row.mode === "never") : [];
  return (
    <section aria-labelledby={headingId} className={cn("space-y-1.5", className)}>
      <h4 id={headingId} className="text-xs font-semibold text-foreground">
        {title}
      </h4>
      {loading && !data ? (
        <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden /> Wczytuję źródła…
        </p>
      ) : null}
      {error && !data ? (
        // Awaria odczytu nie może wyglądać jak „brak materiału”.
        <p role="alert" className="text-xs text-destructive-muted-foreground">
          Nie udało się wczytać źródeł. CV powstanie z ustawień domyślnych: odpowiedzi i notatki tak,
          transkrypty i prep nie.{" "}
          <button type="button" className="font-medium underline underline-offset-2" onClick={onRetry}>
            Ponów
          </button>
        </p>
      ) : null}
      {rows.length > 0 ? (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {rows.map((row) => {
            const toggle = isToggle(row);
            const checked = toggle ? (value?.[row.id] ?? false) : false;
            return (
              <li key={row.id} className="flex items-start gap-3 px-2.5 py-2" data-testid={`ai-source-${row.id}`}>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-foreground">{row.label}</p>
                  <p className="text-[11px] leading-snug text-muted-foreground [overflow-wrap:anywhere]">{row.detail}</p>
                </div>
                {toggle ? (
                  <Switch
                    aria-label={row.label}
                    checked={checked}
                    disabled={disabled || value == null || row.empty === true}
                    onCheckedChange={(on) => onChange(row.id, on)}
                    className="mt-0.5"
                  />
                ) : row.mode === "always" ? (
                  <StatusChip tone="ok">zawsze</StatusChip>
                ) : row.mode === "never" ? (
                  <Switch aria-label={`${row.label} — zawsze wycinane`} checked={false} disabled className="mt-0.5" />
                ) : (
                  <StatusChip tone="warn">brak</StatusChip>
                )}
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
