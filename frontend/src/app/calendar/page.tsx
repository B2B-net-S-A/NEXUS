"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Calendar,
  ChevronLeft,
  ChevronRight,
  Plus,
  X,
  Clock,
  MapPin,
  Users,
  Link as LinkIcon,
  User,
  Briefcase,
  Building2,
  Video,
  Phone,
  CheckCircle,
  AlertCircle,
  Download,
  Loader2,
} from "lucide-react";
import api, { calendarApi, candidatesApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { ConfirmButton } from "@/components/ConfirmDialog";

// ── Constants ─────────────────────────────────────────────────────────────────

const EVENT_TYPE_CONFIG: Record<
  string,
  { label: string; color: string; bgColor: string; borderColor: string; dotColor: string }
> = {
  interview: {
    label: "Rozmowa kwalifikacyjna",
    color: "text-primary",
    bgColor: "bg-primary/15",
    borderColor: "border-primary/30",
    dotColor: "bg-primary",
  },
  screening: {
    label: "Screening",
    color: "text-green-700",
    bgColor: "bg-green-100",
    borderColor: "border-green-300",
    dotColor: "bg-green-500",
  },
  prep_call: {
    label: "Prep Call",
    color: "text-purple-700",
    bgColor: "bg-purple-100",
    borderColor: "border-purple-300",
    dotColor: "bg-purple-500",
  },
  meeting: {
    label: "Spotkanie",
    color: "text-foreground",
    bgColor: "bg-muted",
    borderColor: "border-border",
    dotColor: "bg-gray-400",
  },
  deadline: {
    label: "Deadline",
    color: "text-destructive",
    bgColor: "bg-destructive/15",
    borderColor: "border-red-300",
    dotColor: "bg-destructive/100",
  },
};

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  scheduled: { label: "Zaplanowane", color: "bg-primary/15 text-primary" },
  completed: { label: "Zakończone", color: "bg-green-100 text-green-700" },
  cancelled: { label: "Anulowane", color: "bg-destructive/15 text-destructive" },
};

const HOURS = Array.from({ length: 13 }, (_, i) => i + 8); // 8:00 – 20:00

const DAY_NAMES = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Nd"];
const DAY_NAMES_FULL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"];

type CalendarEvent = {
  id: number;
  title: string;
  description?: string;
  event_type: string;
  start_time: string;
  end_time?: string;
  all_day: boolean;
  candidate_id?: number;
  candidate_name?: string;
  job_id?: number;
  job_title?: string;
  client_id?: number;
  client_name?: string;
  attendees?: string[];
  location?: string;
  teams_link?: string;
  reminder_minutes: number;
  status: string;
  created_at?: string;
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function getMonday(date: Date): Date {
  const d = new Date(date);
  const day = d.getDay();
  const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

function formatHour(h: number): string {
  return `${h.toString().padStart(2, "0")}:00`;
}

function getWeekDays(monday: Date): Date[] {
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday);
    d.setDate(d.getDate() + i);
    return d;
  });
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

function parseTime(iso: string): Date {
  return new Date(iso);
}

function getEventTop(start: Date): number {
  const h = start.getHours() + start.getMinutes() / 60;
  return Math.max(0, (h - 8) * 56); // 56px per hour
}

