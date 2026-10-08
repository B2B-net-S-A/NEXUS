"use client";

import {
  ChangeEvent,
  FormEvent,
  KeyboardEvent,
  RefObject,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  MentionScope,
  useMentionableUsers,
} from "@/hooks/useMentionableUsers";
import {
  choosePopupPlacement,
  findMentionToken,
  matchMentionUsers,
  type PopupPlacement,
} from "@/lib/mention-autocomplete";
import { cn } from "@/lib/utils";
import { ROLE_LABELS, type UserRole } from "@/store/auth";
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
  /** Klasy opakowania (pole i lista) — np. gdy pole stoi w wierszu flex. */
  wrapperClassName?: string;
  onFocus?: (e: FormEvent<HTMLTextAreaElement>) => void;
  onBlur?: (e: FormEvent<HTMLTextAreaElement>) => void;
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  ariaLabel?: string;
  maxSuggestions?: number;
}

const MAX_SUGGESTIONS_DEFAULT = 6;
const POPUP_DESIRED_HEIGHT = 264;

/** Miejsce nad i pod polem, którego nie ucina okno ani przewijany przodek. */
function measurePopupSpace(field: HTMLElement): { above: number; below: number } {
  const rect = field.getBoundingClientRect();
  let top = 0;
  let bottom = window.innerHeight;
  for (let node = field.parentElement; node; node = node.parentElement) {
    if (getComputedStyle(node).overflowY === "visible") continue;
    const clip = node.getBoundingClientRect();
    top = Math.max(top, clip.top);
    bottom = Math.min(bottom, clip.bottom);
  }
  return { above: rect.top - top, below: bottom - rect.bottom };
}

