"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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
} from "lucide-react";
import { notificationsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useNotifications, WsNotification } from "@/hooks/useNotifications";
import { InterviewFeedbackModal } from "@/components/feedback/InterviewFeedbackModal";

type Notification = {
  id: number;
  user_id: number;
  title: string;
  message: string;
  link?: string;
  notification_type: string;
  is_read: boolean;
  created_at?: string;
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
    color: "text-blue-600",
    bgColor: "bg-blue-100",
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
    color: "text-red-600",
    bgColor: "bg-red-100",
  },
  candidate_feedback_1h: {
    icon: <StickyNote className="w-3.5 h-3.5" />,
    color: "text-indigo-600",
    bgColor: "bg-indigo-100",
  },
  stage_stuck_7d: {
    icon: <Hourglass className="w-3.5 h-3.5" />,
    color: "text-gray-600",
    bgColor: "bg-gray-100",
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
    color: "text-red-600",
    bgColor: "bg-red-100",
  },
  suggest_next_step: {
    icon: <ChevronRight className="w-3.5 h-3.5" />,
    color: "text-emerald-600",
    bgColor: "bg-emerald-100",
  },
  // Targ kandydatów — nowy projekt dopasował się do kandydata w puli marketplace
  marketplace_match: {
    icon: <Store className="w-3.5 h-3.5" />,
    color: "text-teal-600",
    bgColor: "bg-teal-100",
  },
};

const POST_INTERVIEW_TYPES = new Set([
  "post_interview_t15",
  "post_interview_t45",
  "post_interview_t2h_escalation",
]);

/** Parse calendar_event id from notif.link like "/calendar?event=11&action=feedback". */
function parseEventIdFromLink(link?: string): number | null {
  if (!link) return null;
  const match = /[?&]event=(\d+)/.exec(link);
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isFinite(id) ? id : null;
}

function timeAgo(iso?: string): string {
  if (!iso) return "";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return "Przed chwilą";
  if (diff < 3600) return `${Math.floor(diff / 60)} min temu`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h temu`;
  return `${Math.floor(diff / 86400)} dni temu`;
}

// ── Toast notification for real-time events ───────────────────────────────────
function NotifToast({ notif, onClose }: { notif: WsNotification; onClose: () => void }) {
  return (
    <div className="fixed bottom-6 right-6 z-[300] max-w-sm w-full bg-white dark:bg-gray-800 border border-blue-200 dark:border-blue-700 rounded-2xl shadow-2xl p-4 flex items-start gap-3 animate-fadeIn">
      <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-600 flex items-center justify-center flex-shrink-0">
        <Bell className="w-4 h-4" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-bold text-gray-900 dark:text-gray-100 leading-tight">{notif.title}</p>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">{notif.message}</p>
      </div>
      <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 flex-shrink-0">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

export function NotificationsDropdown() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [toastNotif, setToastNotif] = useState<WsNotification | null>(null);
  const [feedbackModal, setFeedbackModal] = useState<{
    eventId: number;
  } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleWsNotification = useCallback((notif: WsNotification) => {
    setToastNotif(notif);
    setTimeout(() => setToastNotif(null), 5000);
  }, []);

  const { unreadCount: wsUnreadDelta, clearUnread } = useNotifications({
    onNotification: handleWsNotification,
  });

  const { data } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => notificationsApi.list(20).then((r) => r.data),
    // WS invalidates cache on new events. 30s poll is safety net + fallback.
    refetchInterval: 30_000,
  });

  const notifications: Notification[] = data?.items || [];
  const serverUnread: number = data?.unread_count || 0;
  // Show max of server count and live WS delta (resolves after query refresh)
  const unreadCount = Math.max(serverUnread, wsUnreadDelta);

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
            open ? "bg-blue-50 text-blue-600" : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
          )}
          aria-label="Powiadomienia"
        >
          <Bell className="w-5 h-5" />
          {unreadCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] bg-red-500 text-white text-xs font-bold rounded-full flex items-center justify-center px-1">
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </button>

        {/* Dropdown */}
        {open && (
          <div className="absolute right-0 top-full mt-2 w-96 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-2xl shadow-xl z-50 overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-700">
              <div className="flex items-center gap-2">
                <Bell className="w-4 h-4 text-gray-500" />
                <span className="font-bold text-gray-900 dark:text-gray-100 text-sm">Powiadomienia</span>
                {unreadCount > 0 && (
                  <span className="px-1.5 py-0.5 bg-red-100 text-red-600 text-xs font-bold rounded-full">
                    {unreadCount}
                  </span>
                )}
              </div>
              {unreadCount > 0 && (
                <button
                  onClick={() => markAllMutation.mutate()}
                  disabled={markAllMutation.isPending}
                  className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 font-medium transition-colors"
                >
                  <CheckCheck className="w-3.5 h-3.5" />
                  Oznacz wszystko jako przeczytane
                </button>
              )}
            </div>

            {/* List */}
            <div className="max-h-[420px] overflow-y-auto">
              {notifications.length === 0 ? (
                <div className="text-center py-10 text-gray-400">
                  <Bell className="w-8 h-8 mx-auto mb-2 opacity-30" />
                  <p className="text-sm">Brak powiadomień</p>
                </div>
              ) : (
                <ul>
                  {notifications.map((notif) => {
                    const cfg = TYPE_CONFIG[notif.notification_type] || TYPE_CONFIG.candidate_added;
                    return (
                      <li
                        key={notif.id}
                        onClick={() => handleNotificationClick(notif)}
                        className={cn(
                          "flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors hover:bg-gray-50 dark:hover:bg-gray-700 border-b border-gray-50 dark:border-gray-700 last:border-b-0",
                          !notif.is_read && "bg-blue-50/40 dark:bg-blue-900/10"
                        )}
                      >
                        {/* Icon */}
                        <div
                          className={cn(
                            "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5",
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
                                notif.is_read ? "font-medium text-gray-700 dark:text-gray-300" : "font-bold text-gray-900 dark:text-gray-100"
                              )}
                            >
                              {notif.title}
                            </p>
                            {!notif.is_read && (
                              <div className="w-2 h-2 bg-blue-500 rounded-full flex-shrink-0 mt-1.5" />
                            )}
                          </div>
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2 leading-relaxed">
                            {notif.message}
                          </p>
                          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">{timeAgo(notif.created_at)}</p>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            {/* Footer */}
            {notifications.length > 0 && (
              <div className="border-t border-gray-100 dark:border-gray-700 px-4 py-2 text-center">
                <button
                  onClick={() => setOpen(false)}
                  className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
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
