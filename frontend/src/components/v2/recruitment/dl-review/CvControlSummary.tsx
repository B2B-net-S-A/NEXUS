"use client";

/**
 * „Kontrola CV” w kolumnie decyzji przeglądu DL (R5, 07.11.2026). Do tej
 * zmiany wynik QC był tylko pigułką „QC ✓” — Delivery Lead nie wiedział, co
 * sprawdził automat, co rekruter ręcznie, a czego nikt (139 z 535 zdanych par
 * miało krytyczne „sprawdź ręcznie”). Liczy `cvControlSummary` z wyniku QC.
 */

import { AlertTriangle, CheckCircle2, Hand, HelpCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { QcCheck } from "@/lib/api/cvQc";
import { countForm, cvControlSummary, type QcStateTone, type QcStateView } from "@/lib/cv-qc";
import { cn } from "@/lib/utils";

export interface CvControlOverride {
  by_name?: string | null;
  reason: string;
  at?: string | null;
}

export interface CvControlSummaryProps {
  /** Wynik QC; `undefined` = jeszcze się liczy. */
  checks: readonly QcCheck[] | undefined;
  /** Stan z serwera (`qc_state`) — nagłówek „Kontrola CV · sprawdzone”. */
  state?: QcStateView | null;
  /** Obejście QC — linia „Przepuszczone mimo uwag”. */
  override: CvControlOverride | null;
  /** Panel ma już baner obejścia — bez drugiej linii o tym samym. */
  hideOverrideLine?: boolean;
  onOpenQc: () => void;
}

function Line({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="grid grid-cols-[16px_1fr] items-start gap-2">
      <span className="mt-0.5">{icon}</span>
      <span className="min-w-0 [overflow-wrap:anywhere]">{children}</span>
    </li>
  );
}

const STATE_TONE: Record<QcStateTone, string> = {
  ok: "text-success",
  info: "text-info",
  wait: "text-warning",
  urgent: "text-destructive",
  neutral: "text-muted-foreground",
};

export function CvControlSummary({ checks, state = null, override, hideOverrideLine = false, onOpenQc }: CvControlSummaryProps) {
  const control = checks ? cvControlSummary(checks) : null;
  return (
    <section aria-label="Kontrola CV" className="space-y-1.5 rounded-lg border border-border px-3 py-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          Kontrola CV
          {state ? <span className={cn("font-medium", STATE_TONE[state.tone])}> · {state.text.replace(/^QC: /, "")}</span> : null}
        </h3>
        <Button size="sm" variant="ghost" className="h-6 shrink-0 px-2 text-xs" onClick={onOpenQc}>
          Otwórz QC
        </Button>
      </div>
      {!control ? (
        <p className="text-muted-foreground">Sprawdzam QC…</p>
      ) : (
        <ul className="space-y-1">
          <Line icon={<CheckCircle2 className="size-4 text-success" aria-hidden />}>
            {countForm(control.autoOk, ["sprawdzenie automatu", "sprawdzenia automatu", "sprawdzeń automatu"])} w porządku
          </Line>
          {control.blocking > 0 ? (
            <Line
              icon={<AlertTriangle className="size-4 text-destructive" aria-hidden />}
            >
              {countForm(control.blocking, ["rzecz", "rzeczy", "rzeczy"])} do poprawy przed wysłaniem
            </Line>
          ) : null}
          {control.gaps.map((requirement) => (
            <Line key={`gap-${requirement}`} icon={<AlertTriangle className="size-4 text-warning" aria-hidden />}>
              {requirement} — kandydat tego nie ma, decyzja o wysyłce należy do Ciebie
            </Line>
          ))}
          {control.manual.map((entry) => (
            <Line key={entry.requirement} icon={<Hand className="size-4 text-info" aria-hidden />}>
              {entry.roles.length > 0
                ? `${entry.requirement} opisane w: ${entry.roles.join(", ")}`
                : `${entry.requirement} — oryginał nie opisuje tego w żadnej roli`}
              {entry.by ? ` — wskazał(a) ${entry.by}` : ""}
            </Line>
          ))}
          {control.unverified.map((requirement) => (
            <Line
              key={requirement}
              icon={<HelpCircle className="size-4 text-warning" aria-hidden />}
            >
              {requirement} — nikt nie sprawdził opisu w rolach
            </Line>
          ))}
          {control.consentManual ? (
            <Line
              icon={<HelpCircle className="size-4 text-warning" aria-hidden />}
            >
              Zgoda RODO z pliku kandydata — obejrzyj ręcznie
            </Line>
          ) : null}
          {control.dismissed.map((entry, i) => (
            <Line
              key={`dismissed-${entry.what}-${i}`}
              icon={<AlertTriangle className="size-4 text-warning" aria-hidden />}
            >
              Pominięte jako nieprawdziwe: {entry.what}
              {entry.by || entry.reason ? " — " : ""}
              {[entry.by, entry.reason].filter(Boolean).join(": ")}
            </Line>
          ))}
          {override && !hideOverrideLine ? (
            <Line icon={<AlertTriangle className="size-4 text-warning" aria-hidden />}>
              Przepuszczone mimo uwag — {override.by_name ?? "rekruter"}: {override.reason.replace(/[.\s]+$/, "")}
            </Line>
          ) : !override && control.dismissed.length === 0 ? (
            <Line icon={<CheckCircle2 className="size-4 text-success" aria-hidden />}>Nic nie przepuszczono mimo uwag</Line>
          ) : null}
        </ul>
      )}
    </section>
  );
}

/** Punkty QC do „Wróć do poprawy” — to, co rekruter może poprawić w CV. */
export function cvReturnPoints(checks: readonly QcCheck[] | undefined): string[] {
  if (!checks) return [];
  const control = cvControlSummary(checks);
  const fails = checks
    .filter((check) => check.status === "fail")
    .map((check) => check.label);
  return [...control.unverified.map((r) => `${r} — opisz w roli, w której kandydat tego używał`), ...fails];
}
