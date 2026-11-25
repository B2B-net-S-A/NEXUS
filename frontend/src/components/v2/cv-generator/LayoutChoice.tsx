"use client";

import { Check, Lock } from "lucide-react";

import type { CvLayout } from "@/lib/api";
import { cvDownloadPlan, wordClassicWarning, type CvFileFormat } from "@/lib/cv-file-format";

import { cn } from "@/lib/utils";

import { Segmented } from "./GeneratorParts";

/** Etykiety układu CV wspólne dla generatora, karty i edytora (22.11.2026). */
export const CV_LAYOUT_LABEL: Record<CvLayout, string> = {
  new: "Nowe CV",
  classic: "Klasyczne (Word)",
};

/** Krótki opis układu do faktów karty: „Nowe CV · PDF”. */
export function cvLayoutFact(layout: CvLayout): string {
  return layout === "new" ? "Nowe CV · PDF" : "Klasyczne · Word";
}

const OPTIONS = [
  { value: "new" as const, label: CV_LAYOUT_LABEL.new },
  { value: "classic" as const, label: CV_LAYOUT_LABEL.classic },
];
// Wąska karta (ok. 250 px obok miniatury): krótsze etykiety, pełne w podpowiedzi.
const COMPACT_OPTIONS = [
  { value: "new" as const, label: "Nowe CV", title: "Nowe CV — PDF" },
  { value: "classic" as const, label: "Klasyczne", title: "Klasyczne — szablon Word" },
];

export interface LayoutChoiceProps {
  value: CvLayout;
  onChange: (value: CvLayout) => void;
  /** Gdzie stoi przełącznik: generator (przed „Generuj”) albo karta gotowego CV. */
  place: "generator" | "card";
  clientName?: string | null;
  /** Domyślny układ klienta — podpowiedź w generatorze. */
  clientDefault?: CvLayout;
  disabled?: boolean;
  /** CV jest już u klienta: przełącznik zablokowany (jak podmiana CV). */
  lockedAfterSend?: boolean;
  /** Etykieta nad przełącznikiem — wąska karta „CV do klienta”. */
  compact?: boolean;
}

/**
 * Układ CV: Nowe CV (PDF) albo Klasyczne (Word). Jedno ustawienie CV —
 * ten sam tekst w obu układach, przełączenie nie generuje CV od nowa.
 */
export function LayoutChoice({
  value,
  onChange,
  place,
  clientName = null,
  clientDefault = "classic",
  disabled = false,
  lockedAfterSend = false,
  compact = false,
}: LayoutChoiceProps) {
  const hint =
    place === "generator"
      ? [
          clientDefault === "new" && clientName
            ? `${clientName}: domyślnie Nowe CV.`
            : null,
          "Układ zmienisz też po wygenerowaniu — bez generowania od nowa.",
        ]
          .filter(Boolean)
          .join(" ")
      : "Ten sam tekst w obu układach. Zmiana układu nie generuje CV od nowa i nie kasuje poprawek.";
  return (
    <div
      data-testid={`cv-layout-choice-${place}`}
      className={compact ? "grid gap-2" : "grid gap-2 sm:grid-cols-[110px_minmax(0,1fr)] sm:items-start"}
    >
      <p className="pt-1.5 text-sm font-semibold text-foreground">Układ CV</p>
      <div className="space-y-2">
        {/* Kotwica lekcji „Nowe CV” (23.11.2026) — przełącznik w karcie „CV do klienta”. */}
        <div
          className="flex flex-wrap items-center gap-2"
          data-tour={place === "card" ? "cv.layout-choice" : undefined}
        >
          <Segmented<CvLayout>
            label="Układ CV"
            value={value}
            onChange={onChange}
            disabled={disabled || lockedAfterSend}
            options={compact ? COMPACT_OPTIONS : OPTIONS}
          />
          {lockedAfterSend ? (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Lock className="h-3.5 w-3.5" aria-hidden /> po wysyłce do klienta
            </span>
          ) : null}
        </div>
        {lockedAfterSend ? null : (
          <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
        )}
      </div>
    </div>
  );
}


/* ---------- Makieta rundy 36 (23.11.2026): wybór układu jako dwie karty ---------- */

const CARD_COPY: Record<CvLayout, { title: string; file: string; points: string[] }> = {
  new: {
    title: "Nowe CV",
    file: "PDF",
    points: [
      "Strona 1 to podsumowanie dla klienta: 3 zdania „Dlaczego nasz kandydat”, oś kariery, umiejętności, certyfikaty.",
      "Od strony 2 stanowiska w tabelkach.",
      "Poprawki w edytorze w zakładkach „Strona 1” i „Stanowiska”.",
    ],
  },
  classic: {
    title: "Klasyczne",
    file: "Word",
    points: [
      "Dotychczasowy szablon firmowy, tekst od góry do dołu.",
      "Klient dostaje plik .docx.",
      "Wybierz, gdy klient prosi o Worda.",
    ],
  },
};

