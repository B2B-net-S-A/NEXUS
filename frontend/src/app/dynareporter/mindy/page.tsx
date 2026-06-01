"use client";

/**
 * DynaReporter B.2.10 – MINDY AI chatbot.
 *
 * Dwa tryby:
 * - "Komentarz" – jednorazowy insight MINDY (analyze KPI + sugestia)
 * - Chat – interactive z history (localStorage)
 */

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useAuthStore, hasSection } from "@/store/auth";
import api from "@/lib/api";
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

const STORAGE_KEY = "dr_mindy_history_v1";

export default function MindyPage() {
  const { user, hydrated } = useAuthStore();
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [period, setPeriod] = useState<"week" | "month" | "quarter">("month");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Load history from localStorage
  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      try {
        setChatHistory(JSON.parse(raw));
      } catch {
        /* ignore */
      }
    }
  }, []);
  // Persist history
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(chatHistory));
  }, [chatHistory]);
  // Auto-scroll
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [chatHistory]);

  const commentaryQ = useQuery({
    queryKey: ["dr", "mindy", "commentary", period],
    queryFn: () =>
      api
        .post<MindyResponse>("/api/dynareporter/mindy/commentary", { period })
        .then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "mindy"),
  });

  const chatMut = useMutation({
    mutationFn: (msgs: ChatMessage[]) =>
      api
        .post<MindyResponse>("/api/dynareporter/mindy/chat", { messages: msgs })
        .then((r) => r.data),
  });

  const sendMessage = async () => {
    if (!inputValue.trim() || chatMut.isPending) return;
    const newMsgs: ChatMessage[] = [
      ...chatHistory,
      { role: "user", content: inputValue.trim() },
    ];
    setChatHistory(newMsgs);
    setInputValue("");
    try {
      const resp = await chatMut.mutateAsync(newMsgs);
      setChatHistory([...newMsgs, { role: "assistant", content: resp.content }]);
    } catch (e) {
      // Show error in chat
      setChatHistory([
        ...newMsgs,
        { role: "assistant", content: `❌ Błąd: ${e instanceof Error ? e.message : "unknown"}` },
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
        {commentaryQ.isLoading ? (
          <p className="text-sm text-muted-foreground">MINDY analizuje Twoje KPI…</p>
        ) : commentaryQ.isError ? (
          <p className="text-sm text-destructive">
            Błąd: {(commentaryQ.error as Error).message}. Sprawdź czy ANTHROPIC_API_KEY jest skonfigurowany.
          </p>
        ) : commentaryQ.data ? (
          <>
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{commentaryQ.data.content}</p>
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-muted-foreground">
                Kontekst (KPI)
              </summary>
              <pre className="mt-2 p-2 bg-muted rounded text-[10px] overflow-x-auto">
                {commentaryQ.data.context_summary}
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
              Zadaj MINDY pytanie – np. „Jak poprawić moje placementy?" lub „Czy mam szansę na podium tego kwartału?"
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
