"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  CornerUpLeft,
  Edit2,
  Eye,
  Loader2,
  MessageCircle,
  Pin,
  PinOff,
  Search,
  Send,
  Smile,
  Trash2,
  X,
} from "lucide-react";

import { jobChatApi } from "@/lib/api";
import { cn, formatRelativeTime } from "@/lib/utils";
import { hasMinRole, useAuthStore } from "@/store/auth";
import {
  CHAT_BUS_EVENT,
  type ChatBusEvent,
  type ChatMessage,
  type ChatMessageListResp,
  type ReactionAggregate,
} from "@/types/job-chat";
import { MentionTextarea } from "@/components/v2/forms/MentionTextarea";

const QUICK_REACTIONS = ["👍", "❤️", "🎉", "🚀", "👀", "🤔", "🙏", "🔥"];

const PAGE_LIMIT = 50;

interface JobChatTabProps {
  jobId: number;
}

// ── Component ────────────────────────────────────────────────────────────────

export default function JobChatTab({ jobId }: JobChatTabProps) {
  const user = useAuthStore((s) => s.user);
  const canPin = hasMinRole(user, "delivery_lead");
  const queryClient = useQueryClient();

  // ── Members (do wyświetlenia licznika "X członków" w headerze) ────────────
  // Autocomplete @mention używa hook'a w MentionTextarea, niezwiązanego z tym query.
  const { data: members = [] } = useQuery({
    queryKey: ["job-chat-members", jobId],
    queryFn: async () => (await jobChatApi.getMembers(jobId)).data,
    staleTime: 60_000,
  });

  // ── Pinned ────────────────────────────────────────────────────────────────
  const { data: pinned = [] } = useQuery({
    queryKey: ["job-chat-pinned", jobId],
    queryFn: async () => (await jobChatApi.getPinned(jobId)).data,
    staleTime: 30_000,
  });

  // ── Messages — infinite scroll w stronę "starsze" ─────────────────────────
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSearch, setActiveSearch] = useState("");

  const messagesQuery = useInfiniteQuery({
    queryKey: ["job-chat-messages", jobId, activeSearch],
    initialPageParam: undefined as number | undefined,
    queryFn: async ({ pageParam }) => {
      const params: { limit: number; before_id?: number; search?: string } = {
        limit: PAGE_LIMIT,
      };
      if (pageParam) params.before_id = pageParam;
      if (activeSearch.trim()) params.search = activeSearch.trim();
      const resp = await jobChatApi.listMessages(jobId, params);
      return resp.data as ChatMessageListResp;
    },
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? (lastPage.next_before_id ?? undefined) : undefined,
  });

  // Merge wszystkich page'y w jedną listę i odwróć (najstarsza pierwsza, dla UI od dołu).
  const messages = useMemo<ChatMessage[]>(() => {
    const all = (messagesQuery.data?.pages ?? []).flatMap((p) => p.items);
    return all.slice().reverse();
  }, [messagesQuery.data]);

  // ── Compose state ─────────────────────────────────────────────────────────
  const [text, setText] = useState("");
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll do dołu tylko gdy user już jest blisko dołu
  const stickToBottomRef = useRef(true);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottomRef.current = distanceFromBottom < 120;

    // Lazy-load starszych wiadomości gdy user scrolluje na sam wierzch
    if (
      el.scrollTop < 60 &&
      messagesQuery.hasNextPage &&
      !messagesQuery.isFetchingNextPage
    ) {
      messagesQuery.fetchNextPage();
    }
  };

  useEffect(() => {
    if (stickToBottomRef.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages.length]);

  // ── Mutations ─────────────────────────────────────────────────────────────
  const sendMutation = useMutation({
    mutationFn: async (payload: {
      content: string;
      reply_to_message_id?: number | null;
    }) => (await jobChatApi.sendMessage(jobId, payload)).data,
    onSuccess: () => {
      setText("");
      setReplyTo(null);
      stickToBottomRef.current = true;
      // Server emituje WS event do wszystkich (w tym do autora) → invalidacja
      // ride'uje na CHAT_BUS_EVENT, ale dla pewności wyzwalamy też tutaj.
      queryClient.invalidateQueries({
        queryKey: ["job-chat-messages", jobId, activeSearch],
      });
    },
  });

  const editMutation = useMutation({
    mutationFn: async ({ id, content }: { id: number; content: string }) =>
      (await jobChatApi.editMessage(jobId, id, { content })).data,
    onSuccess: () => {
      setText("");
      setEditingId(null);
      queryClient.invalidateQueries({
        queryKey: ["job-chat-messages", jobId, activeSearch],
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await jobChatApi.deleteMessage(jobId, id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["job-chat-messages", jobId, activeSearch],
      });
    },
  });

  const pinMutation = useMutation({
    mutationFn: async ({ id, pin }: { id: number; pin: boolean }) =>
      pin
        ? (await jobChatApi.pinMessage(jobId, id)).data
        : (await jobChatApi.unpinMessage(jobId, id)).data,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["job-chat-pinned", jobId] });
      queryClient.invalidateQueries({
        queryKey: ["job-chat-messages", jobId, activeSearch],
      });
    },
  });

  const reactionMutation = useMutation({
    mutationFn: async ({
      id,
      emoji,
      add,
    }: {
      id: number;
      emoji: string;
      add: boolean;
    }) =>
      add
        ? (await jobChatApi.addReaction(jobId, id, emoji)).data
        : (await jobChatApi.removeReaction(jobId, id, emoji)).data,
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["job-chat-messages", jobId, activeSearch],
      });
    },
  });

  // ── WS bus listener ───────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: Event) => {
      const ev = e as CustomEvent<ChatBusEvent>;
      const detail = ev.detail;
      if (!detail) return;

      // Filtrujemy tylko wiadomości tego joba
      const eventJobId =
        detail.kind === "delete" || detail.kind === "pin"
          ? detail.data.job_id
          : detail.data.job_id;
      if (eventJobId !== jobId) return;

      queryClient.invalidateQueries({
        queryKey: ["job-chat-messages", jobId, activeSearch],
      });
      queryClient.invalidateQueries({ queryKey: ["job-chat-pinned", jobId] });
      queryClient.invalidateQueries({ queryKey: ["job-chat-unread", jobId] });

      // Mark as read jeśli to nowa wiadomość a tab jest aktywny
      if (detail.kind === "new" && document.visibilityState === "visible") {
        // best-effort, w tle
        jobChatApi.markRead(jobId).catch(() => undefined);
      }
    };
    window.addEventListener(CHAT_BUS_EVENT, handler as EventListener);
    return () =>
      window.removeEventListener(CHAT_BUS_EVENT, handler as EventListener);
  }, [jobId, activeSearch, queryClient]);

  // Mark read on mount + przy każdej zmianie ostatniej wiadomości (jeśli tab widoczny)
  useEffect(() => {
    jobChatApi.markRead(jobId).catch(() => undefined);
  }, [jobId, messages.length]);

  // ── Submit ────────────────────────────────────────────────────────────────
  const handleSubmit = (e?: FormEvent) => {
    e?.preventDefault();
    const trimmed = text.trim();
    if (!trimmed) return;
    if (editingId !== null) {
      editMutation.mutate({ id: editingId, content: trimmed });
    } else {
      sendMutation.mutate({
        content: trimmed,
        reply_to_message_id: replyTo?.id ?? null,
      });
    }
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
      return;
    }
    if (e.key === "Escape") {
      if (editingId !== null) {
        setEditingId(null);
        setText("");
      } else if (replyTo) {
        setReplyTo(null);
      }
    }
  };

  const handleSearchSubmit = (e: FormEvent) => {
    e.preventDefault();
    setActiveSearch(searchQuery);
  };

  const startEdit = (m: ChatMessage) => {
    setEditingId(m.id);
    setReplyTo(null);
    setText(m.content);
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const cancelEdit = () => {
    setEditingId(null);
    setText("");
  };

  return (
    <div className="flex flex-col h-[70vh] bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <MessageCircle className="w-5 h-5 text-blue-500" />
          <h2 className="text-base font-semibold">Chat zespołu</h2>
          <span className="text-xs text-gray-400">
            {members.length} członków
          </span>
        </div>
        <form onSubmit={handleSearchSubmit} className="flex items-center gap-1">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              type="text"
              placeholder="Szukaj…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-7 pr-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900"
            />
          </div>
          {activeSearch && (
            <button
              type="button"
              onClick={() => {
                setSearchQuery("");
                setActiveSearch("");
              }}
              className="text-xs text-gray-500 hover:text-gray-700"
              aria-label="Wyczyść wyszukiwanie"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </form>
      </div>

      {/* Pinned bar */}
      {pinned.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border-b border-amber-200 dark:border-amber-800 px-4 py-2 space-y-1">
          {pinned.map((p) => (
            <div key={p.id} className="flex items-start gap-2 text-xs">
              <Pin className="w-3 h-3 mt-0.5 text-amber-600 flex-shrink-0" />
              <div className="flex-1 truncate">
                <span className="font-medium">{p.author?.name ?? "?"}: </span>
                <span className="text-gray-700 dark:text-gray-300">
                  {p.content}
                </span>
              </div>
              {canPin && (
                <button
                  onClick={() => pinMutation.mutate({ id: p.id, pin: false })}
                  className="text-amber-600 hover:text-amber-800"
                  aria-label="Odepnij"
                >
                  <PinOff className="w-3 h-3" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Message list */}
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-3"
      >
        {messagesQuery.isFetchingNextPage && (
          <div className="text-center text-xs text-gray-400">
            <Loader2 className="w-4 h-4 inline-block animate-spin mr-1" />
            Ładowanie starszych…
          </div>
        )}
        {messages.length === 0 && !messagesQuery.isLoading && (
          <div className="text-center text-sm text-gray-400 py-12">
            Brak wiadomości{activeSearch ? " pasujących do filtra" : ""}.
          </div>
        )}
        {messages.map((m) => (
          <MessageRow
            key={m.id}
            message={m}
            currentUserId={user?.id ?? -1}
            canPin={canPin}
            isAdmin={user?.role === "admin"}
            onReply={() => {
              setReplyTo(m);
              setEditingId(null);
              requestAnimationFrame(() => textareaRef.current?.focus());
            }}
            onEdit={() => startEdit(m)}
            onDelete={() => deleteMutation.mutate(m.id)}
            onPinToggle={() => pinMutation.mutate({ id: m.id, pin: !m.pinned })}
            onReaction={(emoji, add) =>
              reactionMutation.mutate({ id: m.id, emoji, add })
            }
            onLoadReadBy={async (msgId) =>
              (await jobChatApi.getReadBy(jobId, msgId)).data
            }
          />
        ))}
      </div>

      {/* Reply / edit banner */}
      {(replyTo || editingId !== null) && (
        <div className="flex items-center justify-between px-4 py-1.5 bg-blue-50 dark:bg-blue-900/30 border-t border-blue-200 dark:border-blue-800 text-xs">
          <span className="truncate">
            {editingId !== null ? (
              <>Edytujesz wiadomość</>
            ) : (
              <>
                Odpowiadasz <strong>{replyTo?.author?.name ?? "?"}</strong>:{" "}
                <span className="text-gray-600 dark:text-gray-400 truncate">
                  {replyTo?.content}
                </span>
              </>
            )}
          </span>
          <button
            onClick={() => {
              if (editingId !== null) cancelEdit();
              else setReplyTo(null);
            }}
            className="text-blue-600 hover:text-blue-800"
            aria-label="Anuluj"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Compose */}
      <form
        onSubmit={handleSubmit}
        className="relative border-t border-gray-200 dark:border-gray-700 px-3 py-2"
      >
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <MentionTextarea
              value={text}
              onChange={setText}
              scope={{ kind: "job", jobId }}
              textareaRef={textareaRef}
              onKeyDown={handleKey}
              placeholder={
                editingId !== null
                  ? "Edytuj wiadomość…"
                  : "Napisz wiadomość… (@email aby oznaczyć osobę, Enter wysyła, Shift+Enter = nowa linia)"
              }
              rows={2}
              disabled={sendMutation.isPending || editMutation.isPending}
              ariaLabel="Treść wiadomości chatu"
            />
          </div>
          <button
            type="submit"
            disabled={
              !text.trim() ||
              sendMutation.isPending ||
              editMutation.isPending
            }
            className={cn(
              "flex items-center justify-center w-10 h-10 rounded-lg",
              "bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 disabled:cursor-not-allowed",
            )}
            aria-label="Wyślij"
          >
            {sendMutation.isPending || editMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

// ── MessageRow ───────────────────────────────────────────────────────────────

interface MessageRowProps {
  message: ChatMessage;
  currentUserId: number;
  canPin: boolean;
  isAdmin: boolean;
  onReply: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onPinToggle: () => void;
  onReaction: (emoji: string, add: boolean) => void;
  onLoadReadBy: (
    msgId: number,
  ) => Promise<{ user_id: number; name: string; read_at: string }[]>;
}

function MessageRow({
  message,
  currentUserId,
  canPin,
  isAdmin,
  onReply,
  onEdit,
  onDelete,
  onPinToggle,
  onReaction,
  onLoadReadBy,
}: MessageRowProps) {
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [readByOpen, setReadByOpen] = useState(false);
  const [readByList, setReadByList] = useState<
    { user_id: number; name: string; read_at: string }[] | null
  >(null);

  const hasMyReaction = (emoji: string) =>
    message.reactions.some(
      (r) => r.emoji === emoji && r.user_ids.includes(currentUserId),
    );

  const showReadBy = async () => {
    setReadByOpen((prev) => !prev);
    if (readByList === null) {
      try {
        const data = await onLoadReadBy(message.id);
        setReadByList(data);
      } catch {
        setReadByList([]);
      }
    }
  };

  const isAuthor = message.author?.id === currentUserId;
  const canEdit = isAuthor && !message.is_deleted;
  const canDelete = (isAuthor || isAdmin) && !message.is_deleted;

  return (
    <div
      className={cn(
        "group flex gap-3",
        message.is_deleted && "opacity-60",
        message.pinned && "bg-amber-50/40 dark:bg-amber-900/10 -mx-2 px-2 py-1 rounded",
      )}
    >
      {/* Avatar (initials) */}
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-500 text-white flex items-center justify-center text-xs font-semibold">
        {(message.author?.name ?? "?").slice(0, 2).toUpperCase()}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span className="font-semibold text-gray-900 dark:text-gray-100">
            {message.author?.name ?? "(usunięty użytkownik)"}
          </span>
          <span>{formatRelativeTime(message.created_at)}</span>
          {message.is_edited && !message.is_deleted && (
            <span className="text-gray-400">(edytowano)</span>
          )}
          {message.pinned && (
            <Pin className="w-3 h-3 text-amber-600" aria-label="Przypięte" />
          )}
        </div>

        {message.reply_to_preview && (
          <div className="mt-1 mb-1 text-xs px-2 py-1 border-l-2 border-blue-400 bg-gray-50 dark:bg-gray-900/50 truncate">
            <CornerUpLeft className="w-3 h-3 inline-block mr-1 text-blue-400" />
            {message.reply_to_preview}
          </div>
        )}

        <div
          className={cn(
            "mt-0.5 text-sm whitespace-pre-wrap break-words",
            message.is_deleted && "italic text-gray-400",
          )}
        >
          {message.content}
        </div>

        {/* Reactions chips */}
        {message.reactions.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {message.reactions.map((r: ReactionAggregate) => {
              const mine = r.user_ids.includes(currentUserId);
              return (
                <button
                  key={r.emoji}
                  type="button"
                  onClick={() => onReaction(r.emoji, !mine)}
                  className={cn(
                    "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border text-xs transition-colors",
                    mine
                      ? "bg-blue-100 border-blue-400 text-blue-700 dark:bg-blue-900/40"
                      : "bg-gray-100 border-gray-300 text-gray-700 dark:bg-gray-700 dark:border-gray-600",
                  )}
                  title={`${r.count} ${r.count === 1 ? "reakcja" : "reakcji"}`}
                >
                  <span>{r.emoji}</span>
                  <span>{r.count}</span>
                </button>
              );
            })}
          </div>
        )}

        {!message.is_deleted && (
          <div className="opacity-0 group-hover:opacity-100 transition-opacity mt-1 flex items-center gap-2 text-xs relative">
            <button
              onClick={onReply}
              className="text-gray-500 hover:text-blue-600 flex items-center gap-1"
            >
              <CornerUpLeft className="w-3 h-3" />
              Odpowiedz
            </button>
            <div className="relative">
              <button
                onClick={() => setEmojiOpen((v) => !v)}
                className="text-gray-500 hover:text-amber-500 flex items-center gap-1"
                aria-label="Dodaj reakcję"
              >
                <Smile className="w-3 h-3" />
                Reakcja
              </button>
              {emojiOpen && (
                <div className="absolute z-10 mt-1 left-0 flex gap-1 p-1.5 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg">
                  {QUICK_REACTIONS.map((emoji) => {
                    const mine = hasMyReaction(emoji);
                    return (
                      <button
                        key={emoji}
                        onClick={() => {
                          onReaction(emoji, !mine);
                          setEmojiOpen(false);
                        }}
                        className={cn(
                          "w-7 h-7 rounded hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center justify-center text-base",
                          mine && "ring-2 ring-blue-400",
                        )}
                      >
                        {emoji}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            <button
              onClick={showReadBy}
              className="text-gray-500 hover:text-blue-600 flex items-center gap-1 relative"
              aria-label="Kto przeczytał"
            >
              <Eye className="w-3 h-3" />
              Przeczytane
              {readByOpen && readByList && (
                <div className="absolute z-10 mt-1 top-full left-0 min-w-[180px] p-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg text-left">
                  {readByList.length === 0 ? (
                    <span className="text-gray-500 text-xs">
                      Jeszcze nikt nie przeczytał
                    </span>
                  ) : (
                    <ul className="space-y-0.5">
                      {readByList.map((u) => (
                        <li
                          key={u.user_id}
                          className="flex justify-between gap-3 text-xs"
                        >
                          <span className="font-medium">{u.name}</span>
                          <span className="text-gray-500">
                            {formatRelativeTime(u.read_at)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </button>
            {canEdit && (
              <button
                onClick={onEdit}
                className="text-gray-500 hover:text-blue-600 flex items-center gap-1"
              >
                <Edit2 className="w-3 h-3" />
                Edytuj
              </button>
            )}
            {canDelete && (
              <button
                onClick={onDelete}
                className="text-gray-500 hover:text-red-600 flex items-center gap-1"
              >
                <Trash2 className="w-3 h-3" />
                Usuń
              </button>
            )}
            {canPin && (
              <button
                onClick={onPinToggle}
                className="text-gray-500 hover:text-amber-600 flex items-center gap-1"
              >
                {message.pinned ? (
                  <>
                    <PinOff className="w-3 h-3" />
                    Odepnij
                  </>
                ) : (
                  <>
                    <Pin className="w-3 h-3" />
                    Przypnij
                  </>
                )}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
