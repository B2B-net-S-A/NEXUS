"use client";

/**
 * Pasek „polecenia dla całego CV” (Edytor CV 2, PR 4): własne słowa albo
 * gotowe polecenie → „Przygotuj zmiany”. Wynik to PLAN w panelu obok
 * (`CvEditorPlan`) — sam pasek niczego w CV nie zmienia.
 */

import { useId, useState } from "react";
import { Loader2, Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CV_COMMAND_PRESETS } from "@/lib/api/cvEditorCommand";
import { CV_COMMAND_MAX } from "@/lib/cv-editor-command";

import type { CvCommandController } from "./useCvCommandPlan";

/** Znacznik korzenia: Escape w pasku i w panelu planu nie zamyka całego edytora. */
export const CV_COMMAND_ATTR = "data-cv-command";

export interface CvEditorCommandBarProps {
  controller: CvCommandController;
  onClose: () => void;
}

export function CvEditorCommandBar({ controller, onClose }: CvEditorCommandBarProps) {
  const [command, setCommand] = useState("");
  const fieldId = useId();
  const loading = controller.phase === "loading";
  const blocked = !controller.enabled || loading || controller.busy;
  const ready = command.trim().length >= 3;

  return (
    <form
      {...{ [CV_COMMAND_ATTR]: "" }}
      aria-label="Polecenie dla całego CV"
      className="space-y-1.5 border-b border-border bg-background px-3 py-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready && !blocked) controller.request({ command });
      }}
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        event.stopPropagation();
        event.preventDefault();
        if (controller.phase === "idle" || controller.phase === "message") onClose();
      }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <label
          htmlFor={fieldId}
          className="flex h-9 min-w-0 flex-1 basis-64 items-center gap-2 rounded-md border border-border bg-card px-2.5 focus-within:border-primary"
        >
          <Sparkles className="size-4 flex-none text-primary" aria-hidden />
          <span className="sr-only">Co asystent ma zmienić w całym CV</span>
          <input
            id={fieldId}
            type="text"
            value={command}
            maxLength={CV_COMMAND_MAX}
            disabled={blocked}
            autoFocus
            placeholder="Napisz, co zmienić w całym CV, np. „skróć do dwóch stron, zostaw wszystko o Kafce”"
            onChange={(event) => setCommand(event.target.value)}
            // `w-0` obok `flex-1`: bez jawnej szerokości minimum pola liczy się z długiego placeholdera.
            className="w-0 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
          />
        </label>
        <Button type="submit" size="sm" disabled={!ready || blocked}>
          {loading ? <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden /> : null}
          Przygotuj zmiany
        </Button>
        <Button
          type="button"
          size="icon-sm"
          variant="ghost"
          aria-label="Zamknij polecenie"
          disabled={controller.busy}
          onClick={onClose}
        >
          <X className="size-4" aria-hidden />
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-muted-foreground">Gotowe polecenia:</span>
        {CV_COMMAND_PRESETS.map((item) => (
          <Button
            key={item.preset}
            type="button"
            size="sm"
            variant="outline"
            className="h-6 px-2 text-xs"
            disabled={blocked}
            onClick={() => controller.request({ preset: item.preset })}
          >
            {item.label}
          </Button>
        ))}
      </div>
    </form>
  );
}
