"use client";

import { useId, useState } from "react";
import { ChevronRight } from "lucide-react";

import { classifyCvWarnings, type CvAutoRepair } from "@/lib/cv-generator";
import { cn } from "@/lib/utils";

import { StatusChip } from "./GeneratorParts";

export interface CvWarningsProps {
  warnings: readonly string[] | null | undefined;
  /** Klik „Pokaż w CV” — otwiera podgląd dokumentu. */
  onShowInCv?: () => void;
}

/**
 * Uwagi do CV w dwóch grupach: „Do sprawdzenia” (to, co może być w CV
 * nieprawdą albo czego brakuje) i zwinięte „Informacje” (co generator zrobił).
 */
export function CvWarnings({ warnings, onShowInCv }: CvWarningsProps) {
  const infoId = useId();
  const [infoOpen, setInfoOpen] = useState(false);
  const { review, info, infoKinds, repairs } = classifyCvWarnings(warnings);
  if (review.length === 0 && info.length === 0 && repairs.length === 0) {
    return <p className="text-sm text-muted-foreground">Bez uwag — generator nie zgłosił niczego do sprawdzenia.</p>;
  }
  return (
    <div className="space-y-3">
      {review.length > 0 ? (
        <section aria-label="Do sprawdzenia" className="rounded-xl border border-warning/30 bg-card">
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
            <h3 className="text-sm font-semibold text-foreground">Do sprawdzenia</h3>
            <StatusChip tone="warn">{review.length}</StatusChip>
            <span className="text-xs text-muted-foreground">Tylko to, co może być w CV nieprawdą</span>
          </div>
          <ul className="divide-y divide-border">
            {review.map((item) => (
              <li key={item.text} className="flex flex-wrap items-start gap-x-3 gap-y-1 px-4 py-3">
                <span className="w-full text-xs font-semibold uppercase tracking-wide text-warning-muted-foreground sm:w-36 sm:flex-none">
                  {item.kind}
                </span>
                <span className="min-w-0 flex-1 text-sm text-foreground">{item.text}</span>
                {onShowInCv ? (
                  <button type="button" onClick={onShowInCv} className="text-sm font-medium text-primary hover:underline">
                    Pokaż w CV
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {repairs.length > 0 ? <CvAutoRepairs repairs={repairs} /> : null}
      {info.length > 0 ? (
        <div className="rounded-xl border border-border bg-card">
          <button
            type="button"
            aria-expanded={infoOpen}
            aria-controls={infoId}
            onClick={() => setInfoOpen((open) => !open)}
            className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ChevronRight aria-hidden className={cn("h-4 w-4 flex-none text-muted-foreground transition-transform", infoOpen && "rotate-90")} />
            <span className="font-semibold text-foreground">{`Informacje (${info.length})`}</span>
            <span className="min-w-0 truncate text-muted-foreground">
              — {infoKinds.map((k) => `${k.kind} (${k.count})`).join(", ")}
            </span>
          </button>
          {infoOpen ? (
            <ul id={infoId} className="space-y-1.5 border-t border-border px-4 py-3 text-sm text-muted-foreground">
              {info.map((item) => (
                <li key={item.text}>{item.text}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Co generator zmienił sam po kontroli AI. Pierwotna treść jest zawsze widoczna,
 * bo model poprawiający mógł się pomylić, a rekruter zna kandydata.
 */
function CvAutoRepairs({ repairs }: { repairs: readonly CvAutoRepair[] }) {
  const [copied, setCopied] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  async function copy(repair: CvAutoRepair) {
    try {
      await navigator.clipboard.writeText(repair.before);
      setCopied(repair.text);
      setFailed(null);
    } catch {
      setFailed(repair.text);
    }
  }
  return (
    <section aria-label="Poprawione automatycznie" data-tour="cv.result.auto-repairs" className="rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h3 className="text-sm font-semibold text-foreground">Poprawione automatycznie</h3>
        <StatusChip tone="neutral">{repairs.length}</StatusChip>
        <span className="text-xs text-muted-foreground">
          Kontrola AI nie znalazła tego w CV ani w notatkach. Jeśli to prawda, wklej tekst z powrotem w edytorze CV.
        </span>
      </div>
      <ul className="divide-y divide-border">
        {repairs.map((repair) => (
          <li key={repair.text} className="space-y-1 px-4 py-3 text-sm">
            <span className="block text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {repair.action === "rewrite" ? "Skrócono" : "Usunięto"} · {repair.field}
            </span>
            <p className="text-foreground">
              <span className="text-muted-foreground">Było: </span>
              {repair.before}
            </p>
            {repair.action === "rewrite" ? (
              <p className="text-foreground">
                <span className="text-muted-foreground">Jest: </span>
                {repair.after}
              </p>
            ) : null}
            <button
              type="button"
              onClick={() => void copy(repair)}
              className="text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              {copied === repair.text ? "Skopiowano" : "Kopiuj pierwotny tekst"}
            </button>
            {failed === repair.text ? (
              <p role="alert" className="text-xs text-destructive">
                Nie udało się skopiować. Zaznacz tekst ręcznie.
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
