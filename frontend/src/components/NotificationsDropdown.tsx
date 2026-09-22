"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useClickOutside } from "@/lib/use-click-outside";
import { useRouter } from "next/navigation";
import {
  keepPreviousData,
  useQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Bell,
  CheckCheck,
  X,
  Calendar,
  FileText,
  UserPlus,
  GitBranch,
  Inbox,
  ClockAlert,
  MessageSquareWarning,
  PhoneOff,
  StickyNote,
  Hourglass,
  Phone,
  PhoneCall,
  AlertTriangle,
  ChevronRight,
  Store,
  Sparkles,
  CalendarClock,
  AtSign,
  MessageSquare,
  BellRing,
  Target,
  Wallet,
  Users,
  FileSignature,
  FileCheck2,
  FileX2,
  Mail,
  MailX,
  MailCheck,
  KeyRound,
  Search,
  ShieldAlert,
  Package,
  ListChecks,
  Workflow,
  ClipboardList,
  Send,
} from "lucide-react";
import { notificationsApi } from "@/lib/api";
import {
  NOTIFICATIONS_FALLBACK_POLL_MS,
  WS_BACKED_SAFETY_POLL_MS,
} from "@/lib/polling";
import { cn } from "@/lib/utils";
import {
  formatNotificationText,
  notificationOnBehalfLabel,
  notificationTimeAgo,
} from "@/lib/notification-format";
import {
  NOTIFICATIONS_INITIAL_LIMIT,
  canShowMoreNotifications,
  nextNotificationsLimit,
  shownNotificationsLimit,
} from "@/lib/notifications-paging";
import { useNotifications, WsNotification } from "@/hooks/useNotifications";
import { InterviewFeedbackModal } from "@/components/feedback/InterviewFeedbackModal";
import { useAuthStore } from "@/store/auth";

type Notification = {
  id: number;
  user_id: number;
  title: string;
  message: string;
  link?: string | null;
  notification_type: string;
  is_read: boolean;
  created_at?: string | null;
  on_behalf_of_name?: string | null;
};

const TYPE_CONFIG: Record<
  string,
  { icon: React.ReactNode; color: string; bgColor: string }
