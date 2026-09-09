"use client";

import { createContext, useContext, useState, useCallback, useMemo, useRef, useEffect } from "react";
import { X, CheckCircle, AlertCircle, Undo2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useThemeStore } from "@/store/theme";

// ── Types ─────────────────────────────────────────────────────────────────────

type ToastType = "success" | "error" | "action";

interface ActionToastOptions {
  actionLabel: string;
  onAction: () => void | Promise<void>;
  // Visible window for the action button. Defaults to 10 seconds — matches
  // the "Cofnij wysyłkę emaila" use case (the full undo window server-side
  // is 15 minutes, but the toast only prompts for the first few seconds).
  durationMs?: number;
}

interface Toast {
  id: number;
  message: string;
  type: ToastType;
  actionLabel?: string;
  onAction?: () => void | Promise<void>;
}

interface ToastContextValue {
  showToast: (message: string, type?: ToastType) => void;
  showSuccess: (message: string) => void;
  showError: (message: string) => void;
  showActionToast: (message: string, options: ActionToastOptions) => void;
}

// ── Context ───────────────────────────────────────────────────────────────────

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counterRef = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  useEffect(() => {
    const activeTimers = timers.current;
    return () => {
      for (const timer of activeTimers.values()) clearTimeout(timer);
      activeTimers.clear();
    };
  }, []);
  const scheduleDismiss = useCallback((id: number, durationMs: number) => {
    timers.current.set(id, setTimeout(() => {
      timers.current.delete(id);
      setToasts(prev => prev.filter(t => t.id !== id));
    }, durationMs));
  }, []);
  // In game mode, success toasts get a cheerful emoji (wording unchanged).
  const kidsMode = useThemeStore((s) => s.kidsMode);

  const showToast = useCallback((message: string, type: ToastType = "success") => {
    const id = ++counterRef.current;
    setToasts((prev) => [...prev, { id, message, type }]);
    // Błędy muszą zdążyć być przeczytane — przy 3 s komunikat znikał zanim
    // user spojrzał (klik "Generuj CV" wyglądał wtedy jak martwy przycisk).
    const durationMs = type === "error" ? 8000 : 3000;
    scheduleDismiss(id, durationMs);
  }, [scheduleDismiss]);

  const showSuccess = useCallback((message: string) => showToast(message, "success"), [showToast]);
  const showError = useCallback((message: string) => showToast(message, "error"), [showToast]);

  const showActionToast = useCallback(
    (message: string, options: ActionToastOptions) => {
      const id = ++counterRef.current;
      const durationMs = options.durationMs ?? 10_000;
      setToasts((prev) => [
        ...prev,
        {
          id,
          message,
          type: "action",
          actionLabel: options.actionLabel,
          onAction: options.onAction,
        },
      ]);
      scheduleDismiss(id, durationMs);
    },
    [scheduleDismiss]
  );

  // Wartość kontekstu MUSI być memoizowana. Provider siedzi nad całą aplikacją
  // i re-renderuje się DWA RAZY na każdy toast (dodanie + usunięcie przez
  // setTimeout). Świeży literał obiektu przy każdym renderze unieważnia kontekst
  // u wszystkich ~99 konsumentów useToast() — w tym u list wirtualizowanych
  // (CandidatesListV2, KanbanBoardV2) — więc lista re-renderuje się rekruterowi
  // pod palcami 3 s po akcji masowej, bez żadnego jego udziału.
  // Gorszy przypadek: konsument, który trzyma cały obiekt kontekstu w tablicy
  // zależności useEffect i woła z niego showError (InsightsView) — zmiana
  // tożsamości obiektu ponawia efekt, efekt pokazuje toast, toast zmienia
  // tożsamość obiektu: pętla, która sama się napędza.
  // Wszystkie cztery funkcje są już stabilne przez useCallback, więc to memo
  // nie unieważni się nigdy.
  const value = useMemo<ToastContextValue>(
    () => ({ showToast, showSuccess, showError, showActionToast }),
    [showToast, showSuccess, showError, showActionToast]
  );

  const dismiss = (id: number) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const handleAction = async (toast: Toast) => {
    if (!toast.onAction) return;
    try {
      await toast.onAction();
    } finally {
      dismiss(toast.id);
    }
  };

  return (
    <ToastContext.Provider value={value}>
      {children}

      {/* Toast container */}
      <div className="fixed bottom-4 right-4 z-9999 flex flex-col gap-2 pointer-events-none">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role={toast.type === "error" ? "alert" : "status"}
            aria-live={toast.type === "error" ? "assertive" : "polite"}
            aria-atomic="true"
            className={cn(
              "flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg border text-sm font-medium pointer-events-auto",
              "animate-in slide-in-from-right-5 fade-in-0 duration-200",
              toast.type === "success" &&
                "bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-900/40 dark:border-emerald-700 dark:text-emerald-200",
              toast.type === "error" &&
                "bg-destructive/10 border-destructive/20 text-red-800 dark:bg-red-900/40 dark:border-red-700 dark:text-red-200",
              toast.type === "action" &&
                "bg-primary/10 border-primary/20 text-primary dark:bg-primary/40 dark:border-primary/90 dark:text-primary"
            )}
          >
            {toast.type === "success" && (
              <CheckCircle
                aria-hidden="true"
                className="w-4 h-4 text-emerald-500 shrink-0"
              />
            )}
            {toast.type === "error" && (
              <AlertCircle
                aria-hidden="true"
                className="w-4 h-4 text-destructive shrink-0"
              />
            )}
            {toast.type === "action" && (
              <Undo2
                aria-hidden="true"
                className="w-4 h-4 text-primary shrink-0"
              />
            )}
            <span className="flex-1">
              {kidsMode && toast.type === "success" ? `🎉 ${toast.message}` : toast.message}
            </span>
            {toast.type === "action" && toast.actionLabel && (
              <button
                type="button"
                onClick={() => handleAction(toast)}
                className="inline-flex min-h-11 min-w-11 items-center justify-center px-2 text-primary dark:text-primary font-semibold underline underline-offset-2 hover:opacity-80 transition-opacity whitespace-nowrap"
              >
                {toast.actionLabel}
              </button>
            )}
            <button
              type="button"
              onClick={() => dismiss(toast.id)}
              aria-label="Zamknij powiadomienie"
              className="ml-1 inline-flex min-h-11 min-w-11 items-center justify-center text-current opacity-50 hover:opacity-100 transition-opacity"
            >
              <X aria-hidden="true" className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
