"use client";

/**
 * Panel rozmowy z Jarvisem — czysto prezentacyjny (dane i akcje z propsów),
 * więc renderuje się też w publicznym harnessie `/preview/jarvis` bez sieci.
 *
 * Pływa przy maskotce i NIE blokuje ekranu pod spodem (bez nakładki), żeby
 * dało się pracować i rozmawiać naraz. Na telefonie zajmuje cały ekran.
 */

import { useEffect, useRef } from "react";
import { ArrowLeft, History, MessageSquarePlus, Palette, Send, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type {
  JarvisAccent,
  JarvisAction,
  JarvisCharacterId,
  JarvisConversationSummary,
  JarvisItem,
  JarvisMood,
} from "@/lib/jarvis/types";
import { JarvisCharacter } from "./characters/JarvisCharacter";
import { JarvisMessageList } from "./JarvisMessageList";

export const JARVIS_MAX_MESSAGE = 4000;

export interface JarvisPanelProps {
  name: string;
  character: JarvisCharacterId;
  accent: JarvisAccent;
  mood: JarvisMood;
  view: "chat" | "history";
  items: JarvisItem[];
  thinking: boolean;
  streaming: boolean;
  draft: string;
  suggestions: string[];
  conversations?: JarvisConversationSummary[];
  conversationsLoading?: boolean;
  activeConversationId?: string | null;
  softLimitNote?: string | null;
  unavailableNote?: string | null;
  busyActionId?: string | null;
  onDraftChange: (value: string) => void;
  onSend: (message: string) => void;
  onNewChat: () => void;
  onShowHistory: () => void;
  onBackToChat: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onOpenAppearance: () => void;
  onClose: () => void;
  onConfirm: (action: JarvisAction) => void;
  onReject: (action: JarvisAction) => void;
  onNavigate?: () => void;
  /** Harness `/preview/jarvis`: panel w przepływie strony zamiast `fixed`. */
  inline?: boolean;
}

const FLOATING =
  "fixed inset-0 z-40 sm:inset-auto sm:bottom-24 sm:right-5 sm:h-[640px] sm:max-h-[calc(100vh-7.5rem)] sm:w-[420px] sm:rounded-2xl sm:border sm:border-border";
const INLINE = "relative h-[640px] w-full max-w-[420px] rounded-2xl border border-border";

function formatWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function JarvisPanel(props: JarvisPanelProps) {
  const {
    name,
    character,
    accent,
    mood,
    view,
    items,
    thinking,
    streaming,
    draft,
    suggestions,
    conversations = [],
    conversationsLoading = false,
    activeConversationId,
    softLimitNote,
    unavailableNote,
    busyActionId,
  } = props;
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (view === "chat") inputRef.current?.focus();
  }, [view]);

  const trimmed = draft.trim();
  const canSend = !streaming && !unavailableNote && trimmed.length > 0 && trimmed.length <= JARVIS_MAX_MESSAGE;

  function submit() {
    if (canSend) props.onSend(trimmed);
  }

  return (
    <section
      role="dialog"
      aria-label={`Asystent ${name}`}
      className={`flex flex-col bg-card text-foreground shadow-xl ${props.inline ? INLINE : FLOATING}`}
      data-testid="jarvis-panel"
    >
      <header className="flex items-center gap-2 border-b border-border px-3 py-2">
        {view === "history" ? (
          <Button size="icon-sm" variant="ghost" onClick={props.onBackToChat} aria-label="Wróć do rozmowy">
            <ArrowLeft className="h-4 w-4" />
          </Button>
        ) : (
          <JarvisCharacter id={character} accent={accent} mood={mood} size={36} />
        )}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{view === "history" ? "Poprzednie rozmowy" : name}</p>
          {view === "chat" && <p className="truncate text-xs text-muted-foreground">Asystent NEXUS — pytaj i zlecaj</p>}
        </div>
        {view === "chat" && (
          <>
            <Button size="icon-sm" variant="ghost" onClick={props.onNewChat} aria-label="Nowa rozmowa" title="Nowa rozmowa">
              <MessageSquarePlus className="h-4 w-4" />
            </Button>
            <Button size="icon-sm" variant="ghost" onClick={props.onShowHistory} aria-label="Poprzednie rozmowy" title="Poprzednie rozmowy">
              <History className="h-4 w-4" />
            </Button>
            <Button size="icon-sm" variant="ghost" onClick={props.onOpenAppearance} aria-label="Wygląd asystenta" title="Wygląd asystenta">
              <Palette className="h-4 w-4" />
            </Button>
          </>
        )}
        <Button size="icon-sm" variant="ghost" onClick={props.onClose} aria-label="Zamknij" title="Zamknij (Esc)">
          <X className="h-4 w-4" />
        </Button>
      </header>

      {view === "history" ? (
        <div className="flex-1 overflow-y-auto p-2">
          {conversationsLoading ? (
            <p className="p-3 text-sm text-muted-foreground">Wczytuję…</p>
          ) : conversations.length === 0 ? (
            <p className="p-3 text-sm text-muted-foreground">
              Nie masz jeszcze zapisanych rozmów. Rozmowy są przechowywane przez 30 dni.
            </p>
          ) : (
            <ul className="space-y-1">
              {conversations.map((c) => (
                <li key={c.id} className="group flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => props.onSelectConversation(c.id)}
                    className={`min-w-0 flex-1 rounded-md px-3 py-2 text-left hover:bg-muted ${
                      c.id === activeConversationId ? "bg-muted" : ""
                    }`}
                  >
                    <span className="block truncate text-sm">{c.title}</span>
                    <span className="block text-xs text-muted-foreground">{formatWhen(c.updated_at)}</span>
                  </button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => props.onDeleteConversation(c.id)}
                    aria-label={`Usuń rozmowę: ${c.title}`}
                    className="opacity-60 group-hover:opacity-100"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <>
          <div className="flex-1 overflow-y-auto px-3 py-3">
            {items.length === 0 && !thinking ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
                <JarvisCharacter id={character} accent={accent} mood="listening" size={88} />
                <div>
                  <p className="text-sm font-semibold">Cześć, tu {name}!</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Zapytaj o kandydatów, rekrutacje, klientów czy kontrakty — albo zleć zadanie. Każdą zmianę
                    najpierw Ci pokażę do zatwierdzenia.
                  </p>
                </div>
              </div>
            ) : (
              <JarvisMessageList
                items={items}
                thinking={thinking}
                assistantName={name}
                busyActionId={busyActionId}
                actionsDisabled={streaming}
                onConfirm={props.onConfirm}
                onReject={props.onReject}
                onNavigate={props.onNavigate}
              />
            )}
          </div>

          <div className="border-t border-border p-3">
            {unavailableNote && (
              <p className="mb-2 rounded-md bg-muted px-2 py-1.5 text-xs text-muted-foreground">{unavailableNote}</p>
            )}
            {!unavailableNote && softLimitNote && (
              <p className="mb-2 rounded-md bg-warning-muted px-2 py-1.5 text-xs text-warning-muted-foreground">{softLimitNote}</p>
            )}
            {items.length === 0 && suggestions.length > 0 && !unavailableNote && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    disabled={streaming}
                    onClick={() => props.onSend(s)}
                    className="rounded-full border border-border px-2.5 py-1 text-xs text-foreground hover:bg-muted disabled:opacity-50"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
            <form
              className="flex items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                submit();
              }}
            >
              <label htmlFor="jarvis-input" className="sr-only">
                Wiadomość do asystenta
              </label>
              <textarea
                id="jarvis-input"
                ref={inputRef}
                value={draft}
                rows={1}
                maxLength={JARVIS_MAX_MESSAGE}
                disabled={Boolean(unavailableNote)}
                onChange={(e) => props.onDraftChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    submit();
                  }
                }}
                placeholder={streaming ? `${name} odpowiada…` : `Napisz do ${name}…`}
                className="max-h-32 min-h-[40px] flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-ring/30 disabled:opacity-60"
              />
              <Button type="submit" size="icon" disabled={!canSend} aria-label="Wyślij">
                <Send className="h-4 w-4" />
              </Button>
            </form>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              {name} widzi tylko to, do czego masz dostęp. Usuwanie, umowy i stawki zostają w Twoich rękach.
            </p>
          </div>
        </>
      )}
    </section>
  );
}
