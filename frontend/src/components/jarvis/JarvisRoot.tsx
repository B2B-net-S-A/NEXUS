"use client";

/**
 * Jarvis w shellu aplikacji — maskotka + panel rozmowy (0330, zastępuje MINDY
 * i dawną KidsMascot).
 *
 * Bramki (kolejno):
 * - tylko zalogowana osoba na WŁASNEJ sesji: w trybie „podgląd jako” Jarvis
 *   znika (backend i tak odmawia — rozmowa szłaby cudzymi uprawnieniami);
 * - `GET /api/jarvis/status`: wyłączony flagą albo bez klucza modelu → brak
 *   maskotki (w trybie kids maskotka zostaje, ale panel mówi, że nie działa);
 * - `prefs.enabled = false` → brak maskotki; ⌘J dalej otwiera panel.
 *
 * Każdy zapis przechodzi przez kartę akcji (klik człowieka) — ten komponent
 * tylko woła confirm/reject i odświeża dane ekranu kluczami z odpowiedzi.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, triggerSessionExpiredRedirect } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  confirmAction,
  deleteConversation,
  fetchConversation,
  fetchConversations,
  fetchJarvisPrefs,
  fetchJarvisStatus,
  jarvisKeys,
  rejectAction,
  saveJarvisPrefs,
} from "@/lib/jarvis/api";
import { screenFromLocation, suggestionsFor } from "@/lib/jarvis/context";
import { JARVIS_OPEN_EVENT, type JarvisOpenDetail } from "@/lib/jarvis/events";
import { applyStreamEvent, replaceAction, type JarvisTurnState } from "@/lib/jarvis/reducer";
import { JarvisHttpError, streamJarvisChat } from "@/lib/jarvis/stream";
import type { JarvisAction, JarvisPrefs, JarvisPrefsResponse } from "@/lib/jarvis/types";
import { playPetSound } from "@/lib/kidsSound";
import { hasSectionAccess } from "@/lib/section-access";
import { hasCapability } from "@/lib/capabilities";
import type { MyPeopleSummary } from "@/lib/api/myPeople";
import {
  MY_PEOPLE_MATCH_EVENT,
  briefFragments,
  jobIdFromMatchLink,
  reassignPrompt,
  type MyPeopleMatchEventDetail,
} from "@/lib/my-people-summary";
import { hasRole, useAuthStore } from "@/store/auth";
import { useThemeStore } from "@/store/theme";
import { JarvisAppearanceDialog } from "./JarvisAppearanceDialog";
import { JarvisMascot } from "./JarvisMascot";
import { JarvisPanel } from "./JarvisPanel";
import { useKidsChatter } from "./useKidsChatter";

const DEFAULT_PREFS: JarvisPrefsResponse = {
  character: "robot",
  name: "Jarvis",
  accent: "primary",
  enabled: true,
  minimized: false,
  sound: false,
  daily_brief: true,
  unlocked_characters: ["robot", "owl", "cat", "ghost", "rocket", "star", "dragon", "astronaut"],
  locked_characters: {},
};

const EMPTY_TURN: JarvisTurnState = { items: [], thinking: false, mood: "idle", conversationId: null };

function storageKey(userId: number | undefined, name: string): string {
  return `nexus:jarvis:${name}:v1:${userId ?? "anon"}`;
}

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage zablokowany — funkcja działa bez pamięci */
  }
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

function todayKey(): string {
  return new Date().toISOString().slice(0, 10);
}