/** Szkic strony 1 z CSS (bez danych osobowych): tytuł, 3 zdania, oś, bloki. */
function PageSketch({ layout }: { layout: CvLayout }) {
  if (layout === "classic") {
    return (
      <div aria-hidden className="h-[118px] w-[84px] shrink-0 rounded-sm border border-border bg-card p-1.5 shadow-sm">
        <div className="h-1.5 w-10 rounded-sm bg-muted-foreground/40" />
        {Array.from({ length: 11 }).map((_, i) => (
          <div key={i} className={cn("mt-1 h-1 rounded-sm bg-muted-foreground/20", i % 4 === 3 ? "w-9" : "w-full")} />
        ))}
      </div>
    );
  }
  return (
    <div aria-hidden className="h-[118px] w-[84px] shrink-0 rounded-sm border border-border bg-card p-1.5 shadow-sm">
      <div className="flex items-start justify-between">
        <div className="h-1.5 w-9 rounded-sm bg-primary" />
        <div className="flex gap-0.5">
          <div className="h-1.5 w-2.5 rounded-full border border-primary" />
          <div className="h-1.5 w-2.5 rounded-full border border-primary" />
        </div>
      </div>
      <div className="mt-0.5 h-1 w-6 rounded-sm bg-foreground/70" />
      <div className="mt-1.5 h-1 w-7 rounded-sm bg-primary" />
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="mt-1 border-t border-border pt-0.5">
          <div className="h-0.5 w-full rounded-sm bg-muted-foreground/30" />
        </div>
      ))}
      <div className="mt-1.5 h-1 w-7 rounded-sm bg-primary" />
      <div className="mt-1 flex h-1.5 gap-px">
        <div className="w-5 bg-muted-foreground/25" />
        <div className="w-6 bg-muted-foreground/25" />
        <div className="flex-1 bg-primary" />
      </div>
      <div className="mt-1.5 h-1 w-7 rounded-sm bg-primary" />
      <div className="mt-1 grid grid-cols-[14px_1fr] gap-px">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="contents">
            <div className="h-0.5 bg-foreground/50" />
            <div className="h-0.5 bg-muted-foreground/30" />
          </div>
        ))}
      </div>
    </div>
  );
}

export interface LayoutCardsProps {
  value: CvLayout;
  onChange: (value: CvLayout) => void;
  clientName?: string | null;
  clientDefault?: CvLayout;
  /** Plik, którego chce klient (reguła CV, 25.11.2026); Word przy Nowym CV = ostrzeżenie. */
  clientFileFormat?: CvFileFormat | null;
  disabled?: boolean;
}

/** Wybór układu w generatorze jako dwie karty z podglądem strony 1 (makieta rundy 36). */
export function LayoutCards({
  value,
  onChange,
  clientName = null,
  clientDefault = "classic",
  clientFileFormat = null,
  disabled = false,
}: LayoutCardsProps) {
  const warnWord = cvDownloadPlan(clientFileFormat, value).warnWordClassic;
  return (
    <div className="space-y-2" data-testid="cv-layout-cards">
      <div role="radiogroup" aria-label="Układ CV" className="grid gap-3 md:grid-cols-2">
        {(["new", "classic"] as const).map((layout) => {
          const copy = CARD_COPY[layout];
          const selected = value === layout;
          return (
            <button
              key={layout}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              onClick={() => onChange(layout)}
              className={cn(
                "flex gap-3 rounded-xl border p-3 text-left transition-colors",
                selected ? "border-primary bg-primary/5 ring-1 ring-primary" : "border-border bg-card hover:border-primary/50",
              )}
            >
              <PageSketch layout={layout} />
              <div className="min-w-0 space-y-1.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[15px] font-semibold text-foreground">{copy.title}</span>
                  <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px] font-semibold text-muted-foreground">{copy.file}</span>
                  {layout === "new" ? (
                    <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[11px] font-semibold text-primary">polecane</span>
                  ) : null}
                  {selected ? <Check className="h-4 w-4 text-primary" aria-label="wybrane" /> : null}
                </div>
                <ul className="space-y-1 text-[12.5px] leading-snug text-muted-foreground">
                  {copy.points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              </div>
            </button>
          );
        })}
      </div>
      <p className="text-xs text-muted-foreground">
        {clientDefault === "new" && clientName ? `${clientName}: domyślnie Nowe CV. ` : null}
        Ten sam tekst w obu układach. Układ zmienisz też po wygenerowaniu, bez generowania od nowa.
      </p>
      {warnWord ? (
        <p
          role="note"
          data-testid="cv-layout-word-classic-warning"
          className="rounded-md border border-warning/30 bg-warning-muted px-2.5 py-2 text-xs text-warning-muted-foreground"
        >
          {wordClassicWarning(clientFileFormat)}
        </p>
      ) : null}
    </div>
  );
}