> = {
  contract_ending: {
    icon: <FileText className="w-3.5 h-3.5" />,
    color: "text-orange-600",
    bgColor: "bg-orange-100",
  },
  interview_scheduled: {
    icon: <Calendar className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  candidate_added: {
    icon: <UserPlus className="w-3.5 h-3.5" />,
    color: "text-green-600",
    bgColor: "bg-green-100",
  },
  stage_changed: {
    icon: <GitBranch className="w-3.5 h-3.5" />,
    color: "text-purple-600",
    bgColor: "bg-purple-100",
  },
  new_application: {
    icon: <Inbox className="w-3.5 h-3.5" />,
    color: "text-cyan-600",
    bgColor: "bg-cyan-100",
  },
  // Phase 13 — automatyczne triggery
  dl_stage_stale_6h: {
    icon: <ClockAlert className="w-3.5 h-3.5" />,
    color: "text-amber-600",
    bgColor: "bg-amber-100",
  },
  client_feedback_eobd: {
    icon: <MessageSquareWarning className="w-3.5 h-3.5" />,
    color: "text-rose-600",
    bgColor: "bg-rose-100",
  },
  powercalling_kpi: {
    icon: <PhoneOff className="w-3.5 h-3.5" />,
    color: "text-destructive",
    bgColor: "bg-destructive/15",
  },
  candidate_feedback_1h: {
    icon: <StickyNote className="w-3.5 h-3.5" />,
    color: "text-indigo-600",
    bgColor: "bg-indigo-100",
  },
  stage_stuck_7d: {
    icon: <Hourglass className="w-3.5 h-3.5" />,
    color: "text-muted-foreground",
    bgColor: "bg-muted",
  },
  // Phase 14 — post-interview feedback chain
  post_interview_t15: {
    icon: <Phone className="w-3.5 h-3.5" />,
    color: "text-indigo-600",
    bgColor: "bg-indigo-100",
  },
  post_interview_t45: {
    icon: <PhoneCall className="w-3.5 h-3.5" />,
    color: "text-amber-600",
    bgColor: "bg-amber-100",
  },
  post_interview_t2h_escalation: {
    icon: <AlertTriangle className="w-3.5 h-3.5" />,
    color: "text-destructive",
    bgColor: "bg-destructive/15",
  },
  suggest_next_step: {
    icon: <ChevronRight className="w-3.5 h-3.5" />,
    color: "text-emerald-600",
    bgColor: "bg-emerald-100",
  },
  // Auto-match: system sam dodał kandydata do pipeline'u rekrutacji (etap Ogłoszenia)
  auto_match: {
    icon: <Sparkles className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/10",
  },
  // „Moi ludzie" — nowa rekrutacja pasuje do osób z listy rekrutera.
  my_people_match: {
    icon: <Users className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/10",
  },
  // Targ kandydatów — nowy projekt dopasował się do kandydata w puli marketplace
  marketplace_match: {
    icon: <Store className="w-3.5 h-3.5" />,
    color: "text-teal-600",
    bgColor: "bg-teal-100",
  },
  // Szybkie przepinanie — nowy request podobny do historycznych z gotowymi
  // kandydatami (link prowadzi do /jobs/{id}?tab=similar).
  similar_job_candidates: {
    icon: <Sparkles className="w-3.5 h-3.5" />,
    color: "text-indigo-600",
    bgColor: "bg-indigo-100",
  },
  // Deadline rekrutacji zbliża się (Job.deadline) — 7/3/1 dni. Link → /jobs/{id}.
  // Eskalacja pilności: neutralny → amber → destructive.
  job_deadline_7d: {
    icon: <Hourglass className="w-3.5 h-3.5" />,
    color: "text-muted-foreground",
    bgColor: "bg-muted",
  },
  job_deadline_3d: {
    icon: <Hourglass className="w-3.5 h-3.5" />,
    color: "text-amber-600",
    bgColor: "bg-amber-100",
  },
  job_deadline_1d: {
    icon: <AlertTriangle className="w-3.5 h-3.5" />,
    color: "text-destructive",
    bgColor: "bg-destructive/15",
  },
  // Finanse → Braki: zamówienie zakończone bez kolejnego zamówienia.
  order_missing_successor: {
    icon: <AlertTriangle className="w-3.5 h-3.5" />,
    color: "text-amber-600",
    bgColor: "bg-amber-100",
  },
  // Typy, które do 09.2026 dziedziczyły ikonę „nowy kandydat" (32 z 53).
  // Kolory na tokenach DS: primary = informacja, warning = do zrobienia,
  // destructive = porażka/eskalacja, success = domknięte.
  note_mention: {
    icon: <AtSign className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  job_chat_mention: {
    icon: <AtSign className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  job_chat_message: {
    icon: <MessageSquare className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  saved_search_match: {
    icon: <Search className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  match_digest: {
    icon: <ListChecks className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  champion_profile_updated: {
    icon: <ClipboardList className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  stage_rule: {
    icon: <Workflow className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  kpi_coach: {
    icon: <Target className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  recruitment_allocation_alert: {
    icon: <Users className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  pending_verification: {
    icon: <ClockAlert className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  ai_spend_alert: {
    icon: <Wallet className="w-3.5 h-3.5" />,
    color: "text-destructive",
    bgColor: "bg-destructive/15",
  },
  rejection_email_scheduled: {
    icon: <Mail className="w-3.5 h-3.5" />,
    color: "text-muted-foreground",
    bgColor: "bg-muted",
  },
  rejection_email_sent: {
    icon: <MailCheck className="w-3.5 h-3.5" />,
    color: "text-success",
    bgColor: "bg-success/15",
  },
  rejection_email_cancelled: {
    icon: <MailX className="w-3.5 h-3.5" />,
    color: "text-muted-foreground",
    bgColor: "bg-muted",
  },
  rejection_email_skipped: {
    icon: <MailX className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  rejection_email_failed: {
    icon: <MailX className="w-3.5 h-3.5" />,
    color: "text-destructive",
    bgColor: "bg-destructive/15",
  },
  signature_sent: {
    icon: <FileSignature className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  signature_signed: {
    icon: <FileCheck2 className="w-3.5 h-3.5" />,
    color: "text-success",
    bgColor: "bg-success/15",
  },
  signature_rejected: {
    icon: <FileX2 className="w-3.5 h-3.5" />,
    color: "text-destructive",
    bgColor: "bg-destructive/15",
  },
  signature_failed: {
    icon: <FileX2 className="w-3.5 h-3.5" />,
    color: "text-destructive",
    bgColor: "bg-destructive/15",
  },
  contract_activated: {
    icon: <FileCheck2 className="w-3.5 h-3.5" />,
    color: "text-success",
    bgColor: "bg-success/15",
  },
  contract_ending_90d: {
    icon: <FileText className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  framework_contract_signed: {
    icon: <FileCheck2 className="w-3.5 h-3.5" />,
    color: "text-success",
    bgColor: "bg-success/15",
  },
  framework_contract_expiring_30d: {
    icon: <FileText className="w-3.5 h-3.5" />,
    color: "text-muted-foreground",
    bgColor: "bg-muted",
  },
  framework_contract_expiring_14d: {
    icon: <FileText className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  framework_contract_expiring_7d: {
    icon: <AlertTriangle className="w-3.5 h-3.5" />,
    color: "text-destructive",
    bgColor: "bg-destructive/15",
  },
  client_order_ending_30d: {
    icon: <Package className="w-3.5 h-3.5" />,
    color: "text-muted-foreground",
    bgColor: "bg-muted",
  },
  client_order_ending_14d: {
    icon: <Package className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  client_order_ending_7d: {
    icon: <AlertTriangle className="w-3.5 h-3.5" />,
    color: "text-destructive",
    bgColor: "bg-destructive/15",
  },
  equipment_return_due_14d: {
    icon: <Package className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  password_reset_requested: {
    icon: <KeyRound className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  password_changed_by_admin: {
    icon: <ShieldAlert className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  // Koniec przeglądu całej bazy (Talent Radar / AI Matching w rekrutacji).
  // Link → /jobs/{id}?tab=similar albo /talent-radar.
  // Zapisane wyszukiwanie po migracji na wspólną semantykę filtrów zwraca inny
  // zbiór osób — alert czeka na akceptację właściciela.
  saved_search_reapproval: {
    icon: <Sparkles className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  candidate_search_completed: {
    icon: <Sparkles className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  // 0338: cykl rozmowy u klienta — przekazania DL ↔ rekruter i debrief.
  interview_slots_requested: {
    icon: <CalendarClock className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  interview_slot_chosen: {
    icon: <CalendarClock className="w-3.5 h-3.5" />,
    color: "text-warning",
    bgColor: "bg-warning/15",
  },
  interview_slot_confirmed: {
    icon: <CalendarClock className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  interview_debrief_saved: {
    icon: <CalendarClock className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  // 0348: kolejka „Czeka na Ciebie" — poranny skrót i wytypowanie do Cpro.
  board_tasks_digest: {
    icon: <ListChecks className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
  cpro_send_assigned: {
    icon: <Send className="w-3.5 h-3.5" />,
    color: "text-primary",
    bgColor: "bg-primary/15",
  },
};

/** Nieznany (nowy) typ dostaje neutralny dzwonek, nie ikonę „nowy kandydat". */
const FALLBACK_TYPE_CONFIG = {
  icon: <BellRing className="w-3.5 h-3.5" />,
  color: "text-muted-foreground",
  bgColor: "bg-muted",
};

const POST_INTERVIEW_TYPES = new Set([
  "post_interview_t15",
  "post_interview_t45",
  "post_interview_t2h_escalation",
]);

/** Parse calendar_event id from notif.link like "/calendar?event=11&action=feedback". */
function parseEventIdFromLink(link?: string | null): number | null {
  if (!link) return null;
  const match = /[?&]event=(\d+)/.exec(link);
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isFinite(id) ? id : null;
}

// ── Toast notification for real-time events ───────────────────────────────────
function NotifToast({ notif, onClose }: { notif: WsNotification; onClose: () => void }) {
  return (
    <div className="fixed bottom-6 right-6 z-300 max-w-sm w-full bg-card dark:bg-muted border border-primary/20 dark:border-primary/90 rounded-2xl shadow-2xl p-4 flex items-start gap-3 animate-fadeIn">
      <div className="w-8 h-8 rounded-full bg-primary/15 dark:bg-primary/40 text-primary flex items-center justify-center shrink-0">
        <Bell className="w-4 h-4" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-bold text-foreground dark:text-foreground leading-tight">{formatNotificationText(notif.title)}</p>
        <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-0.5 line-clamp-2">{formatNotificationText(notif.message)}</p>
      </div>
      <button onClick={onClose} className="text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground shrink-0">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

export function NotificationsDropdown() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const authUser = useAuthStore((state) => state.user);
  const scopeCacheKey = `${authUser?.id ?? "anonymous"}:${authUser?.authorization_version ?? "none"}`;
  const [open, setOpen] = useState(false);
  // B51: „Pokaż więcej" podnosi limit (20 → 50 → 200) zamiast doklejać strony —
  // patrz `lib/notifications-paging.ts`.
  const [limit, setLimit] = useState<number>(NOTIFICATIONS_INITIAL_LIMIT);
  const [toastNotif, setToastNotif] = useState<WsNotification | null>(null);
  const [feedbackModal, setFeedbackModal] = useState<{
    eventId: number;
  } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useClickOutside(ref, () => setOpen(false));

  // Jeden slot toasta, ale timer należy do OSTATNIEGO zdarzenia — do 09.2026
  // drugi toast znikał po czasie liczonym od pierwszego.
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleWsNotification = useCallback((notif: WsNotification) => {
    setToastNotif(notif);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => {
      toastTimerRef.current = null;
      setToastNotif(null);
    }, 5000);
  }, []);
  useEffect(
    () => () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    },
    [],
  );

  const {
    unreadCount: wsUnreadDelta,
    clearUnread,
    wsConnected,
  } = useNotifications({
    onNotification: handleWsNotification,
  });

  const { data, isFetching, isPlaceholderData, dataUpdatedAt } = useQuery({
    queryKey: ["notifications", scopeCacheKey, limit],
    queryFn: () => notificationsApi.list(limit).then((r) => r.data),
    // Przy podniesieniu limitu lista nie znika na czas doładowania.
    placeholderData: keepPreviousData,
    // WS inwaliduje ten klucz na każdym zdarzeniu, więc przy zdrowym gnieździe
    // odpytywanie jest tylko siatką bezpieczeństwa. Bez gniazda `useNotifications`
    // i tak inwaliduje co minutę — tu interwał minutowy jest lustrem, żeby
    // klucz nie zależał od kolejności montowania hooków.
    refetchInterval: wsConnected
      ? WS_BACKED_SAFETY_POLL_MS
      : NOTIFICATIONS_FALLBACK_POLL_MS,
  });

  const notifications: Notification[] = data?.items || [];
  const serverUnread: number = data?.unread_count || 0;
  // Show max of server count and live WS delta (resolves after query refresh)
  const unreadCount = Math.max(serverUnread, wsUnreadDelta);
  // Delta z gniazda jest potrzebna tylko do najbliższego odświeżenia listy —
  // potem licznik serwera już ją zawiera. Bez zerowania zostawał widmowy
  // licznik po przeczytaniu powiadomień w innej karcie.
  const clearUnreadRef = useRef(clearUnread);
  clearUnreadRef.current = clearUnread;
  useEffect(() => {
    if (dataUpdatedAt) clearUnreadRef.current();
  }, [dataUpdatedAt]);
  const shownLimit = shownNotificationsLimit(limit, isPlaceholderData);

  const markReadMutation = useMutation({
    mutationFn: (id: number) => notificationsApi.markRead(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      clearUnread();
    },
  });

  const markAllMutation = useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      clearUnread();
    },
  });

  const handleNotificationClick = (notif: Notification) => {
    if (!notif.is_read) {
      markReadMutation.mutate(notif.id);
    }
    // Phase 14 — post-interview notifications open feedback modal in-place
    // instead of navigating, so the user can collect feedback right after the call.
    if (POST_INTERVIEW_TYPES.has(notif.notification_type)) {
      const eventId = parseEventIdFromLink(notif.link);
      if (eventId) {
        setFeedbackModal({ eventId });
        setOpen(false);
        return;
      }
    }
    if (notif.link) {
      router.push(notif.link);
    }
    setOpen(false);
  };

  const handleOpen = () => {
    setOpen((v) => !v);
    if (!open) clearUnread();
  };

  return (
    <>
      <div ref={ref} className="relative">
        {/* Bell button */}
        <button
          onClick={handleOpen}
          className={cn(
            "relative p-2 rounded-lg transition-colors",
            open ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"
          )}
          aria-label="Powiadomienia"
        >
          <Bell className="w-5 h-5" />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] bg-destructive text-white text-xs font-bold rounded-full flex items-center justify-center px-1">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </button>

        {/* Dropdown */}
        {open && (
          <div className="absolute right-0 top-full mt-2 w-96 bg-card dark:bg-muted border border-border dark:border-border rounded-2xl shadow-xl z-50 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border dark:border-border">
              <div className="flex items-center gap-2">
                <Bell className="w-4 h-4 text-muted-foreground" />
                <span className="font-bold text-foreground dark:text-foreground text-sm">Powiadomienia</span>
                {unreadCount > 0 && (
                  <span className="px-1.5 py-0.5 bg-destructive/15 text-destructive text-xs font-bold rounded-full">
                    {unreadCount}
                  </span>
                )}
              </div>
              {/* „Oznacz wszystko” oznacza tylko WŁASNE — przy samych
                  przypomnieniach w zastępstwie klik nic by nie zmienił. */}
              {unreadCount > 0 && (data?.own_unread_count ?? unreadCount) > 0 && (
                <button
                  onClick={() => markAllMutation.mutate()}
                  disabled={markAllMutation.isPending}
                  className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 font-medium transition-colors"
                >
                  <CheckCheck className="w-3.5 h-3.5" />
                  Oznacz wszystko jako przeczytane
                </button>
              )}
            </div>

            {/* List */}
            <div className="max-h-[420px] overflow-y-auto">
              {notifications.length === 0 ? (
                <div className="text-center py-10 text-muted-foreground">
                  <Bell className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p className="text-sm">Brak powiadomień</p>
                </div>
              ) : (
                <ul>
                  {notifications.map((notif) => {
                    const cfg = TYPE_CONFIG[notif.notification_type] || FALLBACK_TYPE_CONFIG;
                    const onBehalf = notificationOnBehalfLabel(notif);
                    return (
                      <li key={notif.id} className="border-b border-border last:border-b-0">
                        <div
                          role="button"
                          tabIndex={0}
                          onClick={() => handleNotificationClick(notif)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              handleNotificationClick(notif);
                            }
                          }}
                          className={cn(
                            "flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors hover:bg-muted dark:hover:bg-muted focus:outline-hidden focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                            !notif.is_read && "bg-primary/10 dark:bg-primary/10"
                          )}
                        >
                        {/* Icon */}
                        <div
                          className={cn(
                            "w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5",
                            cfg.bgColor,
                            cfg.color
                          )}
                        >
                          {cfg.icon}
                        </div>

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-start justify-between gap-2">
                            <p
                              className={cn(
                                "text-sm leading-tight",
                                notif.is_read ? "font-medium text-foreground dark:text-muted-foreground" : "font-bold text-foreground dark:text-foreground"
                              )}
                            >
                              {formatNotificationText(notif.title)}
                            </p>
                            {!notif.is_read && (
                              <div className="w-2 h-2 bg-primary rounded-full shrink-0 mt-1.5" />
                            )}
                          </div>
                          <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-0.5 line-clamp-2 leading-relaxed">
                            {formatNotificationText(notif.message)}
                          </p>
                          {onBehalf && (
                            <p className="text-xs font-medium text-warning mt-0.5">{onBehalf}</p>
                          )}
                          <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-1">{notificationTimeAgo(notif.created_at)}</p>
                        </div>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            {/* Footer */}
            {notifications.length > 0 && (
              <div className="border-t border-border dark:border-border px-4 py-2 flex items-center justify-center gap-4">
                {canShowMoreNotifications(notifications.length, shownLimit) ? (
                  <button
                    type="button"
                    onClick={() => {
                      const next = nextNotificationsLimit(limit);
                      if (next !== null) setLimit(next);
                    }}
                    disabled={isFetching}
                    className="text-xs text-primary hover:text-primary/80 font-medium transition-colors disabled:opacity-50"
                  >
                    {isFetching ? "Ładowanie…" : "Pokaż więcej"}
                  </button>
                ) : (
                  notifications.length >= shownLimit && (
                    <span className="text-xs text-muted-foreground">
                      Pokazano {shownLimit} najnowszych
                    </span>
                  )
                )}
                <button
                  onClick={() => setOpen(false)}
                  className="text-xs text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground transition-colors"
                >
                  Zamknij
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Real-time toast notification */}
      {toastNotif && (
        <NotifToast notif={toastNotif} onClose={() => setToastNotif(null)} />
      )}

      {/* Phase 14 — Feedback modal triggered by post_interview_* notifications */}
      {feedbackModal && (
        <InterviewFeedbackModal
          open={true}
          onOpenChange={(o) => !o && setFeedbackModal(null)}
          calendarEventId={feedbackModal.eventId}
        />
      )}
    </>
  );
}