export function JarvisRoot() {
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const hydrated = useAuthStore((s) => s.hydrated);
  const user = useAuthStore((s) => s.user);
  const ownSession = useAuthStore((s) => !!s.token && !s.realUser);
  const kidsMode = useThemeStore((s) => s.kidsMode);
  const kidsSound = useThemeStore((s) => s.kidsSound);
  const kidsAutoTalk = useThemeStore((s) => s.kidsAutoTalk);
  const active = hydrated && ownSession && Boolean(user);

  const statusQuery = useQuery({
    queryKey: jarvisKeys.status,
    queryFn: fetchJarvisStatus,
    enabled: active,
    staleTime: 60_000,
    retry: 0,
  });
  const prefsQuery = useQuery({
    queryKey: jarvisKeys.prefs,
    queryFn: fetchJarvisPrefs,
    enabled: active,
    staleTime: 5 * 60_000,
    retry: 0,
  });
  const prefs = prefsQuery.data ?? DEFAULT_PREFS;
  const status = statusQuery.data;
  const available = Boolean(status?.available);

  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"chat" | "history">("chat");
  const [draft, setDraft] = useState("");
  const [turn, setTurn] = useState<JarvisTurnState>(EMPTY_TURN);
  const [streaming, setStreaming] = useState(false);
  const [busyActionId, setBusyActionId] = useState<string | null>(null);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [brief, setBrief] = useState<string | null>(null);
  // Przypomnienie „Moi ludzie": dymek z gotowym pytaniem o przepięcie. Ma
  // pierwszeństwo przed porannym skrótem — dotyczy rekrutacji z tej chwili.
  const [nudge, setNudge] = useState<{ text: string; prompt: string } | null>(null);
  const [webMode, setWebMode] = useState(false);
  const loadedConversation = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const conversationStorage = storageKey(user?.id, "conversation");
  const kids = useKidsChatter({
    enabled: active && kidsMode,
    sound: kidsSound,
    autoTalk: kidsAutoTalk,
    firstName: user?.name?.trim().split(/\s+/)[0],
  });

  // Ostatnia rozmowa wraca po odświeżeniu strony.
  useEffect(() => {
    if (!active) return;
    const saved = readStorage(conversationStorage);
    if (saved) setTurn((t) => (t.conversationId ? t : { ...t, conversationId: saved }));
  }, [active, conversationStorage]);

  useEffect(() => {
    if (!active) return;
    writeStorage(conversationStorage, turn.conversationId);
  }, [active, conversationStorage, turn.conversationId]);

  // Historia rozmowy dociągana przy pierwszym otwarciu panelu.
  useEffect(() => {
    const id = turn.conversationId;
    if (!open || !available || !id || streaming || loadedConversation.current === id) return;
    if (turn.items.length > 0) {
      loadedConversation.current = id;
      return;
    }
    loadedConversation.current = id;
    fetchConversation(id)
      .then((detail) => setTurn((t) => (t.conversationId === id ? { ...t, items: detail.items } : t)))
      .catch(() => {
        // Rozmowa wygasła (retencja 30 dni) albo usunięta — zaczynamy od nowa.
        setTurn(EMPTY_TURN);
      });
  }, [open, available, turn.conversationId, turn.items.length, streaming]);

  const conversationsQuery = useQuery({
    queryKey: jarvisKeys.conversations,
    queryFn: fetchConversations,
    enabled: active && open && view === "history",
    staleTime: 10_000,
    retry: 0,
  });

  const send = useCallback(
    async (message: string) => {
      const text = message.trim();
      if (!text || streaming) return;
      setDraft("");
      setView("chat");
      setStreaming(true);
      // Internet dotyczy tylko tej jednej wiadomości.
      setWebMode(false);
      setTurn((t) => ({
        ...t,
        items: [...t.items, { kind: "message", role: "user", markdown: text }],
        thinking: true,
        mood: "thinking",
      }));
      const controller = new AbortController();
      abortRef.current = controller;
      const screen = screenFromLocation(
        typeof window !== "undefined" ? window.location.pathname : pathname,
        typeof window !== "undefined" ? window.location.search : "",
      );
      try {
        await streamJarvisChat(
          { message: text, conversation_id: turn.conversationId, screen, web: webMode },
          {
            signal: controller.signal,
            onUnauthorized: triggerSessionExpiredRedirect,
            onEvent: (event) => {
              if (event.type === "conversation") loadedConversation.current = event.conversation_id;
              setTurn((t) => applyStreamEvent(t, event));
            },
          },
        );
        if (prefs.sound) playPetSound();
      } catch (error) {
        const messageText =
          error instanceof JarvisHttpError
            ? error.message
            : controller.signal.aborted
              ? "Przerwano."
              : "Nie udało się połączyć z asystentem. Sprawdź połączenie i spróbuj ponownie.";
        setTurn((t) => applyStreamEvent(t, { type: "error", message: messageText }));
      } finally {
        setStreaming(false);
        abortRef.current = null;
        setTurn((t) => ({ ...t, thinking: false }));
        queryClient.invalidateQueries({ queryKey: jarvisKeys.status });
        queryClient.invalidateQueries({ queryKey: jarvisKeys.conversations });
      }
    },
    [streaming, turn.conversationId, pathname, prefs.sound, queryClient, webMode],
  );

  const decide = useCallback(
    async (action: JarvisAction, decision: "confirm" | "reject") => {
      setBusyActionId(action.id);
      try {
        const outcome = decision === "confirm" ? await confirmAction(action.id) : await rejectAction(action.id);
        setTurn((t) => ({
          ...t,
          items: replaceAction(t.items, outcome.action, outcome.follow_up, outcome.message),
          mood: outcome.action.status === "executed" ? "success" : outcome.action.status === "failed" ? "error" : "idle",
        }));
        for (const key of outcome.invalidates) queryClient.invalidateQueries({ queryKey: key });
      } catch (error) {
        setTurn((t) => ({
          ...t,
          items: [
            ...t.items,
            { kind: "error", message: apiErrorMessage(error, "Nie udało się zapisać decyzji. Spróbuj ponownie.") },
          ],
          mood: "error",
        }));
      } finally {
        setBusyActionId(null);
      }
    },
    [queryClient],
  );

  const newChat = useCallback(() => {
    if (streaming) return;
    loadedConversation.current = null;
    setTurn(EMPTY_TURN);
    setView("chat");
  }, [streaming]);

  const selectConversation = useCallback(
    (id: string) => {
      if (streaming) return;
      loadedConversation.current = null;
      setTurn({ ...EMPTY_TURN, conversationId: id });
      setView("chat");
    },
    [streaming],
  );

  const removeConversation = useMutation({
    mutationFn: deleteConversation,
    onSuccess: (_data, id) => {
      queryClient.invalidateQueries({ queryKey: jarvisKeys.conversations });
      if (turn.conversationId === id) newChat();
    },
  });

  const savePrefs = useMutation({
    mutationFn: (next: Partial<JarvisPrefs>) => saveJarvisPrefs(next),
    onSuccess: (data) => {
      queryClient.setQueryData(jarvisKeys.prefs, data);
      setAppearanceOpen(false);
    },
  });

  // ⌘J / Ctrl+J — przełącz panel. Esc — zamknij (gdy fokus w panelu).
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setOpen((v) => !v);
        return;
      }
      if (e.key === "Escape" && open && !appearanceOpen) {
        const panel = document.querySelector('[data-testid="jarvis-panel"]');
        if (panel && (panel.contains(document.activeElement) || !isTypingTarget(document.activeElement))) {
          setOpen(false);
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [active, open, appearanceOpen]);

  // Otwarcie z palety ⌘K, strony MINDY albo dymka.
  useEffect(() => {
    if (!active) return;
    const onOpen = (e: Event) => {
      const detail = (e as CustomEvent<JarvisOpenDetail>).detail ?? {};
      setOpen(true);
      setView("chat");
      if (detail.prompt) {
        if (detail.send) void send(detail.prompt);
        else setDraft(detail.prompt);
      }
    };
    window.addEventListener(JARVIS_OPEN_EVENT, onOpen);
    return () => window.removeEventListener(JARVIS_OPEN_EVENT, onOpen);
  }, [active, send]);

  // Dzwonek `my_people_match` (useNotifications → zdarzenie okna): Jarvis mówi
  // o nowej rekrutacji i po kliknięciu pyta sam siebie, kogo przepiąć. Tylko
  // gdy działa (bez modelu kliknięcie nie miałoby czego zrobić) i na żywo —
  // przegapione dopasowania zbiera poranny skrót.
  useEffect(() => {
    if (!active || !available || !prefs.enabled) return;
    const onMatch = (e: Event) => {
      const detail = (e as CustomEvent<MyPeopleMatchEventDetail>).detail;
      if (!detail) return;
      const jobId = jobIdFromMatchLink(detail.link);
      setNudge({
        text: `${detail.title}. Kliknij, podpowiem, kogo przepiąć.`,
        prompt: reassignPrompt(jobId),
      });
    };
    window.addEventListener(MY_PEOPLE_MATCH_EVENT, onMatch);
    return () => window.removeEventListener(MY_PEOPLE_MATCH_EVENT, onMatch);
  }, [active, available, prefs.enabled]);

  // Poranny skrót dnia — BEZ modelu: liczby z istniejących tras, raz dziennie.
  const briefKey = storageKey(user?.id, "brief");
  useEffect(() => {
    if (!active || !available || !prefs.daily_brief || !user) return;
    if (readStorage(briefKey) === todayKey()) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const parts: string[] = [];
      try {
        const { data } = await api.get<{ count: number }>("/api/notifications/count");
        if (data.count > 0) parts.push(`${data.count} ${data.count === 1 ? "nowe powiadomienie" : "nowe powiadomienia"}`);
      } catch {
        /* skrót jest dodatkiem */
      }
      if (hasSectionAccess(user, "pipeline")) {
        try {
          const day = todayKey();
          const { data } = await api.get<unknown[]>("/api/calendar/events", {
            params: { from_date: `${day}T00:00:00`, to_date: `${day}T23:59:59`, mine_only: true, limit: 50 },
          });
          if (Array.isArray(data) && data.length > 0) {
            parts.push(`${data.length} ${data.length === 1 ? "wydarzenie" : "wydarzenia"} w kalendarzu`);
          }
        } catch {
          /* jw. */
        }
      }
      const dlRole = hasRole(user, "admin", "head_of_recruitment", "delivery_lead", "finance");
      if (dlRole && hasSectionAccess(user, "delivery")) {
        try {
          const { data } = await api.get<{ total: number }>("/api/dl-alerts/cards");
          if (data.total > 0) parts.push(`${data.total} ${data.total === 1 ? "sprawa klienta" : "sprawy klientów"}`);
        } catch {
          /* jw. */
        }
      }
      if (hasCapability(user, "nav.my_people")) {
        try {
          const { data } = await api.get<MyPeopleSummary>("/api/my-people/summary");
          parts.push(...briefFragments(data));
        } catch {
          /* jw. */
        }
      }
      if (cancelled) return;
      writeStorage(briefKey, todayKey());
      if (parts.length > 0) setBrief(`Na dziś: ${parts.join(", ")}. Kliknij, a podpowiem, od czego zacząć.`);
    }, 4000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [active, available, prefs.daily_brief, user, briefKey]);

  const suggestions = useMemo(
    () => suggestionsFor(screenFromLocation(pathname, typeof window !== "undefined" ? window.location.search : "")),
    [pathname],
  );

  if (!active) return null;

  const unavailableNote =
    status && !status.available
      ? status.reason === "impersonation"
        ? "Asystent jest niedostępny w trybie podglądu jako inny użytkownik."
        : "Asystent jest chwilowo wyłączony. Wszystko inne w NEXUSIE działa normalnie."
      : null;
  const softLimitNote =
    status && status.available && status.used_today >= status.soft_limit
      ? `Dziś to już ${status.used_today} pytań — to dużo. Asystent działa dalej, ale każde pytanie kosztuje.`
      : null;
  const showMascot = (available && prefs.enabled) || kidsMode;
  const webRemaining =
    status?.web_enabled && typeof status.web_limit === "number"
      ? Math.max(0, status.web_limit - (status.web_used_today ?? 0))
      : null;
  const webUnavailableReason = !status?.web_enabled
    ? "Wyszukiwanie w internecie jest wyłączone"
    : webRemaining === 0
      ? "Dzisiejszy limit wyszukiwań w internecie jest wyczerpany"
      : null;
  const mood = kids.mood ?? turn.mood;
  const bubble = nudge?.text ?? brief ?? kids.bubble;

  return (
    <>
      {showMascot && (
        <JarvisMascot
          name={prefs.name}
          character={prefs.character}
          accent={prefs.accent}
          mood={streaming ? (turn.mood === "idle" ? "thinking" : turn.mood) : mood}
          minimized={prefs.minimized}
          open={open}
          bubble={bubble}
          attention={Boolean(brief || nudge)}
          onToggle={() => setOpen((v) => !v)}
          onBubbleClick={() => {
            const wasBrief = Boolean(brief);
            const pending = nudge;
            setNudge(null);
            setBrief(null);
            kids.dismiss();
            setOpen(true);
            if (pending && available) void send(pending.prompt);
            else if (wasBrief && available) void send("Co mam dziś do zrobienia? Zacznij od najpilniejszego.");
          }}
          onDismissBubble={() => {
            setNudge(null);
            setBrief(null);
            kids.dismiss();
          }}
        />
      )}
      {open && (
        <JarvisPanel
          name={prefs.name}
          character={prefs.character}
          accent={prefs.accent}
          mood={turn.mood}
          view={view}
          items={turn.items}
          thinking={turn.thinking}
          streaming={streaming}
          draft={draft}
          suggestions={suggestions}
          conversations={conversationsQuery.data}
          conversationsLoading={conversationsQuery.isLoading}
          activeConversationId={turn.conversationId}
          softLimitNote={softLimitNote}
          unavailableNote={statusQuery.isError ? "Nie udało się sprawdzić, czy asystent działa. Spróbuj za chwilę." : unavailableNote}
          busyActionId={busyActionId}
          webMode={webMode}
          webRemaining={webRemaining}
          webUnavailableReason={webUnavailableReason}
          onToggleWeb={() => setWebMode((v) => !v)}
          onDraftChange={setDraft}
          onSend={(m) => void send(m)}
          onNewChat={newChat}
          onShowHistory={() => setView("history")}
          onBackToChat={() => setView("chat")}
          onSelectConversation={selectConversation}
          onDeleteConversation={(id) => removeConversation.mutate(id)}
          onOpenAppearance={() => setAppearanceOpen(true)}
          onClose={() => setOpen(false)}
          onConfirm={(a) => void decide(a, "confirm")}
          onReject={(a) => void decide(a, "reject")}
          onNavigate={() => {
            if (typeof window !== "undefined" && window.innerWidth < 640) setOpen(false);
          }}
        />
      )}
      <JarvisAppearanceDialog
        open={appearanceOpen}
        onOpenChange={setAppearanceOpen}
        prefs={prefs}
        saving={savePrefs.isPending}
        error={savePrefs.isError ? apiErrorMessage(savePrefs.error, "Nie udało się zapisać wyglądu.") : null}
        onSave={(next) => savePrefs.mutate(next)}
      />
    </>
  );
}
