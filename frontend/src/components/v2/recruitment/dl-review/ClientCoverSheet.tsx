"use client";

/**
 * „Karta przed CV” w przeglądzie Delivery Leada (Credit Agricole, 29.10.2026).
 *
 * Klient z wgranym wzorem karty (edytor reguły CV) dostaje z każdym CV osobny
 * plik Word: imię, rola, poziom, staż, profil kompetencji, dostępność,
 * lokalizacja i wynagrodzenie za MD. Karta ma stawkę do klienta, więc stoi
 * tylko tutaj — rekruter jej nie widzi.
 *
 * Kartka wygląda jak strona Worda; przy każdym polu źródło wartości. Poziom
 * jest zawsze „do sprawdzenia” (żółty), bo progi stażu (<3 Junior, 3–7
 * Specjalista, 8+ Expert) to podpowiedź, nie ocena. Wynagrodzenie liczy się
 * na żywo ze „Stawki do klienta” wpisywanej w panelu decyzji (godzinowa × 8).
 * Poprawki DL-a zapisują się po wyjściu z pola (`PUT …/cover-sheet`).
 */

import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Download, FileText, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  coverSheetKey,
  downloadCoverSheet,
  formatMdAmount,
  mdRateFromInput,
  saveCoverSheet,
  type CoverSheetEnabled,
  type CoverSheetField,
  type CoverSheetFieldId,
} from "@/lib/api/coverSheet";
import type { ClientRateUnit } from "@/lib/person-facts";
import { cn } from "@/lib/utils";

export interface CoverSheetRate {
  raw: string;
  unit: ClientRateUnit;
  currency: string;
}

/** Wynagrodzenie karty: stawka z przeglądu, a bez niej — zapisana stawka pary. */
export function coverSheetWage(
  sheet: CoverSheetEnabled,
  rate: CoverSheetRate,
): { label: string | null; source: string; live: boolean } {
  if (rate.raw.trim()) {
    if ((rate.currency || "PLN").toUpperCase() !== "PLN") {
      return { label: null, source: "karta jest w PLN", live: true };
    }
    const md = mdRateFromInput(rate.raw, rate.unit);
    if (md != null) {
      return {
        label: formatMdAmount(md),
        source: rate.unit === "hourly" ? "Twoja stawka × 8 h" : "Twoja stawka",
        live: true,
      };
    }
    return {
      label: null,
      source: rate.unit === "monthly" ? "wpisz stawkę godzinową albo dzienną" : "tylko DL",
      live: true,
    };
  }
  if (sheet.md_rate_label) {
    const field = sheet.fields.find((item) => item.id === "rate");
    return { label: sheet.md_rate_label, source: field?.source_label ?? "zapisana stawka", live: false };
  }
  return { label: null, source: "tylko DL", live: false };
}

function SourceChip({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "warn" | "info" }) {
  return (
    <span
      className={cn(
        "ml-2 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium",
        tone === "muted" && "bg-muted text-muted-foreground",
        tone === "warn" && "bg-warning-muted text-warning-muted-foreground",
        tone === "info" && "bg-info-muted text-info-muted-foreground",
      )}
    >
      {children}
    </span>
  );
}

function FieldRow({
  label,
  children,
  source,
  tone,
}: {
  label: string;
  children: ReactNode;
  source: string | null;
  tone?: "muted" | "warn" | "info";
}) {
  return (
    <div className="flex items-start justify-between gap-2 rounded px-1 py-[3px] hover:bg-muted/40">
      <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-1 text-[13px] leading-snug">
        {label ? <b className="shrink-0">{label}</b> : null}
        {children}
      </div>
      {source ? <SourceChip tone={tone}>{source}</SourceChip> : null}
    </div>
  );
}

/** Pole tekstowe karty: zapis po wyjściu z pola, pusta wartość = wartość NEXUSA. */
function EditableText({
  field,
  multiline,
  narrow,
  disabled,
  onSave,
}: {
  field: CoverSheetField;
  multiline?: boolean;
  narrow?: boolean;
  disabled: boolean;
  onSave: (value: string) => void;
}) {
  const [draft, setDraft] = useState(field.value ?? "");
  useEffect(() => setDraft(field.value ?? ""), [field.value]);
  const commit = () => {
    if (draft.trim() !== (field.value ?? "")) onSave(draft.trim());
  };
  const common = {
    "aria-label": field.label.replace(/:$/, "") || "Imię i nazwisko",
    value: draft,
    disabled,
    placeholder: "do uzupełnienia",
    onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft(event.target.value),
    onBlur: commit,
    className: cn(
      "rounded border border-transparent bg-transparent px-1 text-[13px] hover:border-border focus:border-ring focus:outline-none",
      narrow ? "w-16" : "w-full",
      !field.value && "bg-warning-muted/60",
    ),
  };
  return multiline ? <textarea rows={2} {...common} /> : <input type="text" {...common} />;
}

export interface ClientCoverSheetProps {
  candidateId: number;
  jobId: number;
  sheet: CoverSheetEnabled;
  rate: CoverSheetRate;
  /** Zapis poprawek: uprawnienie do stawki do klienta (DL, admin). */
  canEdit: boolean;
}

