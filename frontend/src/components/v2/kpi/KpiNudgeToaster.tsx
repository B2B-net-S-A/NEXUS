"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { X, Sparkles, Clock, BarChart3 } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ──────────────────────────────────────────────────────────────────

export const KPI_NUDGE_EVENT = "nexus:kpi-nudge";

export interface KpiNudgePayload {
  notification_id: number | null;
  nudge_type: "praise_hit" | "remind_behind" | "eod_summary" | "streak_bonus";
  kpi_id: string;
  state: string;
  title: string;
  message: string;
  emoji: string;
  tone: "praise" | "remind" | "summary";
  variant: number;
  current?: number;
  target?: number;
  progress_pct?: number;
  avg_progress_pct?: number;
  deadline_hours_left?: number;
  sent_at: string;
}

interface ActiveToast extends KpiNudgePayload {
  localId: number;
}

// ── Styling per tone ───────────────────────────────────────────────────────

const TONE_STYLES: Record<
  KpiNudgePayload["tone"],
  { wrapper: string; accent: string; icon: React.ReactNode }
> = {
  praise: {
    wrapper:
      "bg-gradient-to-br from-emerald-50 to-green-100 border-emerald-300 " +
      "text-emerald-900 dark:from-emerald-900/40 dark:to-green-900/40 " +
      "dark:border-emerald-700 dark:text-emerald-100",
    accent: "text-emerald-600 dark:text-emerald-300",
    icon: <Sparkles className="w-5 h-5" />,
  },
  remind: {
    wrapper:
      "bg-gradient-to-br from-amber-50 to-orange-100 border-amber-300 " +
      "text-amber-900 dark:from-amber-900/40 dark:to-orange-900/40 " +
      "dark:border-amber-700 dark:text-amber-100",
    accent: "text-amber-600 dark:text-amber-300",
    icon: <Clock className="w-5 h-5" />,
  },
  summary: {
    wrapper:
      "bg-gradient-to-br from-sky-50 to-blue-100 border-sky-300 " +
      "text-sky-900 dark:from-sky-900/40 dark:to-blue-900/40 " +
      "dark:border-sky-700 dark:text-sky-100",
    accent: "text-sky-600 dark:text-sky-300",
    icon: <BarChart3 className="w-5 h-5" />,
  },
};

// Auto-dismiss (ms) per tone. `summary` = 0 → manual dismiss.
const AUTO_DISMISS_MS: Record<KpiNudgePayload["tone"], number> = {
  praise: 8000,
  remind: 15000,
  summary: 0,
};

// ── Component ──────────────────────────────────────────────────────────────

export function KpiNudgeToaster() {
  const [toasts, setToasts] = useState<ActiveToast[]>([]);
  const counterRef = useRef(0);

  const dismiss = useCallback((localId: number) => {
    setToasts((prev) => prev.filter((t) => t.localId !== localId));
  }, []);

  useEffect(() => {
    const onEvent = (ev: Event) => {
      const custom = ev as CustomEvent<KpiNudgePayload>;
      const payload = custom.detail;
      if (!payload || !payload.title) return;

      const localId = ++counterRef.current;
      const toast: ActiveToast = { ...payload, localId };
      setToasts((prev) => [...prev, toast]);

      const ttl = AUTO_DISMISS_MS[payload.tone] ?? 0;
      if (ttl > 0) {
        window.setTimeout(() => {
          setToasts((prev) => prev.filter((t) => t.localId !== localId));
        }, ttl);
      }
    };
    window.addEventListener(KPI_NUDGE_EVENT, onEvent as EventListener);
    return () => {
      window.removeEventListener(KPI_NUDGE_EVENT, onEvent as EventListener);
    };
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-20 right-4 z-[10000] flex flex-col gap-3 pointer-events-none max-w-sm">
      {toasts.map((toast) => {
        const style = TONE_STYLES[toast.tone] ?? TONE_STYLES.praise;
        return (
          <div
            key={toast.localId}
            role="status"
            aria-live="polite"
            className={cn(
              "flex items-start gap-3 px-4 py-3 rounded-2xl shadow-xl border-2",
              "animate-in slide-in-from-right-5 fade-in-0 duration-300",
              "pointer-events-auto",
              style.wrapper,
            )}
          >
            <div className={cn("flex-shrink-0 mt-0.5", style.accent)}>
              <span className="text-2xl leading-none select-none">
                {toast.emoji}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-bold leading-tight mb-0.5">
                {toast.title}
              </p>
              <p className="text-xs leading-snug opacity-90">{toast.message}</p>
              {typeof toast.progress_pct === "number" &&
                typeof toast.target === "number" &&
                toast.target > 0 && (
                  <div className="mt-2 h-1.5 rounded-full bg-black/10 dark:bg-white/10 overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all",
                        toast.tone === "praise"
                          ? "bg-emerald-500"
                          : toast.tone === "remind"
                            ? "bg-amber-500"
                            : "bg-sky-500",
                      )}
                      style={{
                        width: `${Math.min(100, Math.max(0, toast.progress_pct))}%`,
                      }}
                    />
                  </div>
                )}
            </div>
            <button
              onClick={() => dismiss(toast.localId)}
              aria-label="Zamknij"
              className="text-current opacity-50 hover:opacity-100 transition-opacity flex-shrink-0"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
