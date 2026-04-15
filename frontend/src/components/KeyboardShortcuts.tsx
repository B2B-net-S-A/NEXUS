"use client";

import { useEffect, useState, useCallback } from "react";
import { X, Keyboard } from "lucide-react";

// ── Shortcuts help modal ──────────────────────────────────────────────────────

const SHORTCUTS = [
  { keys: ["n"], description: "Nowy kandydat" },
  { keys: ["j"], description: "Nowa oferta pracy" },
  { keys: ["/"], description: "Szukaj" },
  { keys: ["?"], description: "Pokaż skróty klawiszowe" },
  { keys: ["Esc"], description: "Zamknij modal / anuluj" },
  { keys: ["⌘", "K"], description: "Globalne wyszukiwanie" },
  { keys: ["⌘", "N"], description: "Szybki nowy kandydat" },
  { keys: ["⌘", "J"], description: "Szybka nowa oferta" },
  { keys: ["↑ / ↓"], description: "Nawigacja w wynikach wyszukiwania" },
  { keys: ["Enter"], description: "Wybierz wynik wyszukiwania" },
];

function ShortcutKey({ k }: { k: string }) {
  return (
    <kbd className="inline-flex items-center justify-center min-w-[28px] h-7 px-1.5 bg-gray-100 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded text-xs font-mono font-semibold text-gray-700 dark:text-gray-200 shadow-sm">
      {k}
    </kbd>
  );
}

function ShortcutsModal({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 bg-black/50 z-[100] flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl w-full max-w-md">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <Keyboard className="w-5 h-5 text-blue-500" />
            <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Skróty klawiszowe</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6 space-y-3">
          {SHORTCUTS.map((shortcut, i) => (
            <div key={i} className="flex items-center justify-between gap-4">
              <span className="text-sm text-gray-700 dark:text-gray-300">{shortcut.description}</span>
              <div className="flex items-center gap-1 flex-shrink-0">
                {shortcut.keys.map((k, j) => (
                  <span key={j} className="flex items-center gap-1">
                    <ShortcutKey k={k} />
                    {j < shortcut.keys.length - 1 && (
                      <span className="text-xs text-gray-400 dark:text-gray-500">+</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="px-6 pb-4 text-xs text-gray-400 dark:text-gray-500">
          Skróty są nieaktywne gdy kursor jest w polu tekstowym.
        </div>
      </div>
    </div>
  );
}

// ── Hook: keyboard shortcuts ──────────────────────────────────────────────────

function isInputActive(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  const tag = el.tagName.toLowerCase();
  return (
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    (el as HTMLElement).isContentEditable
  );
}

interface UseKeyboardShortcutsOptions {
  onNewCandidate: () => void;
  onNewJob: () => void;
  onFocusSearch: () => void;
}

export function useKeyboardShortcuts({
  onNewCandidate,
  onNewJob,
  onFocusSearch,
}: UseKeyboardShortcutsOptions) {
  const [showHelp, setShowHelp] = useState(false);

  const handler = useCallback(
    (e: KeyboardEvent) => {
      // Cmd+N → new candidate
      if ((e.metaKey || e.ctrlKey) && e.key === "n") {
        e.preventDefault();
        onNewCandidate();
        return;
      }
      // Cmd+J → new job
      if ((e.metaKey || e.ctrlKey) && e.key === "j") {
        e.preventDefault();
        onNewJob();
        return;
      }
      // Never fire bare shortcuts from other Cmd/Ctrl combos
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isInputActive()) return;

      switch (e.key) {
        case "n":
          e.preventDefault();
          onNewCandidate();
          break;
        case "j":
          e.preventDefault();
          onNewJob();
          break;
        case "/":
          e.preventDefault();
          onFocusSearch();
          break;
        case "?":
          e.preventDefault();
          setShowHelp((v) => !v);
          break;
        default:
          break;
      }
    },
    [onNewCandidate, onNewJob, onFocusSearch],
  );

  useEffect(() => {
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [handler]);

  return { showHelp, setShowHelp };
}

// ── ShortcutsHelpModal export ─────────────────────────────────────────────────
export { ShortcutsModal };
