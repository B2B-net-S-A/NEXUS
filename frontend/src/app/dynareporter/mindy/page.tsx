"use client";

/**
 * DynaReporter B.2.10 — MINDY AI chatbot.
 *
 * Dwa tryby:
 * - "Komentarz" — jednorazowy insight MINDY (analyze KPI + sugestia)
 * - Chat — interactive z history (localStorage)
 */

import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useAuthStore, hasSection } from "@/store/auth";
import api from "@/lib/api";
import { normalizeMindyHistory } from "@/lib/ai-feature-safety";
import { cn } from "@/lib/utils";

interface MindyResponse {
  content: string;
  model: string;
  context_summary?: string;
}
interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

const HISTORY_TTL_MS = 24 * 60 * 60 * 1000;
const historyKey = (userId: number | string) => `dr_mindy_history_v2:${userId}`;

export default function MindyPage() {
  const { user, hydrated } = useAuthStore();
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [period, setPeriod] = useState<"week" | "month" | "quarter">("month");
  const [mode, setMode] = useState<"quick" | "deep">("quick");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const activeHistoryKeyRef = useRef<string | null>(null);

  // Load history from localStorage
  useEffect(() => {
    if (typeof window === "undefined" || !hydrated) return;
    if (!user) {
      if (activeHistoryKeyRef.current) {
        window.localStorage.removeItem(activeHistoryKeyRef.current);
        activeHistoryKeyRef.current = null;
      }
      setChatHistory([]);
      return;
    }
    const key = historyKey(user.id);
    activeHistoryKeyRef.current = key;
    const raw = window.localStorage.getItem(key);
    if (raw) {
      try {
        const stored = JSON.parse(raw) as unknown;
        const messages = normalizeMindyHistory(stored);
        if (messages.length > 0) {
          setChatHistory(messages);
        } else {
          window.localStorage.removeItem(key);
          setChatHistory([]);
        }
      } catch {
        window.localStorage.removeItem(key);
        setChatHistory([]);
      }
    }
  }, [hydrated, user]);
  // Persist history
  useEffect(() => {
    if (typeof window === "undefined" || !user) return;
    window.localStorage.setItem(
      historyKey(user.id),
      JSON.stringify({
        expiresAt: Date.now() + HISTORY_TTL_MS,
        messages: chatHistory.slice(-20),
      }),
    );
  }, [chatHistory, user]);
  // Auto-scroll
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chatHistory]);

  const commentaryMut = useMutation({
    mutationFn: () =>
      api
        .post<MindyResponse>("/api/dynareporter/mindy/commentary", { period, mode })
        .then((r) => r.data),
    retry: false,
  });

  const chatMut = useMutation({
    mutationFn: (msgs: ChatMessage[]) =>
      api
        .post<MindyResponse>("/api/dynareporter/mindy/chat", { messages: msgs, mode })
        .then((r) => r.data),
    retry: false,
  });

  const sendMessage = async () => {
    if (!inputValue.trim() || chatMut.isPending) return;
    const userMessage: ChatMessage = { role: "user", content: inputValue.trim() };
    const newMsgs = [...chatHistory, userMessage].slice(-20);
    setChatHistory(newMsgs);
    setInputValue("");
    try {
      const resp = await chatMut.mutateAsync(newMsgs);
      const assistantMessage: ChatMessage = { role: "assistant", content: resp.content };
      setChatHistory([...newMsgs, assistantMessage].slice(-20));
    } catch (e) {
      // Show error in chat
      const errorMessage: ChatMessage = {
        role: "assistant",
        content: `❌ Błąd: ${e instanceof Error ? e.message : "unknown"}`,
      };
      setChatHistory([
        ...newMsgs,
        errorMessage,
      ]);
    }
  };

  if (!hydrated) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  if (!user) return <div className="p-8 text-sm text-muted-foreground">Zaloguj się.</div>;
  if (!hasSection(user, "mindy")) {
    return (
      <div className="container mx-auto max-w-2xl p-6">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold text-destructive">Brak dostępu</h2>
          <p className="mt-1 text-sm text-muted-foreground">Brak sekcji <code>mindy</code>.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-5xl p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">✨ MINDY AI</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Asystentka AI z kontekstem Twoich KPI. Komentarz jednorazowy lub interaktywny chat.
        </p>
      </header>

      <div className="inline-flex rounded-md border border-border bg-card p-1" aria-label="Tryb MINDY">
        {(["quick", "deep"] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setMode(value)}
            className={cn(
              "rounded px-3 py-1.5 text-xs font-medium transition-colors",
              mode === value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {value === "quick" ? "Quick" : "Deep"}
          </button>
        ))}
      </div>

      {/* Commentary */}
      <section className="rounded-lg border border-border bg-card p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold">Komentarz MINDY</h2>
          <div className="inline-flex rounded-md border border-border bg-card p-1">
            {(["week", "month", "quarter"] as const).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPeriod(p)}
                className={cn(
                  "px-3 py-1 text-xs font-medium rounded transition-colors",
                  period === p
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {{ week: "Tydzień", month: "Miesiąc", quarter: "Kwartał" }[p]}
              </button>
            ))}
          </div>
        </div>
        <button
          type="button"
          onClick={() => commentaryMut.mutate()}
          disabled={commentaryMut.isPending}
          className="mb-3 rounded-md bg-primary px-3 py-2 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          {commentaryMut.isPending ? "Analizuję…" : "Generuj komentarz"}
        </button>
        {commentaryMut.isPending ? (
          <p className="text-sm text-muted-foreground">MINDY analizuje Twoje KPI…</p>
        ) : commentaryMut.isError ? (
          <p className="text-sm text-destructive">
            Błąd: {(commentaryMut.error as Error).message}.
          </p>
        ) : commentaryMut.data ? (
          <>
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{commentaryMut.data.content}</p>
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-muted-foreground">
                Kontekst (KPI)
              </summary>
              <pre className="mt-2 p-2 bg-muted rounded text-[10px] overflow-x-auto">
                {commentaryMut.data.context_summary}
              </pre>
            </details>
          </>
        ) : null}
      </section>

      {/* Chat */}
      <section className="rounded-lg border border-border bg-card flex flex-col h-[500px]">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <h2 className="font-semibold text-sm">Chat z MINDY</h2>
          <button
            type="button"
            onClick={() => setChatHistory([])}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            Wyczyść historię
          </button>
        </div>

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
          {chatHistory.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-8">
              Zadaj MINDY pytanie — np. „Jak poprawić moje placementy?" lub „Czy mam szansę na podium tego kwartału?"
            </p>
          ) : (
            chatHistory.map((m, i) => (
              <div
                key={i}
                className={cn(
                  "rounded-lg p-3 max-w-[85%]",
                  m.role === "user"
                    ? "bg-primary/10 ml-auto"
                    : "bg-muted"
                )}
              >
                <p className="text-xs font-semibold text-muted-foreground uppercase mb-1">
                  {m.role === "user" ? "Ty" : "✨ MINDY"}
                </p>
                <p className="text-sm whitespace-pre-wrap">{m.content}</p>
              </div>
            ))
          )}
          {chatMut.isPending && (
            <div className="bg-muted rounded-lg p-3 max-w-[85%]">
              <p className="text-xs font-semibold text-muted-foreground uppercase mb-1">✨ MINDY</p>
              <p className="text-sm text-muted-foreground">Myślę…</p>
            </div>
          )}
        </div>

        <div className="border-t border-border p-3 flex gap-2">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
            placeholder="Zapytaj MINDY..."
            disabled={chatMut.isPending}
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <button
            type="button"
            onClick={sendMessage}
            disabled={!inputValue.trim() || chatMut.isPending}
            className="rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Wyślij
          </button>
        </div>
      </section>
    </div>
  );
}
