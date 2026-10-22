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

import { warsawToday } from "@/lib/warsaw-date";
import {
  MentionScope,
  useMentionableUsers,
} from "@/hooks/useMentionableUsers";
import {
  chooseCaretPlacement,
  choosePopupPlacement,
  findMentionToken,
  matchMentionUsers,
  type PopupPlacement,
} from "@/lib/mention-autocomplete";
import { textareaFitHeight } from "@/lib/textarea-autogrow";
import { caretOffsetTop, contentScrollHeight } from "@/lib/textarea-mirror";
import { useElementWidth } from "@/lib/use-element-width";
import { cn } from "@/lib/utils";
import { ROLE_LABELS, type UserRole } from "@/store/auth";
import type { ChatUserMini } from "@/types/job-chat";

import {
  absenceShortText,
  insertAfterMention,
  substituteHint,
  substituteHintText,
} from "./mention-absence";

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
  /** Pole rośnie z tekstem od `rows` do tylu linii, dalej przewija się w środku. */
  maxRows?: number;
  /**
   * `false` = wysokość zostaje przy `rows` i klasach: czat (lista wiadomości
   * trzyma się dołu tylko przy nowej wiadomości, więc rosnące pole wypychałoby
   * ostatnie poza widok) i pole, które wypełnia okno.
   */
  autoGrow?: boolean;
  disabled?: boolean;
  className?: string;
  /** Klasy opakowania (pole i lista) — np. gdy pole stoi w wierszu flex. */
  wrapperClassName?: string;
  onFocus?: (e: FormEvent<HTMLTextAreaElement>) => void;
  onBlur?: (e: FormEvent<HTMLTextAreaElement>) => void;
  onKeyDown?: (e: KeyboardEvent<HTMLTextAreaElement>) => void;
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  ariaLabel?: string;
  ariaDescribedBy?: string;
  maxSuggestions?: number;
}

const MAX_SUGGESTIONS_DEFAULT = 6;
const MAX_ROWS_DEFAULT = 10;
const POPUP_DESIRED_HEIGHT = 264;
/** Odstęp listy od krawędzi pola albo linii z „@” (jak `mt-1` / `mb-1`). */
const POPUP_EDGE_GAP = 4;
/** Powyżej tylu linii wysokości lista staje przy linii z „@”, nie przy krawędzi pola. */
const CARET_ANCHOR_ROWS = 3;

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
 *
 * Pole rośnie z tekstem (12.10.2026): od `rows` do `maxRows` linii. W polu
 * wyższym niż trzy linie lista staje przy linii z „@” — nad całym polem
 * byłaby daleko od kursora, a w dużym oknie notatki ucięta.
 *
 * Nieobecni (17.10.2026, moduł urlopów): przy osobie nieobecnej dziś lista
 * pokazuje „nieobecność do pt 23.10”, a po oznaczeniu takiej osoby z zastępcą
 * pod polem stoi podpowiedź „Oznaczyć też zastępcę?”. Bez modułu urlopów albo
 * przy awarii zapytania pole działa jak wcześniej.
 */
