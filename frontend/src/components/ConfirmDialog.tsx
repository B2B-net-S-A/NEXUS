"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Inline confirm wrapper ────────────────────────────────────────────────────
// Usage:
//   <DeleteButton onConfirm={() => mutation.mutate(id)} />

interface DeleteButtonProps {
  onConfirm: () => void;
  label?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  className?: string;
  iconOnly?: boolean;
}

export function DeleteButton({
  onConfirm,
  label,
  confirmLabel = "Usuń",
  cancelLabel = "Anuluj",
  className,
  iconOnly = true,
}: DeleteButtonProps) {
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <span className="inline-flex items-center gap-1 text-xs">
        <span className="text-gray-500 mr-1">Na pewno?</span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onConfirm();
            setConfirming(false);
          }}
          className="px-2 py-0.5 bg-red-600 hover:bg-red-700 text-white rounded font-medium transition-colors"
        >
          {confirmLabel}
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setConfirming(false);
          }}
          className="px-2 py-0.5 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded font-medium transition-colors"
        >
          {cancelLabel}
        </button>
      </span>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        setConfirming(true);
      }}
      className={cn(
        "text-gray-400 hover:text-red-500 transition-colors",
        className
      )}
      title="Usuń"
    >
      {iconOnly ? <Trash2 className="w-4 h-4" /> : (label ?? "Usuń")}
    </button>
  );
}

// ── Inline confirm for any action ─────────────────────────────────────────────

interface ConfirmButtonProps {
  children: React.ReactNode;
  onConfirm: () => void;
  message?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  className?: string;
}

export function ConfirmButton({
  children,
  onConfirm,
  message = "Na pewno chcesz usunąć?",
  confirmLabel = "Usuń",
  cancelLabel = "Anuluj",
  className,
}: ConfirmButtonProps) {
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <span className="inline-flex items-center gap-1 text-xs">
        <span className="text-gray-500 mr-1">{message}</span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onConfirm();
            setConfirming(false);
          }}
          className="px-2 py-0.5 bg-red-600 hover:bg-red-700 text-white rounded font-medium transition-colors"
        >
          {confirmLabel}
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setConfirming(false);
          }}
          className="px-2 py-0.5 bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600 text-gray-600 dark:text-gray-300 rounded font-medium transition-colors"
        >
          {cancelLabel}
        </button>
      </span>
    );
  }

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        setConfirming(true);
      }}
      className={className}
    >
      {children}
    </button>
  );
}