function getEventHeight(start: Date, end: Date | null): number {
  if (!end) return 56;
  const diffMs = end.getTime() - start.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);
  return Math.max(28, diffHours * 56);
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function CalendarPage() {
  const queryClient = useQueryClient();
  const [currentMonday, setCurrentMonday] = useState<Date>(() => getMonday(new Date()));
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [prefilledStart, setPrefilledStart] = useState<string>("");

  const weekDays = getWeekDays(currentMonday);
  const today = new Date();

  // Fetch events for this week
  const fromDate = currentMonday.toISOString();
  const toDate = new Date(currentMonday.getTime() + 7 * 24 * 60 * 60 * 1000).toISOString();

  const { data: events = [], isLoading } = useQuery<CalendarEvent[]>({
    queryKey: ["calendar-events", fromDate],
    queryFn: () =>
      calendarApi.listEvents({ from_date: fromDate, to_date: toDate }).then((r) => r.data),
  });

  const prevWeek = () => {
    setCurrentMonday((d) => {
      const nd = new Date(d);
      nd.setDate(nd.getDate() - 7);
      return nd;
    });
  };

  const nextWeek = () => {
    setCurrentMonday((d) => {
      const nd = new Date(d);
      nd.setDate(nd.getDate() + 7);
      return nd;
    });
  };

  const goToday = () => {
    setCurrentMonday(getMonday(new Date()));
  };

  const handleSlotClick = (day: Date, hour: number) => {
    const d = new Date(day);
    d.setHours(hour, 0, 0, 0);
    // Format as local datetime-local string
    const y = d.getFullYear();
    const mo = String(d.getMonth() + 1).padStart(2, "0");
    const da = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    setPrefilledStart(`${y}-${mo}-${da}T${h}:${mi}`);
    setShowCreateModal(true);
  };

  const monthLabel = currentMonday.toLocaleDateString("pl-PL", { month: "long", year: "numeric" });

  return (
    <div className="flex gap-0 h-[calc(100vh-140px)] overflow-hidden">
      {/* ── Sidebar ── */}
      <CalendarSidebar
        today={today}
        events={events}
        onCreateClick={() => { setPrefilledStart(""); setShowCreateModal(true); }}
      />

      {/* ── Main calendar ── */}
      <div className="flex-1 flex flex-col overflow-hidden bg-card dark:bg-muted border border-border dark:border-border rounded-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border dark:border-border flex-shrink-0">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-bold text-foreground dark:text-foreground capitalize">{monthLabel}</h1>
            <div className="flex items-center gap-1">
              <button
                onClick={prevWeek}
                className="p-1.5 hover:bg-muted rounded-lg transition-colors text-muted-foreground"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button
                onClick={nextWeek}
                className="p-1.5 hover:bg-muted rounded-lg transition-colors text-muted-foreground"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
            <button
              onClick={goToday}
              className="text-xs font-medium px-3 py-1 bg-primary/10 text-primary hover:bg-primary/15 rounded-lg transition-colors"
            >
              Dzisiaj
            </button>
          </div>

          {/* Legend */}
          <div className="flex items-center gap-3">
            {Object.entries(EVENT_TYPE_CONFIG).map(([key, cfg]) => (
              <div key={key} className="flex items-center gap-1.5">
                <div className={cn("w-2.5 h-2.5 rounded-full", cfg.dotColor)} />
                <span className="text-xs text-muted-foreground">{cfg.label}</span>
              </div>
            ))}
          </div>

          <ICalImportButton
            onImported={() => {
              queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
            }}
          />
          <button
            onClick={() => { setPrefilledStart(""); setShowCreateModal(true); }}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-sm font-medium rounded-lg hover:bg-primary/90 transition-colors"
          >
            <Plus className="w-4 h-4" />
            Nowe wydarzenie
          </button>
        </div>

        {/* Day headers */}
        <div className="grid grid-cols-[48px_repeat(7,1fr)] border-b border-border dark:border-border flex-shrink-0">
          <div className="border-r border-border" />
          {weekDays.map((day, i) => {
            const isToday = isSameDay(day, today);
            return (
              <div
                key={i}
                className={cn(
                  "text-center py-2 border-r border-border last:border-r-0",
                  isToday && "bg-primary/10"
                )}
              >
                <div className="text-xs text-muted-foreground font-medium">{DAY_NAMES[i]}</div>
                <div
                  className={cn(
                    "text-sm font-bold mx-auto w-7 h-7 flex items-center justify-center rounded-full mt-0.5",
                    isToday
                      ? "bg-primary text-white"
                      : "text-foreground"
                  )}
                >
                  {day.getDate()}
                </div>
              </div>
            );
          })}
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center h-32 text-muted-foreground">
              <div className="w-5 h-5 border-2 border-primary/30 border-t-transparent rounded-full animate-spin mr-2" />
              Ładowanie kalendarza...
            </div>
          ) : (
            <WeekGrid
              hours={HOURS}
              weekDays={weekDays}
              events={events}
              today={today}
              onSlotClick={handleSlotClick}
              onEventClick={setSelectedEvent}
            />
          )}
        </div>
      </div>

      {/* ── Create modal ── */}
      {showCreateModal && (
        <CreateEventModal
          prefilledStart={prefilledStart}
          onClose={() => setShowCreateModal(false)}
          onCreated={() => {
            queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
            setShowCreateModal(false);
          }}
        />
      )}

      {/* ── Detail modal ── */}
      {selectedEvent && (
        <EventDetailModal
          event={selectedEvent}
          onClose={() => setSelectedEvent(null)}
          onDeleted={() => {
            queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
            setSelectedEvent(null);
          }}
        />
      )}
    </div>
  );
}