export function MentionTextarea({
  value,
  onChange,
  scope,
  placeholder,
  rows = 3,
  maxRows = MAX_ROWS_DEFAULT,
  autoGrow = true,
  disabled = false,
  className,
  onFocus,
  onBlur,
  onKeyDown,
  textareaRef,
  ariaLabel,
  ariaDescribedBy,
  maxSuggestions = MAX_SUGGESTIONS_DEFAULT,
  wrapperClassName,
}: MentionTextareaProps) {
  const innerRef = useRef<HTMLTextAreaElement | null>(null);
  const ref = textareaRef ?? innerRef;
  const [mention, setMention] = useState<MentionState>(initialMentionState);

  // Opakowanie ma szerokość pola (`w-full`) — po zmianie szerokości tekst
  // zawija się inaczej i wysokość trzeba policzyć od nowa.
  const [wrapper, setWrapper] = useState<HTMLDivElement | null>(null);
  const width = useElementWidth(wrapper);
  useLayoutEffect(() => {
    const field = ref.current;
    if (!field) return;
    const style = autoGrow ? getComputedStyle(field) : null;
    const fit = style
      ? textareaFitHeight(
          {
            scrollHeight: contentScrollHeight(field, width),
            lineHeight: parseFloat(style.lineHeight),
            padding: parseFloat(style.paddingTop) + parseFloat(style.paddingBottom),
            // Z kroju, nie z `offsetHeight − clientHeight`: w ukrytym panelu
            // oba są zerem, a pole ma wrócić z dobrą wysokością.
            border:
              (parseFloat(style.borderTopWidth) || 0) + (parseFloat(style.borderBottomWidth) || 0),
          },
          maxRows,
        )
      : null;
    field.style.height = fit ? `${fit.height}px` : "";
    field.style.overflowY = fit ? (fit.scroll ? "auto" : "hidden") : "";
  }, [ref, value, rows, maxRows, autoGrow, width]);

  const usersQuery = useMentionableUsers(scope, { withAbsences: true });
  const users = usersQuery.data;
  const absences = usersQuery.absences;
  const today = warsawToday();
  // Osoba, przy której wstawieniu pole podpowiada zastępcę.
  const [hintFor, setHintFor] = useState<number | null>(null);

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
    const field = ref.current;
    if (!popupVisible || !field) return;
    const space = measurePopupSpace(field);
    const style = getComputedStyle(field);
    const lineHeight = parseFloat(style.lineHeight);
    const tall =
      field.clientHeight >
      lineHeight * CARET_ANCHOR_ROWS + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    setPlacement(
      tall
        ? chooseCaretPlacement(
            space.above,
            space.below,
            // Opakowanie bywa o kilka px wyższe niż pole (linia bazowa pola
            // `inline-block`), a lista jest pozycjonowana względem opakowania.
            wrapper?.offsetHeight || field.offsetHeight,
            caretOffsetTop(field, mention.startIndex),
            lineHeight,
            POPUP_DESIRED_HEIGHT,
          )
        : choosePopupPlacement(space.above, space.below, POPUP_DESIRED_HEIGHT),
    );
  }, [popupVisible, ref, wrapper, mention.startIndex]);

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
    if (absences?.get(m.id)?.substitute_user_id) setHintFor(m.id);
    requestAnimationFrame(() => {
      const taNow = ref.current;
      if (!taNow) return;
      const newPos = (before + insertion).length;
      taNow.focus();
      taNow.setSelectionRange(newPos, newPos);
    });
  };

  const hint =
    hintFor != null && users && absences
      ? substituteHint(value, hintFor, users, absences)
      : null;

  const addSubstitute = () => {
    if (!hint) return;
    const next = insertAfterMention(value, hint.person.email, hint.substitute.email);
    onChange(next.text);
    setHintFor(null);
    requestAnimationFrame(() => {
      const taNow = ref.current;
      if (!taNow) return;
      taNow.focus();
      taNow.setSelectionRange(next.caret, next.caret);
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
    <div ref={setWrapper} className={cn("relative", wrapperClassName)}>
      {popupVisible && (
        <div
          role="listbox"
          aria-label="Osoby do oznaczenia"
          // Kliknięcie w listę nie może zabrać fokusu z pola (zamknęłoby ją).
          onMouseDown={(e) => e.preventDefault()}
          style={{
            maxHeight: placement.maxHeight,
            ...(placement.offset == null
              ? null
              : placement.side === "above"
                ? { bottom: placement.offset + POPUP_EDGE_GAP }
                : { top: placement.offset + POPUP_EDGE_GAP }),
          }}
          className={cn(
            "absolute left-0 right-0 z-30 min-w-56 overflow-y-auto rounded-lg border border-border bg-card shadow-lg",
            placement.offset != null
              ? null
              : placement.side === "above"
                ? "bottom-full mb-1"
                : "top-full mt-1",
          )}
        >
          {filtered.map((m, idx) => {
            const absence = absences?.get(m.id);
            return (
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
                {absence ? (
                  <span
                    data-testid="mention-absence"
                    title={
                      absence.substitute_name
                        ? `${absenceShortText(absence, today)} · zastępuje ${absence.substitute_name}`
                        : absenceShortText(absence, today)
                    }
                    className="shrink-0 rounded-full bg-warning-muted px-1.5 text-[10px] font-medium leading-4 text-warning-muted-foreground"
                  >
                    {absenceShortText(absence, today)}
                  </span>
                ) : null}
                {m.role && (
                  <span className="shrink-0 text-[10px] text-muted-foreground">
                    {ROLE_LABELS[m.role as UserRole] ?? m.role}
                  </span>
                )}
              </button>
            );
          })}
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
        aria-describedby={ariaDescribedBy}
        className={cn(
          "w-full resize-none rounded border border-border dark:border-border bg-card dark:bg-card px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring disabled:opacity-50",
          className,
        )}
      />
      {/* Pod polem, gdy lista jest zamknięta — otwarta liczy miejsce od opakowania. */}
      {hint && !popupVisible ? (
        <div
          role="status"
          data-testid="mention-substitute-hint"
          className="mt-1 flex shrink-0 flex-wrap items-center gap-x-2 gap-y-0.5 rounded-md bg-warning-muted px-2 py-1 text-xs text-warning-muted-foreground"
        >
          <span className="min-w-0">{substituteHintText(hint, today)}</span>
          <button
            type="button"
            // Klik nie zabiera fokusu z pola.
            onMouseDown={(e) => e.preventDefault()}
            onClick={addSubstitute}
            className="font-medium text-primary hover:underline"
          >
            Oznacz zastępcę
          </button>
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setHintFor(null)}
            className="text-muted-foreground hover:underline"
          >
            Nie
          </button>
        </div>
      ) : null}
    </div>
  );
}