/**
 * Pole tekstowe z podpowiedzią osób po „@” — notatki i czaty.
 *
 * Do tekstu trafia `@adres@domena.pl ` (spacja po wstawieniu): ten format
 * rozpoznaje backend (`mention_parser.py`), a przy wyświetlaniu zamienia się
 * na imię i nazwisko (`renderWithMentions`).
 *
 * Lista otwiera się po samym „@”, szuka po imieniu, nazwisku i adresie (bez
 * polskich znaków) i staje po tej stronie pola, gdzie jest miejsce. Gdy jest
 * otwarta: Enter i Tab wybierają, strzałki zmieniają osobę, Escape zamyka;
 * w pozostałych przypadkach `onKeyDown` idzie do rodzica (Enter wysyła czat).
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
  wrapperClassName,
}: MentionTextareaProps) {
  const innerRef = useRef<HTMLTextAreaElement | null>(null);
  const ref = textareaRef ?? innerRef;
  const [mention, setMention] = useState<MentionState>(initialMentionState);

  const usersQuery = useMentionableUsers(scope);
  const users = usersQuery.data;

  const filtered = useMemo(
    () =>
      mention.open && users
        ? matchMentionUsers(users, mention.query, maxSuggestions)
        : [],
    [users, mention.open, mention.query, maxSuggestions],
  );

  // Co pokazać zamiast osób: lista nie może milczeć, gdy się wczytuje, nie
  // wczytała albo nikt nie pasuje. Tekst ze spacją, do którego nikt nie
  // pasuje, to zwykłe zdanie po „@” — wtedy nie pokazujemy nic.
  const plainWord = !/\s/.test(mention.query) && !/^\d/.test(mention.query);
  const status: "loading" | "error" | "empty" | null = !mention.open
    ? null
    : usersQuery.isPending
      ? "loading"
      : usersQuery.isError
        ? "error"
        : filtered.length === 0 && plainWord
          ? "empty"
          : null;
  const popupVisible = mention.open && (filtered.length > 0 || status !== null);

  const [placement, setPlacement] = useState<PopupPlacement>({
    side: "below",
    maxHeight: POPUP_DESIRED_HEIGHT,
  });
  useLayoutEffect(() => {
    if (!popupVisible || !ref.current) return;
    const space = measurePopupSpace(ref.current);
    setPlacement(
      choosePopupPlacement(space.above, space.below, POPUP_DESIRED_HEIGHT),
    );
  }, [popupVisible, ref]);

  // Rodzic wyczyścił albo podmienił tekst (Enter wysłał wiadomość) — lista
  // nie może zostać nad pustym polem ze starym zapytaniem.
  useEffect(() => {
    if (mention.open && value[mention.startIndex] !== "@") {
      setMention(initialMentionState);
    }
  }, [value, mention.open, mention.startIndex]);

  useEffect(() => {
    if (mention.open && mention.highlightIdx >= filtered.length) {
      setMention((s) => ({ ...s, highlightIdx: 0 }));
    }
  }, [filtered.length, mention.highlightIdx, mention.open]);

  const handleChange = (e: ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    const caret = e.target.selectionStart ?? val.length;
    onChange(val);

    const token = findMentionToken(val, caret);
    if (!token) {
      setMention(initialMentionState);
      return;
    }
    setMention({
      open: true,
      query: token.query,
      startIndex: token.start,
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
      if (e.key === "ArrowDown" && filtered.length > 0) {
        e.preventDefault();
        setMention((s) => ({
          ...s,
          highlightIdx: Math.min(s.highlightIdx + 1, filtered.length - 1),
        }));
        return;
      }
      if (e.key === "ArrowUp" && filtered.length > 0) {
        e.preventDefault();
        setMention((s) => ({
          ...s,
          highlightIdx: Math.max(s.highlightIdx - 1, 0),
        }));
        return;
      }
      if ((e.key === "Enter" || e.key === "Tab") && filtered.length > 0) {
        e.preventDefault();
        insertMention(filtered[mention.highlightIdx] ?? filtered[0]);
        return;
      }
      if (e.key === "Escape" && popupVisible) {
        e.preventDefault();
        setMention(initialMentionState);
        return;
      }
    }
    onKeyDown?.(e);
  };

  return (
    <div className={cn("relative", wrapperClassName)}>
      {popupVisible && (
        <div
          role="listbox"
          aria-label="Osoby do oznaczenia"
          // Kliknięcie w listę nie może zabrać fokusu z pola (zamknęłoby ją).
          onMouseDown={(e) => e.preventDefault()}
          style={{ maxHeight: placement.maxHeight }}
          className={cn(
            "absolute left-0 right-0 z-30 min-w-56 overflow-y-auto rounded-lg border border-border bg-card shadow-lg",
            placement.side === "above" ? "bottom-full mb-1" : "top-full mt-1",
          )}
        >
          {filtered.map((m, idx) => (
            <button
              key={m.id}
              type="button"
              role="option"
              aria-selected={idx === mention.highlightIdx}
              onMouseDown={(e) => {
                e.preventDefault();
                insertMention(m);
              }}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-2 text-left text-sm",
                idx === mention.highlightIdx ? "bg-primary/10" : "hover:bg-muted",
              )}
            >
              <span className="shrink-0 font-medium">{m.name}</span>
              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                {m.email}
              </span>
              {m.role && (
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {ROLE_LABELS[m.role as UserRole] ?? m.role}
                </span>
              )}
            </button>
          ))}
          {status === "loading" && (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              Wczytuję listę osób…
            </p>
          )}
          {status === "error" && (
            <p role="alert" className="px-3 py-2 text-xs text-muted-foreground">
              Nie udało się wczytać listy osób.{" "}
              <button
                type="button"
                className="font-medium text-primary hover:underline"
                onMouseDown={(e) => {
                  e.preventDefault();
                  void usersQuery.refetch();
                }}
              >
                Spróbuj ponownie
              </button>
            </p>
          )}
          {status === "empty" && (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              Nie ma osoby pasującej do „{mention.query}”.
            </p>
          )}
        </div>
      )}
      <textarea
        ref={ref}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDownInner}
        onFocus={onFocus}
        onBlur={(e) => {
          setMention(initialMentionState);
          onBlur?.(e);
        }}
        placeholder={placeholder}
        rows={rows}
        disabled={disabled}
        aria-label={ariaLabel}
        className={cn(
          "w-full resize-none rounded border border-border dark:border-border bg-card dark:bg-card px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring disabled:opacity-50",
          className,
        )}
      />
    </div>
  );
}