// ── Week Grid ─────────────────────────────────────────────────────────────────

function WeekGrid({
  hours,
  weekDays,
  events,
  today,
  onSlotClick,
  onEventClick,
}: {
  hours: number[];
  weekDays: Date[];
  events: CalendarEvent[];
  today: Date;
  onSlotClick: (day: Date, hour: number) => void;
  onEventClick: (ev: CalendarEvent) => void;
}) {
  const nowMinutes = today.getHours() * 60 + today.getMinutes();
  const nowTop = ((nowMinutes - 8 * 60) / 60) * 56;

  return (
    <div className="grid grid-cols-[48px_repeat(7,1fr)] relative">
      {/* Hour labels */}
      <div className="border-r border-border">
        {hours.map((h) => (
          <div
            key={h}
            className="h-14 flex items-start justify-end pr-2 pt-0.5 text-xs text-muted-foreground font-medium"
          >
            {formatHour(h)}
          </div>
        ))}
      </div>

      {/* Day columns */}
      {weekDays.map((day, dayIdx) => {
        const isToday = isSameDay(day, today);
        const dayEvents = events.filter((ev) => {
          const evDate = parseTime(ev.start_time);
          return isSameDay(evDate, day);
        });

        return (
          <div
            key={dayIdx}
            className={cn(
              "relative border-r border-border last:border-r-0",
              isToday && "bg-primary/10/30"
            )}
          >
            {/* Hour slots */}
            {hours.map((h) => (
              <div
                key={h}
                className="h-14 border-b border-gray-50 hover:bg-primary/10/40 cursor-pointer transition-colors"
                onClick={() => onSlotClick(day, h)}
              />
            ))}

            {/* Today line */}
            {isToday && nowTop >= 0 && nowTop < hours.length * 56 && (
              <div
                className="absolute left-0 right-0 z-10 pointer-events-none"
                style={{ top: `${nowTop}px` }}
              >
                <div className="flex items-center">
                  <div className="w-2 h-2 rounded-full bg-destructive/100 -ml-1" />
                  <div className="flex-1 h-px bg-red-400" />
                </div>
              </div>
            )}

            {/* Events */}
            {dayEvents.map((ev) => {
              const start = parseTime(ev.start_time);
              const end = ev.end_time ? parseTime(ev.end_time) : null;
              const top = getEventTop(start);
              const height = getEventHeight(start, end);
              const cfg = EVENT_TYPE_CONFIG[ev.event_type] || EVENT_TYPE_CONFIG.meeting;

              return (
                <div
                  key={ev.id}
                  className={cn(
                    "absolute left-1 right-1 rounded-lg border px-2 py-1 cursor-pointer overflow-hidden shadow-sm hover:shadow-md transition-shadow z-5",
                    cfg.bgColor,
                    cfg.borderColor,
                    ev.status === "cancelled" && "opacity-50 line-through"
                  )}
                  style={{ top: `${top}px`, height: `${height}px`, minHeight: "28px" }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onEventClick(ev);
                  }}
                >
                  <div className={cn("text-xs font-semibold truncate leading-tight", cfg.color)}>
                    {ev.title}
                  </div>
                  {height > 40 && (
                    <div className="text-xs text-muted-foreground truncate leading-tight">
                      {start.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}
                      {end && ` – ${end.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}`}
                    </div>
                  )}
                  {height > 56 && ev.candidate_name && (
                    <div className="text-xs text-muted-foreground truncate flex items-center gap-1">
                      <User className="w-2.5 h-2.5" />
                      {ev.candidate_name}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function CalendarSidebar({
  today,
  events,
  onCreateClick,
}: {
  today: Date;
  events: CalendarEvent[];
  onCreateClick: () => void;
}) {
  const upcomingEvents = events
    .filter((ev) => {
      const d = new Date(ev.start_time);
      return d >= today && ev.status !== "cancelled";
    })
    .slice(0, 5);

  return (
    <div className="w-64 flex-shrink-0 mr-4 flex flex-col gap-4">
      {/* Create button */}
      <button
        onClick={onCreateClick}
        className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary hover:bg-primary/90 text-white font-semibold rounded-xl transition-colors shadow-sm"
      >
        <Plus className="w-4 h-4" />
        Nowe wydarzenie
      </button>

      {/* Mini calendar */}
      <div className="bg-card dark:bg-muted border border-border dark:border-border rounded-2xl p-4">
        <div className="text-xs font-bold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide mb-3">
          {today.toLocaleDateString("pl-PL", { month: "long", year: "numeric" })}
        </div>
        <MiniCalendar today={today} events={events} />
      </div>

      {/* Upcoming events */}
      {upcomingEvents.length > 0 && (
        <div className="bg-card dark:bg-muted border border-border dark:border-border rounded-2xl p-4">
          <div className="text-xs font-bold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide mb-3">
            Najbliższe
          </div>
          <div className="space-y-2">
            {upcomingEvents.map((ev) => {
              const cfg = EVENT_TYPE_CONFIG[ev.event_type] || EVENT_TYPE_CONFIG.meeting;
              const d = new Date(ev.start_time);
              return (
                <div key={ev.id} className="flex items-start gap-2">
                  <div className={cn("w-2 h-2 rounded-full mt-1.5 flex-shrink-0", cfg.dotColor)} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-foreground truncate">{ev.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {d.toLocaleDateString("pl-PL", { weekday: "short", day: "numeric", month: "short" })}
                      {" "}
                      {d.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="bg-card dark:bg-muted border border-border dark:border-border rounded-2xl p-4">
        <div className="text-xs font-bold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide mb-3">
          Typy wydarzeń
        </div>
        <div className="space-y-2">
          {Object.entries(EVENT_TYPE_CONFIG).map(([key, cfg]) => (
            <div key={key} className="flex items-center gap-2">
              <div className={cn("w-2.5 h-2.5 rounded-full flex-shrink-0", cfg.dotColor)} />
              <span className="text-xs text-muted-foreground">{cfg.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Mini calendar ─────────────────────────────────────────────────────────────

function MiniCalendar({ today, events }: { today: Date; events: CalendarEvent[] }) {
  const year = today.getFullYear();
  const month = today.getMonth();
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const startOffset = firstDay === 0 ? 6 : firstDay - 1;

  const eventDays = new Set(
    events.map((ev) => {
      const d = new Date(ev.start_time);
      return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    })
  );

  const cells: (number | null)[] = [
    ...Array(startOffset).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  return (
    <div>
      <div className="grid grid-cols-7 gap-0.5 mb-1">
        {["P", "W", "Ś", "C", "P", "S", "N"].map((d, i) => (
          <div key={i} className="text-center text-xs text-muted-foreground font-medium">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-0.5">
        {cells.map((day, i) => {
          if (!day) return <div key={i} />;
          const isToday = day === today.getDate();
          const key = `${year}-${month}-${day}`;
          const hasEvents = eventDays.has(key);
          return (
            <div
              key={i}
              className={cn(
                "text-center text-xs py-0.5 rounded-md font-medium relative",
                isToday ? "bg-primary text-white" : "text-muted-foreground hover:bg-muted"
              )}
            >
              {day}
              {hasEvents && !isToday && (
                <div className="absolute bottom-0.5 left-1/2 -translate-x-1/2 w-1 h-1 bg-primary/30 rounded-full" />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Create Event Modal ────────────────────────────────────────────────────────

function CreateEventModal({
  prefilledStart,
  onClose,
  onCreated,
}: {
  prefilledStart: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const queryClient = useQueryClient();

  const [form, setForm] = useState({
    title: "",
    description: "",
    event_type: "meeting",
    start_time: prefilledStart,
    end_time: "",
    all_day: false,
    candidate_id: "",
    job_id: "",
    attendees_raw: "",
    location: "",
    teams_link: "",
    reminder_minutes: "15",
  });

  const [error, setError] = useState<string | null>(null);

  const { data: candidates = [] } = useQuery({
    queryKey: ["candidates-mini"],
    queryFn: () => candidatesApi.list({ page_size: 100 }).then((r) => r.data?.items || []),
  });

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => calendarApi.createEvent(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
      onCreated();
    },
    onError: (e: any) => {
      setError(e.response?.data?.detail || "Błąd tworzenia wydarzenia");
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title.trim() || !form.start_time) {
      setError("Tytuł i czas rozpoczęcia są wymagane");
      return;
    }

    const attendees = form.attendees_raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    mutation.mutate({
      title: form.title.trim(),
      description: form.description || null,
      event_type: form.event_type,
      start_time: new Date(form.start_time).toISOString(),
      end_time: form.end_time ? new Date(form.end_time).toISOString() : null,
      all_day: form.all_day,
      candidate_id: form.candidate_id ? parseInt(form.candidate_id) : null,
      job_id: form.job_id ? parseInt(form.job_id) : null,
      attendees,
      location: form.location || null,
      teams_link: form.teams_link || null,
      reminder_minutes: parseInt(form.reminder_minutes) || 15,
    });
  };

  const typeConfig = EVENT_TYPE_CONFIG[form.event_type] || EVENT_TYPE_CONFIG.meeting;

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center sm:p-4">
      <div className="bg-card dark:bg-muted rounded-2xl sm:rounded-2xl rounded-b-none sm:rounded-b-2xl shadow-2xl w-full sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border">
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-bold text-foreground dark:text-foreground">Nowe wydarzenie</h2>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-muted-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {error}
            </div>
          )}

          {/* Title */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">Tytuł *</label>
            <input
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              placeholder="np. Rozmowa z kandydatem"
            />
          </div>

          {/* Type */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">Typ</label>
            <div className="grid grid-cols-5 gap-1.5">
              {Object.entries(EVENT_TYPE_CONFIG).map(([key, cfg]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setForm({ ...form, event_type: key })}
                  className={cn(
                    "px-2 py-1.5 rounded-lg text-xs font-medium border transition-colors text-center",
                    form.event_type === key
                      ? `${cfg.bgColor} ${cfg.color} ${cfg.borderColor}`
                      : "bg-muted text-muted-foreground border-border hover:bg-muted"
                  )}
                >
                  {cfg.label}
                </button>
              ))}
            </div>
          </div>

          {/* Date/time */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-muted-foreground block mb-1">Od *</label>
              <input
                required
                type="datetime-local"
                value={form.start_time}
                onChange={(e) => setForm({ ...form, start_time: e.target.value })}
                className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-muted-foreground block mb-1">Do</label>
              <input
                type="datetime-local"
                value={form.end_time}
                onChange={(e) => setForm({ ...form, end_time: e.target.value })}
                className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              />
            </div>
          </div>

          {/* Candidate */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">Kandydat (opcjonalnie)</label>
            <select
              value={form.candidate_id}
              onChange={(e) => setForm({ ...form, candidate_id: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
            >
              <option value="">— Wybierz kandydata —</option>
              {candidates.map((c: any) => (
                <option key={c.id} value={c.id}>
                  {c.name} {c.lastname}
                </option>
              ))}
            </select>
          </div>

          {/* Location */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">Lokalizacja</label>
            <input
              value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              placeholder="np. Google Meet, Telefon, Biuro..."
            />
          </div>

          {/* Teams link */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">Link Teams/Meet</label>
            <input
              value={form.teams_link}
              onChange={(e) => setForm({ ...form, teams_link: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              placeholder="https://..."
            />
          </div>

          {/* Attendees */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">
              Uczestnicy (email, oddzielone przecinkiem)
            </label>
            <input
              value={form.attendees_raw}
              onChange={(e) => setForm({ ...form, attendees_raw: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
              placeholder="jan@email.com, anna@email.com"
            />
          </div>

          {/* Description */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">Opis</label>
            <textarea
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring resize-none"
            />
          </div>

          {/* Reminder */}
          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">Przypomnienie</label>
            <select
              value={form.reminder_minutes}
              onChange={(e) => setForm({ ...form, reminder_minutes: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus-visible:ring-ring"
            >
              <option value="5">5 minut przed</option>
              <option value="10">10 minut przed</option>
              <option value="15">15 minut przed</option>
              <option value="30">30 minut przed</option>
              <option value="60">1 godzina przed</option>
            </select>
          </div>

          {/* Buttons */}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
            >
              Anuluj
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="px-5 py-2 bg-primary hover:bg-primary/90 text-white text-sm font-semibold rounded-lg disabled:opacity-50 transition-colors"
            >
              {mutation.isPending ? "Tworzenie..." : "Utwórz wydarzenie"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Event Detail Modal ────────────────────────────────────────────────────────

function EventDetailModal({
  event,
  onClose,
  onDeleted,
}: {
  event: CalendarEvent;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const queryClient = useQueryClient();
  const cfg = EVENT_TYPE_CONFIG[event.event_type] || EVENT_TYPE_CONFIG.meeting;
  const statusCfg = STATUS_CONFIG[event.status] || STATUS_CONFIG.scheduled;

  const deleteMutation = useMutation({
    mutationFn: () => calendarApi.deleteEvent(event.id),
    onSuccess: onDeleted,
  });

  const completeMutation = useMutation({
    mutationFn: () => calendarApi.updateEvent(event.id, { status: "completed" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
      onClose();
    },
  });

  const start = new Date(event.start_time);
  const end = event.end_time ? new Date(event.end_time) : null;

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center sm:p-4">
      <div className="bg-card rounded-2xl shadow-2xl w-full max-w-md">
        {/* Header stripe */}
        <div className={cn("h-1.5 rounded-t-2xl", cfg.dotColor.replace("bg-", "bg-"))} />

        <div className="p-6">
          {/* Title + close */}
          <div className="flex items-start justify-between gap-3 mb-4">
            <div>
              <div
                className={cn(
                  "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold mb-2",
                  cfg.bgColor,
                  cfg.color
                )}
              >
                <div className={cn("w-1.5 h-1.5 rounded-full", cfg.dotColor)} />
                {cfg.label}
              </div>
              <h2 className="text-lg font-bold text-foreground">{event.title}</h2>
            </div>
            <button onClick={onClose} className="text-muted-foreground hover:text-muted-foreground flex-shrink-0">
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Details */}
          <div className="space-y-3">
            {/* Time */}
            <div className="flex items-center gap-3 text-sm text-foreground">
              <Clock className="w-4 h-4 text-muted-foreground flex-shrink-0" />
              <span>
                {start.toLocaleDateString("pl-PL", {
                  weekday: "long",
                  day: "numeric",
                  month: "long",
                })}{" "}
                · {start.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}
                {end && ` – ${end.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}`}
              </span>
            </div>

            {/* Status */}
            <div className="flex items-center gap-3">
              <CheckCircle className="w-4 h-4 text-muted-foreground" />
              <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", statusCfg.color)}>
                {statusCfg.label}
              </span>
            </div>

            {/* Candidate */}
            {event.candidate_name && (
              <div className="flex items-center gap-3 text-sm text-foreground">
                <User className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <span>{event.candidate_name}</span>
              </div>
            )}

            {/* Job */}
            {event.job_title && (
              <div className="flex items-center gap-3 text-sm text-foreground">
                <Briefcase className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <span>{event.job_title}</span>
              </div>
            )}

            {/* Location */}
            {event.location && (
              <div className="flex items-center gap-3 text-sm text-foreground">
                <MapPin className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <span>{event.location}</span>
              </div>
            )}

            {/* Teams link */}
            {event.teams_link && (
              <div className="flex items-center gap-3 text-sm">
                <Video className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <a
                  href={event.teams_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline truncate"
                >
                  Dołącz do spotkania
                </a>
              </div>
            )}

            {/* Attendees */}
            {event.attendees && event.attendees.length > 0 && (
              <div className="flex items-start gap-3 text-sm text-foreground">
                <Users className="w-4 h-4 text-muted-foreground flex-shrink-0 mt-0.5" />
                <div className="flex flex-wrap gap-1">
                  {event.attendees.map((email, i) => (
                    <span
                      key={i}
                      className="px-2 py-0.5 bg-muted text-muted-foreground rounded-full text-xs"
                    >
                      {email}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Description */}
            {event.description && (
              <p className="text-sm text-muted-foreground bg-muted rounded-lg p-3 leading-relaxed">
                {event.description}
              </p>
            )}
          </div>

          {/* Actions */}
          <div className="flex gap-2 mt-5 pt-4 border-t border-border">
            {event.status === "scheduled" && (
              <button
                onClick={() => completeMutation.mutate()}
                disabled={completeMutation.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 transition-colors"
              >
                <CheckCircle className="w-3.5 h-3.5" />
                Zakończ
              </button>
            )}
            <ConfirmButton
              onConfirm={() => deleteMutation.mutate()}
              message="Na pewno chcesz usunąć?"
              confirmLabel="Usuń"
              cancelLabel="Anuluj"
              className={`flex items-center gap-1.5 px-3 py-1.5 bg-destructive/10 border border-destructive/20 hover:bg-destructive/15 text-destructive text-sm font-medium rounded-lg disabled:opacity-50 transition-colors ${deleteMutation.isPending ? "opacity-50 pointer-events-none" : ""}`}
            >
              <X className="w-3.5 h-3.5" />
              {deleteMutation.isPending ? "Usuwam..." : "Usuń"}
            </ConfirmButton>
            <button
              onClick={onClose}
              className="ml-auto px-4 py-1.5 text-sm text-muted-foreground hover:text-foreground"
            >
              Zamknij
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── iCal import button (Phase 7b.6) ──────────────────────────────────────────

function ICalImportButton({ onImported }: { onImported: () => void }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [since, setSince] = useState(7);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const run = async () => {
    if (!url.trim()) return;
    setBusy(true);
    setResult(null);
    try {
      const r = await api.post("/api/calendar/import-ical", {
        url: url.trim(),
        since_days: since,
      });
      const d = r.data as {
        events_fetched: number;
        inserted: number;
        updated: number;
        skipped_past: number;
        errors: number;
      };
      setResult(
        `fetched=${d.events_fetched} ins=${d.inserted} upd=${d.updated} skip=${d.skipped_past} err=${d.errors}`
      );
      onImported();
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
            "Błąd")
          : "Błąd";
      setResult(`Błąd: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 px-3 py-1.5 border border-border dark:border-border text-sm rounded-lg hover:bg-muted dark:hover:bg-muted"
        title="Importuj z publicznego feedu iCal (Outlook / Google Calendar)"
      >
        <Download className="w-4 h-4" />
        iCal import
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-96 bg-card dark:bg-muted rounded-lg shadow-xl border border-border dark:border-border p-3 z-30 space-y-2">
          <p className="text-xs text-muted-foreground">
            Wklej publiczny URL iCal (Outlook → Publikuj kalendarz, albo Google
            Calendar → Private address in iCal format).
          </p>
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://outlook.office365.com/.../calendar.ics"
            className="w-full rounded border border-border dark:border-border px-2 py-1.5 text-sm bg-card dark:bg-card"
          />
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            Pomiń starsze niż
            <input
              type="number"
              value={since}
              onChange={(e) => setSince(Number(e.target.value) || 7)}
              className="w-16 rounded border border-border dark:border-border px-2 py-0.5 text-xs bg-card dark:bg-card"
              min={0}
              max={365}
            />
            dni
          </label>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setOpen(false)}
              className="text-xs px-2 py-1 text-muted-foreground hover:text-foreground"
            >
              Anuluj
            </button>
            <button
              onClick={run}
              disabled={!url.trim() || busy}
              className="flex items-center gap-1 text-xs px-2.5 py-1 bg-primary text-white rounded hover:bg-primary/90 disabled:opacity-50"
            >
              {busy ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Download className="w-3 h-3" />
              )}
              Importuj
            </button>
          </div>
          {result && (
            <div className="text-xs text-foreground dark:text-muted-foreground bg-muted dark:bg-card rounded p-2 font-mono">
              {result}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
