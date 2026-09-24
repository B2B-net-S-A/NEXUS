"use client";

import { useId } from "react";
import { ChevronRight } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { StatusChip } from "./GeneratorParts";

export interface AdvancedOptionsProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  blind: boolean;
  onBlindChange: (value: boolean) => void;
  position: string;
  onPositionChange: (value: string) => void;
  positionRequired: boolean;
  /** Stanowisko podpowiedziane z tytułu rekrutacji. */
  positionFromJob: boolean;
  projectRef: string;
  onProjectRefChange: (value: string) => void;
  projectRefVisible: boolean;
  projectRefRequired: boolean;
  /** Numer z rekrutacji (PKO BP) — tylko do odczytu. */
  projectRefFromJob: string | null;
}

/**
 * „Zaawansowane” — Blind CV, stanowisko, numer projektu. Zwinięte, ale
 * rozwijają się same, gdy wymagane pole w środku jest puste.
 */
export function AdvancedOptions(props: AdvancedOptionsProps) {
  const panelId = useId();
  const positionId = useId();
  const projectId = useId();
  const blindId = useId();
  const star = <span className="text-destructive" aria-hidden> *</span>;
  return (
    <div className="mt-4 border-t border-border pt-3">
      <button
        type="button"
        aria-expanded={props.open}
        aria-controls={panelId}
        onClick={() => props.onOpenChange(!props.open)}
        className="inline-flex items-center gap-1.5 rounded-md text-sm font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronRight aria-hidden className={cn("h-4 w-4 transition-transform", props.open && "rotate-90")} />
        Zaawansowane
        {!props.open ? (
          <span className="font-normal text-muted-foreground">— Blind CV, stanowisko, numer projektu{props.blind ? " (Blind CV włączone)" : ""}</span>
        ) : null}
      </button>
      {props.open ? (
        <div id={panelId} className="mt-4 space-y-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <label htmlFor={blindId} className="block text-sm font-semibold text-foreground">Blind CV</label>
              <p className="text-xs text-muted-foreground">
                Ukryj imię, nazwisko i nazwy firm. Tylko gdy klient prosi o CV anonimowe.
              </p>
            </div>
            <Switch id={blindId} checked={props.blind} onCheckedChange={props.onBlindChange} />
          </div>
          <div className="space-y-1.5">
            <label htmlFor={positionId} className="block text-sm font-semibold text-foreground">
              Stanowisko{props.positionRequired ? star : null}
            </label>
            <Input
              id={positionId}
              value={props.position}
              maxLength={300}
              onChange={(event) => props.onPositionChange(event.target.value)}
              placeholder="np. Analityk Biznesowy"
              className="sm:max-w-md"
            />
            <p className="text-xs text-muted-foreground">
              {props.positionFromJob
                ? "Z tytułu rekrutacji. Trafia do nagłówka CV i do nazwy pliku."
                : "Trafia do nagłówka CV i do nazwy pliku."}
            </p>
          </div>
          {props.projectRefVisible ? (
            <div className="space-y-1.5">
              {props.projectRefFromJob ? (
                <>
                  <p className="text-sm font-semibold text-foreground">Numer projektu</p>
                  <p className="flex items-center gap-2 text-sm text-foreground">
                    <span className="font-mono">{props.projectRefFromJob}</span>
                    <StatusChip tone="ok">z rekrutacji</StatusChip>
                  </p>
                </>
              ) : (
                <>
                <label htmlFor={projectId} className="block text-sm font-semibold text-foreground">
                  Numer projektu{props.projectRefRequired ? star : null}
                </label>
                <Input
                  id={projectId}
                  value={props.projectRef}
                  maxLength={120}
                  onChange={(event) => props.onProjectRefChange(event.target.value)}
                  placeholder="np. ZOB/2026/114"
                  className="sm:max-w-md"
                />
                </>
              )}
              <p className="text-xs text-muted-foreground">Wchodzi do nazwy pliku zgodnie ze wzorem klienta.</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
