"use client";

/** Pusty panel: pytania, które ludzie naprawdę zadali Jarvisowi na tym ekranie
 *  (`asked` w przewodniku ekranu). Zastępuje dymek ekranu — 714 pokazań,
 *  2 otwarcia przewodnika (23.09–06.11.2026). Klik wysyła pytanie. */

import { MessageCircleQuestion } from "lucide-react";

interface Props {
  questions: string[];
  disabled?: boolean;
  onAsk: (question: string) => void;
}

export function JarvisScreenQuestions({ questions, disabled = false, onAsk }: Props) {
  if (questions.length === 0) return null;
  return (
    <div className="rounded-lg border border-border px-3 py-2 text-left" data-testid="jarvis-screen-questions">
      <p className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
        <MessageCircleQuestion className="h-3.5 w-3.5 text-primary" aria-hidden />
        Na tym ekranie ludzie pytali
      </p>
      <ul className="mt-1 space-y-0.5">
        {questions.map((q) => (
          <li key={q}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onAsk(q)}
              className="w-full rounded-md px-1.5 py-1 text-left text-xs text-foreground hover:bg-muted disabled:opacity-50"
            >
              {q}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
