"use client";

/**
 * Karta przewodnika ekranu w panelu Jarvisa — treść z `GET /api/help/screens`,
 * bez wywołania modelu. Klik w zadanie wstawia do rozmowy gotową odpowiedź,
 * „Pokaż na ekranie” podświetla element (`HelpSpotlight`).
 */

import { Lightbulb, MousePointerClick } from "lucide-react";
import type { ScreenGuide, ScreenGuideTask } from "@/lib/jarvis/types";

interface Props {
  guide: ScreenGuide;
  onTask?: (task: ScreenGuideTask) => void;
  onShow?: (anchorId: string) => void;
  onAskOther?: () => void;
}

export function JarvisGuideCard({ guide, onTask, onShow, onAskOther }: Props) {
  return (
    <div className="rounded-xl border border-border bg-background p-3" data-testid="jarvis-guide-card">
      <p className="flex items-center gap-1.5 text-sm font-semibold">
        <Lightbulb className="h-4 w-4 text-primary" aria-hidden />
        {guide.title}
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{guide.what}</p>
      <p className="mt-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Najczęściej tutaj</p>
      <ul className="mt-1.5 space-y-1.5">
        {guide.tasks.map((task) => (
          <li key={task.q} className="flex items-start gap-1.5">
            <button
              type="button"
              onClick={() => onTask?.(task)}
              className="min-w-0 flex-1 rounded-lg border border-border px-2.5 py-1.5 text-left text-sm hover:bg-muted"
            >
              {task.q}
            </button>
            {task.anchor && (
              <button
                type="button"
                onClick={() => onShow?.(task.anchor as string)}
                className="shrink-0 rounded-lg border border-border p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label={`Pokaż na ekranie: ${task.q}`}
                title="Pokaż na ekranie"
              >
                <MousePointerClick className="h-4 w-4" aria-hidden />
              </button>
            )}
          </li>
        ))}
      </ul>
      {guide.pitfalls.length > 0 && (
        <div className="mt-3 rounded-lg bg-warning-muted px-2.5 py-2 text-xs text-warning-muted-foreground">
          <p className="font-medium">Uwaga</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {guide.pitfalls.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      {onAskOther && (
        <button type="button" onClick={onAskOther} className="mt-3 text-xs font-medium text-primary hover:underline">
          Zapytaj o coś innego
        </button>
      )}
    </div>
  );
}
