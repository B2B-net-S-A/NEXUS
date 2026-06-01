"use client";

import {
  ChangeEvent,
  FormEvent,
  KeyboardEvent,
  RefObject,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  MentionScope,
  useMentionableUsers,
} from "@/hooks/useMentionableUsers";
import { cn } from "@/lib/utils";
import type { ChatUserMini } from "@/types/job-chat";

interface MentionState {
  open: boolean;
  query: string;
  startIndex: number;
  highlightIdx: number;
}

const initialMentionState: MentionState = {
  open: false,
  query: "",
  startIndex: -1,
  highlightIdx: 0,
};

interface MentionTextareaProps {
  value: string;
  onChange: (value: string) => void;
  scope: MentionScope;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
  className?: string;
  onFocus?: (e: FormEvent<HTMLTextAreaElement>) => void;
  onBlur?: (e: FormEvent<HTMLTextAreaElement>) => void;
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  ariaLabel?: string;
  maxSuggestions?: number;
}

const MAX_SUGGESTIONS_DEFAULT = 6;

/**
 * Reusable textarea z @mention autocomplete. Eliminuje duplikację z
 * JobChatTab/CandidateChatTab (handwritten autocomplete) – używana też w
 * NotatkiTab kandydata i ScreeningNote editorze.
 *
 * Składnia mention: `@email@domena.pl ` (spacja po wstawieniu). To bezpośredni
 * format który backend (`mention_parser.py`) parsuje regex'em – zero migracji
 * danych, zero zmian formatu.
 *
 * onKeyDown jest pass-through gdy popup zamknięty – żeby chat mógł obsłużyć
 * Enter-to-submit. Gdy popup otwarty: Enter wybiera highlightIdx, Escape
 * zamyka, Strzałki nawigują (todo v2 – w v1 tylko Enter na pierwszym wyniku).
 */
export function MentionTextarea({
  value,
  onChange,
  scope,
  placeholder,
  rows = 3,
  disabled = false,
  className,
  onFocus,
  onBlur,
  onKeyDown,
  textareaRef,
  ariaLabel,
  maxSuggestions = MAX_SUGGESTIONS_DEFAULT,
}: MentionTextareaProps) {
  const innerRef = useRef<HTMLTextAreaElement | null>(null);
  const ref = textareaRef ?? innerRef;
  const [mention, setMention] = useState<MentionState>(initialMentionState);

  const { data: users = [] } = useMentionableUsers(scope);

  const filtered = useMemo(() => {
    if (!mention.open) return [];
    const q = mention.query;
    return users
      .filter(
        (m) =>
          m.email.toLowerCase().includes(q) ||
          (m.name?.toLowerCase().includes(q) ?? false),
      )
      .slice(0, maxSuggestions);
  }, [users, mention, maxSuggestions]);

  useEffect(() => {
    if (mention.open && mention.highlightIdx >= filtered.length) {
      setMention((s) => ({ ...s, highlightIdx: 0 }));
    }
  }, [filtered.length, mention.highlightIdx, mention.open]);

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    const caret = e.target.selectionStart ?? val.length;
    onChange(val);

    // Detekcja "@..." na lewo od caret bez spacji (mirror logiki z JobChatTab).
    const before = val.slice(0, caret);
    const atPos = before.lastIndexOf("@");
    if (atPos === -1) {
      setMention(initialMentionState);
      return;
    }
    const token = before.slice(atPos + 1);
    if (!token || /\s/.test(token)) {
      setMention(initialMentionState);
      return;
    }
    setMention({
      open: true,
      query: token.toLowerCase(),
      startIndex: atPos,
      highlightIdx: 0,
    });
  };

  const insertMention = (m: ChatUserMini) => {
    const ta = ref.current;
    if (mention.startIndex < 0 || !ta) return;
    const before = value.slice(0, mention.startIndex);
    const afterCaret = value.slice(ta.selectionStart ?? value.length);
    const insertion = `@${m.email} `;
    const next = before + insertion + afterCaret;
    onChange(next);
    setMention(initialMentionState);
    requestAnimationFrame(() => {
      const taNow = ref.current;
      if (!taNow) return;
      const newPos = (before + insertion).length;
      taNow.focus();
      taNow.setSelectionRange(newPos, newPos);
    });
  };

  const handleKeyDownInner = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (mention.open) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setMention((s) => ({
          ...s,
          highlightIdx: Math.min(s.highlightIdx + 1, filtered.length - 1),
        }));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setMention((s) => ({
          ...s,
          highlightIdx: Math.max(s.highlightIdx - 1, 0),
        }));
        return;
      }
      if (e.key === "Enter" && filtered.length > 0) {
        e.preventDefault();
        insertMention(filtered[mention.highlightIdx] ?? filtered[0]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMention(initialMentionState);
        return;
      }
    }
    onKeyDown?.(e);
  };

  return (
    <div className="relative">
      {mention.open && filtered.length > 0 && (
        <div className="absolute bottom-full left-0 right-0 mb-1 bg-card dark:bg-card border border-border dark:border-border rounded-lg shadow-lg z-20 overflow-hidden">
          {filtered.map((m, idx) => (
            <button
              key={m.id}
              type="button"
              onMouseDown={(e) => {
                e.preventDefault();
                insertMention(m);
              }}
              className={cn(
                "w-full flex items-center gap-2 px-3 py-2 text-left text-sm",
                idx === mention.highlightIdx
                  ? "bg-primary/10 dark:bg-primary/30"
                  : "hover:bg-muted dark:hover:bg-muted",
              )}
            >
              <span className="font-medium">{m.name}</span>
              <span className="text-xs text-muted-foreground">{m.email}</span>
              {m.role && (
                <span className="ml-auto text-[10px] uppercase text-muted-foreground">
                  {m.role}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      <textarea
        ref={ref}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDownInner}
        onFocus={onFocus}
        onBlur={onBlur}
        placeholder={placeholder}
        rows={rows}
        disabled={disabled}
        aria-label={ariaLabel}
        className={cn(
          "w-full resize-none rounded border border-border dark:border-border bg-card dark:bg-card px-3 py-2 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring disabled:opacity-50",
          className,
        )}
      />
    </div>
  );
}
