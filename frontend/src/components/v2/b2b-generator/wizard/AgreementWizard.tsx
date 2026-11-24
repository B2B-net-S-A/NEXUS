"use client";

/**
 * Układ „Nowej umowy” w Generatorze (etap 3b przebudowy modułu Kontrakty,
 * wariant A z makiet 19.11.2026 z paskiem braków z wariantu B):
 *  - po lewej lista kroków ze stanem („2 braki” albo to, co wpisano),
 *  - w środku formularz jednego kroku (pola trzyma `GeneratorForm`),
 *  - po prawej „kartka” — pierwszy akapit umowy wypełniany na żywo,
 *  - na dole przyklejony pasek: ile pól brakuje i które, „Podgląd”, „Pobierz”.
 *
 * Komponenty tylko pokazują — stan, walidacja i pobranie zostają w formularzu,
 * więc umowa generuje się dokładnie tak jak przed przebudową.
 */

import * as React from "react";
import {
  ArrowRight,
  Check,
  Download,
  Eye,
  Loader2,
  Lock,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import type {
  PaperParagraph,
  PaperSegment,
} from "@/lib/b2b-agreement-paper";
import {
  gapsLabel,
  missingCountLabel,
  missingInStep,
  type GeneratorFormStep,
  type GeneratorMissing,
  type GeneratorStep,
} from "@/lib/b2b-generator-wizard";
import { cn } from "@/lib/utils";

export interface WizardStepItem {
  key: GeneratorStep;
  label: string;
  summary: string;
  /** Liczba braków w kroku (dla „Sprawdź i pobierz” — wszystkich). */
  gaps: number;
  /**
   * Krok czeka na inny (szczegóły administracyjne przed wyborem rekrutacji):
   * bez braków, ale też bez ✓ — nie ma jeszcze czego uzupełnić.
   */
  waiting?: boolean;
}

/** Lista kroków: numer albo ✓, nazwa i jedna linia stanu. */
export function AgreementStepList({
  steps,
  current,
  onGo,
}: {
  steps: readonly WizardStepItem[];
  current: GeneratorStep;
  onGo: (step: GeneratorStep) => void;
}) {
  return (
    <nav aria-label="Kroki umowy" data-tour="b2b-generator.steps">
      <ol className="flex gap-1 overflow-x-auto pb-1 @4xl:flex-col @4xl:gap-0 @4xl:overflow-visible @4xl:pb-0">
        {steps.map((s, i) => {
          const active = s.key === current;
          const download = s.key === "pobierz";
          const done = !download && s.gaps === 0 && !s.waiting;
          const ready = download && s.gaps === 0;
          return (
            <li key={s.key} className="relative shrink-0 @4xl:shrink">
              {i < steps.length - 1 ? (
                <span
                  aria-hidden
                  className="absolute bottom-[-6px] left-[19px] top-[34px] hidden w-px bg-border @4xl:block"
                />
              ) : null}
              <button
                type="button"
                onClick={() => onGo(s.key)}
                aria-current={active ? "step" : undefined}
                data-tour={s.key === "admin" ? "b2b-generator.step-admin" : undefined}
                className={cn(
                  "relative flex w-full items-start gap-2.5 rounded-lg px-2 py-2 text-left transition-colors",
                  active
                    ? "bg-card shadow-xs ring-1 ring-border"
                    : "hover:bg-muted/60",
                )}
              >
                <span
                  className={cn(
                    "grid size-6 shrink-0 place-items-center rounded-full text-[11.5px] font-semibold tabular-nums",
                    active
                      ? "bg-primary text-primary-foreground"
                      : done || ready
                        ? "bg-success-muted text-success-muted-foreground"
                        : "border border-border bg-card text-muted-foreground",
                  )}
                >
                  {(done || ready) && !active ? (
                    <Check className="size-3.5" aria-label="komplet" />
                  ) : download && !ready && !active ? (
                    <Lock className="size-3" aria-label="czeka na komplet" />
                  ) : (
                    i + 1
                  )}
                </span>
                <span className="min-w-0 pt-px">
                  <span
                    className={cn(
                      "block whitespace-nowrap text-[13px] leading-4 text-foreground @4xl:whitespace-normal",
                      active ? "font-semibold" : "font-medium",
                    )}
                  >
                    {s.label}
                  </span>
                  {s.summary ? (
                    <span
                      className={cn(
                        "mt-0.5 hidden break-words text-[11.5px] leading-4 @4xl:line-clamp-2",
                        s.gaps > 0
                          ? "text-warning-muted-foreground"
                          : "text-muted-foreground",
                      )}
                      title={s.summary}
                    >
                      {s.summary}
                    </span>
                  ) : null}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Rama kroku: nazwa, „Krok n z 7”, jedno zdanie po co, stopka Wstecz/Dalej. */
export function AgreementStepPanel({
  title,
  index,
  total,
  intro,
  previousLabel,
  nextLabel,
  onPrevious,
  onNext,
  children,
}: {
  title: string;
  index: number;
  total: number;
  intro: string;
  previousLabel: string | null;
  nextLabel: string | null;
  onPrevious: () => void;
  onNext: () => void;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-label={title}
      data-gen-panel
      className="@container min-w-0 scroll-mt-4 rounded-xl border border-border bg-card shadow-xs"
    >
      <header className="border-b border-border/70 px-4 py-2.5">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
          <span className="shrink-0 text-[12px] tabular-nums text-muted-foreground">
            Krok {index + 1} z {total}
          </span>
        </div>
        <p className="mt-0.5 text-[12.5px] leading-4 text-muted-foreground">
          {intro}
        </p>
      </header>
      <div className="px-4 py-3">{children}</div>
      <footer className="flex items-center justify-between gap-2 border-t border-border/70 px-4 py-2.5">
        {previousLabel ? (
          <Button type="button" variant="ghost" size="sm" onClick={onPrevious}>
            Wstecz
          </Button>
        ) : (
          <span />
        )}
        {nextLabel ? (
          <Button type="button" variant="outline" size="sm" onClick={onNext}>
            Dalej: {nextLabel}
            <ArrowRight className="size-3.5" aria-hidden />
          </Button>
        ) : null}
      </footer>
    </section>
  );
}

function Segment({
  segment,
  onGap,
}: {
  segment: PaperSegment;
  onGap: (step: GeneratorFormStep, field: string) => void;
}) {
  if (segment.kind === "gap") {
    return (
      <button
        type="button"
        onClick={() => onGap(segment.step, segment.field)}
        title={`Uzupełnij: ${segment.label}`}
        className={cn(
          "rounded-[3px] bg-warning-muted px-1 py-px text-[10.5px] font-semibold text-warning-muted-foreground hover:underline",
          segment.strong && "font-bold",
        )}
      >
        [{segment.label}]
      </button>
    );
  }
  if (segment.kind === "value") {
    return (
      <span
        className={cn("rounded-[3px] bg-primary/8 px-0.5", segment.strong && "font-semibold")}
      >
        {segment.text}
      </span>
    );
  }
  return segment.strong ? (
    <span className="font-semibold">{segment.text}</span>
  ) : (
    <>{segment.text}</>
  );
}

const PARAGRAPH_TONE: Record<PaperParagraph["tone"], string> = {
  title: "text-center text-[12.5px] font-bold",
  subtitle: "mb-1.5 text-center text-[12px] font-semibold tabular-nums",
  body: "mt-1.5",
  muted: "mt-1.5 text-muted-foreground",
};

/**
 * „Kartka” — pierwszy akapit umowy z brakami w tekście. Klik w brak przenosi
 * do pola. Tylko podgląd: dokument tworzy szablon na serwerze.
 */
export function AgreementPaperPreview({
  paragraphs,
  gaps,
  onGap,
}: {
  paragraphs: readonly PaperParagraph[];
  gaps: number;
  onGap: (step: GeneratorFormStep, field: string) => void;
}) {
  return (
    <div data-testid="agreement-paper" data-tour="b2b-generator.paper">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="text-[12.5px] font-semibold text-foreground">Podgląd na żywo</p>
        <p
          className={cn(
            "text-[11.5px]",
            gaps ? "text-warning-muted-foreground" : "text-success",
          )}
        >
          {gaps ? `${gapsLabel(gaps)} w tym akapicie` : "akapit kompletny"}
        </p>
      </div>
      <article
        aria-label="Pierwszy akapit umowy"
        className="relative overflow-hidden rounded-[3px] border border-border bg-card px-5 pb-8 pt-5 text-[11.5px] leading-[1.6] text-foreground shadow-md"
      >
        {paragraphs.map((p, i) => (
          <p key={i} className={PARAGRAPH_TONE[p.tone]}>
            {p.segments.map((s, j) => (
              <Segment key={j} segment={s} onGap={onGap} />
            ))}
          </p>
        ))}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-linear-to-b from-transparent to-card"
        />
      </article>
      <p className="mt-1.5 text-[11.5px] leading-4 text-muted-foreground">
        Tylko początek umowy. Pełny tekst pokaże „Podgląd”, a dokument tworzy
        szablon przy pobraniu.
      </p>
    </div>
  );
}

/** Przyklejony pasek gotowości: braki (klik → pole), „Podgląd”, „Pobierz”. */
export function AgreementReadinessBar({
  missing,
  onGo,
  readyText,
  status,
  previewBusy,
  onPreview,
  downloadLabel,
  downloadBusy,
  downloadDisabled = false,
  onDownload,
}: {
  /** Braki ułożone po krokach. */
  missing: readonly GeneratorMissing[];
  onGo: (step: GeneratorFormStep, field: string) => void;
  readyText: string;
  /** Np. „Sprawdzam firmę w rejestrze…” w trakcie pobierania. */
  status: string | null;
  previewBusy: boolean;
  onPreview: () => void;
  downloadLabel: string;
  downloadBusy: boolean;
  /** Pobranie wstrzymane mimo kompletu pól (np. nieudane sprawdzenie umów osoby). */
  downloadDisabled?: boolean;
  onDownload: () => void;
}) {
  const ready = missing.length === 0;
  const blocked = ready
    ? undefined
    : `${missingCountLabel(missing.length)}: ${missing.map((m) => m.label).join(", ")}`;
  const nipMissing = missing.some((m) => m.field === "nip");
  return (
    <div
      role="region"
      aria-label="Gotowość umowy"
      data-testid="agreement-readiness-bar"
      data-tour="b2b-generator.readiness"
      className="sticky bottom-3 z-20 mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-border bg-card/95 px-4 py-2.5 shadow-lg backdrop-blur @4xl:mr-14 @4xl:flex-nowrap"
    >
      <div className="min-w-0 flex-1 basis-64">
        {status ? (
          <p role="status" className="flex items-center gap-1.5 text-[13px] text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            {status}
          </p>
        ) : ready ? (
          <p className="flex items-center gap-1.5 text-[13px] font-semibold text-success">
            <Check className="size-4 shrink-0" aria-hidden />
            {readyText}
          </p>
        ) : (
          <p className="line-clamp-2 text-[13px] leading-5 text-muted-foreground">
            <span className="mr-1.5 inline-flex items-center gap-1.5 font-semibold text-foreground">
              <span aria-hidden className="size-2 rounded-full bg-warning" />
              {missingCountLabel(missing.length)}:
            </span>
            {missing.map((m, i) => (
              <React.Fragment key={`${m.step}-${m.field}-${m.label}`}>
                {i > 0 ? ", " : null}
                <button
                  type="button"
                  onClick={() => onGo(m.step, m.field)}
                  className="text-foreground underline decoration-border underline-offset-2 hover:decoration-foreground"
                >
                  {m.label}
                </button>
              </React.Fragment>
            ))}
            .
            {nipMissing ? (
              <span className="text-[12px]">
                {" "}
                NIP uzupełni nazwę firmy, REGON i adres z rejestru.
              </span>
            ) : null}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onPreview}
          disabled={previewBusy}
          title="Cała umowa z wpisanymi danymi; podgląd nie zajmuje numeru"
        >
          {previewBusy ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <Eye className="size-3.5" aria-hidden />
          )}
          Podgląd
        </Button>
        <Button
          type="button"
          size="sm"
          onClick={onDownload}
          disabled={!ready || downloadBusy || downloadDisabled}
          title={blocked}
          data-help="contracts.b2b_generator.docx"
        >
          {downloadBusy ? (
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
          ) : (
            <Download className="size-3.5" aria-hidden />
          )}
          {downloadLabel}
        </Button>
      </div>
    </div>
  );
}

/** Krok „Sprawdź i pobierz”: braki po krokach z „Uzupełnij” i co zrobi pobranie. */
export function AgreementDownloadSummary({
  steps,
  missing,
  onGo,
  notes,
}: {
  steps: readonly WizardStepItem[];
  missing: readonly GeneratorMissing[];
  onGo: (step: GeneratorFormStep, field: string) => void;
  /** Zdania o numerze, rejestrze CEIDG/KRS i kontrakcie po podpisie. */
  notes: readonly string[];
}) {
  const sections = steps
    .filter((s) => s.key !== "pobierz")
    .map((s) => ({ ...s, items: missingInStep(missing, s.key) }))
    .filter((s) => s.items.length > 0);
  return (
    <div className="space-y-3">
      {sections.length === 0 ? (
        <p className="rounded-lg bg-success-muted px-3 py-2 text-[13px] text-success-muted-foreground">
          Wszystko uzupełnione — umowę można pobrać.
        </p>
      ) : (
        <div>
          <p className="mb-1.5 text-[13px] font-semibold text-foreground">
            {missingCountLabel(missing.length)}
          </p>
          <ul className="divide-y divide-border/60 rounded-lg border border-border">
            {sections.map((s) => (
              <li
                key={s.key}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-[12.5px] leading-5"
              >
                <span className="w-[150px] shrink-0 font-medium text-foreground">
                  {s.label}
                </span>
                <span className="min-w-0 flex-1 text-muted-foreground">
                  {s.items.map((m) => m.label).join(", ")}
                </span>
                <button
                  type="button"
                  onClick={() => onGo(s.items[0].step, s.items[0].field)}
                  className="shrink-0 font-medium text-primary hover:underline"
                >
                  Uzupełnij
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <ul className="space-y-1 text-[12.5px] leading-5 text-muted-foreground">
        {notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </div>
  );
}
