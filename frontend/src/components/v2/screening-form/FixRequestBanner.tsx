"use client";

/**
 * „Delivery Lead prosi o poprawki (N)” nad formularzem screeningu (D6,
 * 08.10.2026) i znacznik przy polu. Lista pól, uwaga DL i stan każdego pola
 * („Do poprawy” / „Zmienione — zapisz” / „Poprawione”). CV firmowe poprawia
 * się w edytorze CV — tu tylko stan.
 */

import { CheckCircle2, CircleDot, PencilLine } from "lucide-react";

import type { ScreeningFixRequest } from "@/lib/api/screeningForm";
import { FIX_STATE_LABEL, fixFieldState, type FixFieldState } from "@/lib/screening-fix-request";
import { cn, formatDate } from "@/lib/utils";

const STATE_CLASS: Record<FixFieldState, string> = {
  todo: "border-warning/40 bg-warning-muted text-warning-muted-foreground",
  edited: "border-info/30 bg-info-muted text-info-muted-foreground",
  done: "border-success/30 bg-success-muted text-success-muted-foreground",
};

function StateIcon({ state }: { state: FixFieldState }) {
  if (state === "done") return <CheckCircle2 className="size-3" aria-hidden />;
  if (state === "edited") return <PencilLine className="size-3" aria-hidden />;
  return <CircleDot className="size-3" aria-hidden />;
}

export function FixMark({ state }: { state: FixFieldState | null }) {
  if (!state) return null;
  return (
    <span
      className={cn(
        "inline-flex w-fit items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        STATE_CLASS[state],
      )}
      data-fix-state={state}
    >
      <StateIcon state={state} />
      {FIX_STATE_LABEL[state]}
    </span>
  );
}

export function FixRequestBanner({
  request,
  dirty,
}: {
  request: ScreeningFixRequest;
  dirty?: Record<string, unknown>;
}) {
  const who = request.requested_by_name?.trim() || "Delivery Lead";
  return (
    <section
      aria-label="Prośba Delivery Leada o poprawki"
      className="space-y-2 rounded-lg border border-warning/40 bg-warning-muted/60 px-3 py-2.5 text-xs"
      data-testid="fix-request-banner"
    >
      <p className="font-semibold text-foreground">
        Delivery Lead prosi o poprawki ({request.count})
        {request.changed_count > 0 ? ` · poprawione ${request.changed_count} z ${request.count}` : ""}
      </p>
      <p className="text-muted-foreground">
        {who}
        {request.requested_at ? ` · ${formatDate(request.requested_at)}` : ""} — popraw zaznaczone pola, zapisz
        i oddaj kartę do przeglądu.
      </p>
      {request.remark ? (
        <p className="whitespace-pre-line text-foreground [overflow-wrap:anywhere]">Uwaga: „{request.remark}”</p>
      ) : null}
      {request.fields.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Pola do poprawy">
          {request.fields.map((field) => {
            const state = fixFieldState(request, field.key, dirty) ?? "todo";
            return (
              <li
                key={field.key}
                className={cn(
                  "inline-flex max-w-full items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
                  STATE_CLASS[state],
                )}
                data-fix-key={field.key}
                data-fix-state={state}
              >
                <StateIcon state={state} />
                <span className="truncate">{field.label}</span>
                <span className="sr-only"> — {FIX_STATE_LABEL[state]}</span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