export function ClientCoverSheet({ candidateId, jobId, sheet, rate, canEdit }: ClientCoverSheetProps) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const [saving, setSaving] = useState<CoverSheetFieldId | null>(null);
  const [downloading, setDownloading] = useState(false);
  const wage = coverSheetWage(sheet, rate);
  const fields = new Map(sheet.fields.map((field) => [field.id, field]));

  // Zapisy po kolei: wyjście z pola i od razu wybór poziomu to dwa PUT-y —
  // równolegle odpowiedź starszego mogłaby cofnąć ekran. Pobranie czeka na
  // ostatni zapis, żeby plik miał poprawkę, którą DL właśnie wpisał.
  const queue = useRef<Promise<void>>(Promise.resolve());

  const save = (id: CoverSheetFieldId, value: string): Promise<void> => {
    const run = queue.current.then(async () => {
      setSaving(id);
      try {
        const next = await saveCoverSheet(candidateId, jobId, { [id]: value });
        queryClient.setQueryData(coverSheetKey(candidateId, jobId), next);
      } catch (error) {
        showError(apiErrorMessage(error, "Nie udało się zapisać karty."));
      } finally {
        setSaving(null);
      }
    });
    queue.current = run;
    return run;
  };

  const download = async () => {
    setDownloading(true);
    try {
      await queue.current;
      await downloadCoverSheet(
        candidateId,
        jobId,
        wage.live ? { raw: rate.raw, unit: rate.unit, currency: rate.currency } : null,
      );
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać karty."));
    } finally {
      setDownloading(false);
    }
  };

  const renderField = (field: CoverSheetField) => {
    const disabled = !canEdit || saving === field.id;
    if (field.id === "rate") {
      return (
        <FieldRow key={field.id} label={field.label} source={wage.source} tone={wage.label ? "info" : "warn"}>
          {wage.label ? (
            <span data-testid="cover-sheet-wage">
              {wage.label}
              {field.suffix.replace(/^,00/, "")}
            </span>
          ) : (
            <span className="rounded bg-destructive/10 px-1 text-destructive" data-testid="cover-sheet-wage">
              wpisz „Stawkę do klienta” w decyzji
            </span>
          )}
        </FieldRow>
      );
    }
    if (field.id === "level") {
      return (
        <FieldRow key={field.id} label={field.label} source={field.source_label} tone="warn">
          <select
            aria-label="Poziom doświadczenia"
            value={field.value ?? ""}
            disabled={disabled}
            onChange={(event) => void save("level", event.target.value)}
            className="rounded border border-border bg-warning-muted/60 px-1 py-0.5 text-[13px]"
          >
            <option value="">— wybierz —</option>
            {(field.options ?? []).map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </FieldRow>
      );
    }
    if (field.editable && canEdit) {
      return (
        <FieldRow key={field.id} label={field.label} source={field.source_label}>
          <span className="flex min-w-0 flex-1 items-baseline gap-1">
            <EditableText
              field={field}
              multiline={field.id === "profile"}
              narrow={field.id === "experience"}
              disabled={disabled}
              onSave={(value) => void save(field.id, value)}
            />
            {field.suffix.trim() ? <span className="shrink-0">{field.suffix.trim()}</span> : null}
          </span>
        </FieldRow>
      );
    }
    return (
      <FieldRow key={field.id} label={field.label} source={field.source_label}>
        {field.value ? (
          <span className={field.id === "name" ? "font-bold" : undefined}>
            {field.value}
            {field.suffix}
          </span>
        ) : (
          <span className="rounded bg-warning-muted/60 px-1">do uzupełnienia</span>
        )}
      </FieldRow>
    );
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto" data-testid="cover-sheet">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-info/30 bg-info-muted px-3 py-2 text-xs text-info-muted-foreground">
        <FileText className="size-4 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1">
          Ten klient chce karty z każdym CV — osobny plik Word. NEXUS wypełnił ją z profilu, rekrutacji i CV
          firmowego; sprawdź poziom i profil. Wynagrodzenie bierze się z Twojej „Stawki do klienta”; rekruter
          tej karty nie widzi.
        </span>
        <Button
          size="sm"
          variant="outline"
          className="h-7"
          disabled={!wage.label || downloading}
          title={wage.label ? undefined : "Najpierw wpisz stawkę do klienta"}
          onClick={() => void download()}
        >
          {downloading ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <Download className="size-3.5" aria-hidden />
          )}
          Word
        </Button>
      </div>
      <div className="mx-auto w-full max-w-[640px] rounded-sm border border-border bg-card px-10 py-8 text-card-foreground shadow-md">
        {sheet.layout.map((item, index) => {
          if (item.kind === "text") {
            return index === 0 ? (
              <p key={index} className="mb-4 border-b-2 border-primary pb-1 text-2xl font-semibold text-primary">
                {item.text}
              </p>
            ) : (
              <p key={index} className={cn("px-1 text-[13px] leading-snug", item.bold && "pt-1 font-bold")}>
                {item.text}
              </p>
            );
          }
          const field = fields.get(item.id);
          return field ? renderField(field) : null;
        })}
      </div>
    </div>
  );
}

/** Jedna linia nad przyciskami decyzji: czy karta jest gotowa. */
export function CoverSheetDecisionNote({ sheet, rate }: { sheet: CoverSheetEnabled; rate: CoverSheetRate }) {
  const wage = coverSheetWage(sheet, rate);
  return (
    <p
      role="note"
      data-testid="cover-sheet-note"
      className="flex items-start gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
    >
      <FileText className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="font-medium text-foreground">
          {wage.label ? "Karta przed CV gotowa" : "Karta przed CV czeka na stawkę"}
        </span>
        {wage.label ? ` · ${wage.label} zł/MD` : ""} · poziom do sprawdzenia. Plik Word pobierzesz z pigułki
        „Karta do klienta”.
      </span>
    </p>
  );
}
