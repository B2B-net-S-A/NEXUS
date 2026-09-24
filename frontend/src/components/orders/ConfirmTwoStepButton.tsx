"use client";

import { useEffect, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Przycisk z potwierdzeniem w dwóch krokach — zamiast `window.confirm`.
 *
 * Natywny dialog zamraża automatyzację przeglądarki (klik leci w timeout,
 * a `navigate` odrzuca dialog, więc akcja się nie wykonuje) — audyt
 * 24.09.2026, N8. Pierwsze kliknięcie „uzbraja" przycisk i zmienia jego treść
 * na pytanie, drugie wykonuje akcję. Po `timeoutMs` bez drugiego kliknięcia
 * przycisk wraca do stanu wyjściowego.
 */
export function ConfirmTwoStepButton({
  onConfirm,
  children,
  confirmLabel,
  ariaLabel,
  confirmAriaLabel,
  title,
  className,
  armedClassName,
  disabled = false,
  timeoutMs = 4000,
}: {
  onConfirm: () => void;
  children: ReactNode;
  /** Treść przycisku po pierwszym kliknięciu (pytanie). */
  confirmLabel: ReactNode;
  ariaLabel?: string;
  confirmAriaLabel?: string;
  title?: string;
  className?: string;
  armedClassName?: string;
  disabled?: boolean;
  timeoutMs?: number;
}) {
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    if (!armed) return;
    const timer = window.setTimeout(() => setArmed(false), timeoutMs);
    return () => window.clearTimeout(timer);
  }, [armed, timeoutMs]);

  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={armed ? (confirmAriaLabel ?? ariaLabel) : ariaLabel}
      title={title}
      data-armed={armed ? "true" : undefined}
      onClick={() => {
        if (!armed) {
          setArmed(true);
          return;
        }
        setArmed(false);
        onConfirm();
      }}
      className={cn(className, armed && armedClassName)}
    >
      {armed ? confirmLabel : children}
    </button>
  );
}
