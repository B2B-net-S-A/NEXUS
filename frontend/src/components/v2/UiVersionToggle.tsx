"use client";

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { readUiFlagClient, setUiFlagClient, type UiVersion } from "@/lib/ui-flag";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

/**
 * Client-facing opt-in banner for v2 redesign.
 * Mount inline at the top of settings pages. Works in both v1 and v2 shells.
 */
export function UiVersionToggle() {
  const [ui, setUi] = useState<UiVersion | "loading">("loading");

  useEffect(() => {
    setUi(readUiFlagClient());
  }, []);

  const flip = (next: UiVersion) => {
    setUiFlagClient(next);
    window.location.reload();
  };

  if (ui === "loading") {
    return null;
  }

  return (
    <div
      className={
        ui === "v2"
          ? "rounded-v2-m border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-surface))] p-4 mb-4 flex items-start gap-3"
          : "rounded-xl border border-blue-200 dark:border-blue-800 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20 p-4 mb-4 flex items-start gap-3"
      }
    >
      <div
        className={
          ui === "v2"
            ? "w-10 h-10 rounded-v2-s bg-[hsl(var(--accent-soft))] flex items-center justify-center shrink-0"
            : "w-10 h-10 rounded-xl bg-white dark:bg-gray-800 flex items-center justify-center shrink-0"
        }
      >
        <Sparkles
          className={ui === "v2" ? "h-5 w-5 text-[hsl(var(--accent))]" : "h-5 w-5 text-blue-600"}
        />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <h3
            className={
              ui === "v2"
                ? "font-display font-bold text-sm text-[hsl(var(--text-title))]"
                : "font-bold text-sm text-gray-900 dark:text-gray-100"
            }
          >
            Dynaminds UI (v2)
          </h3>
          <Badge variant={ui === "v2" ? "burgundy" : "neutral"} size="sm" uppercase>
            {ui === "v2" ? "Aktywne" : "Wyłączone"}
          </Badge>
        </div>
        <p
          className={
            ui === "v2"
              ? "text-xs text-[hsl(var(--text-body))] mt-1 max-w-2xl"
              : "text-xs text-gray-700 dark:text-gray-300 mt-1 max-w-2xl"
          }
        >
          Nowy design Nexusa bazujący na brandbooku Dynaminds — Deep Plum sidebar,
          Warm Cream canvas, Burgundy akcenty, Poppins + Inter. W trakcie rozwoju —
          v1 pozostaje domyślna do czasu stabilizacji v2.
        </p>
        <div className="flex items-center gap-2 mt-3">
          {ui === "v2" ? (
            <Button size="sm" variant="outline" onClick={() => flip("v1")}>
              Wróć do klasycznego UI (v1)
            </Button>
          ) : (
            <button
              onClick={() => flip("v2")}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold transition-colors"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Wypróbuj nowy design
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
