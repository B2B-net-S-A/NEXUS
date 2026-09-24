"use client";

import { Suspense, useState, useEffect, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  AlertTriangle,
  Calendar,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  PanelLeft,
  Plus,
  User,
  X,
} from "lucide-react";
import api, { calendarApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { celebrate } from "@/lib/celebrate";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Sheet, SheetBody, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { InterviewFeedbackModal } from "@/components/feedback/InterviewFeedbackModal";
import { EventDetailModal } from "@/components/calendar/EventDetailModal";
import { CandidateCombobox, type CandidateChoice } from "@/components/calendar/CandidateCombobox";
import { RecruitmentSelect } from "@/components/calendar/RecruitmentSelect";
import {
  DAY_NAMES,
  EVENT_TYPE_CONFIG,
  FEEDBACK_EVENT_TYPES,
  HOURS,
  REMINDER_OPTIONS,
  isOtherOutlookMeeting,
  type CalendarEvent,
} from "@/components/calendar/calendar-config";
import { resolveViewState } from "@/lib/view-state";
import { layoutOverlappingEvents, limitVisibleLanes } from "@/lib/calendar-overlap";
import { allDayLabel, isAllDayOnDay } from "@/lib/calendar-all-day";
import { invalidAttendeeEmails, splitAttendeeEmails } from "@/components/calendar/attendee-emails";

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

/** Ta sama data przesunięta o `n` dni (00:00) — nawigacja widoku dnia. */
export function shiftDay(date: Date, n: number): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + n);
  return d;
}

/** Indeks w `DAY_NAMES` (poniedziałek = 0) dla dowolnej daty. */
function dayNameIndex(date: Date): number {
  return (date.getDay() + 6) % 7;
}

/**
 * Siatka tygodnia na telefonie pokazuje JEDEN dzień (decyzja 23.09.2026):
 * siedem kolumn na 375 px to ~40 px na dzień, tytuły znikały do 2–3 liter.
 * Przełączenie jest czysto w CSS (bez `matchMedia`), więc render serwera
 * i klienta jest ten sam: poniżej `md` widać tylko kolumnę wybranego dnia.
 */
const GRID_COLUMNS = "grid-cols-[48px_1fr] md:grid-cols-[48px_repeat(7,1fr)]";
function dayColumnVisibility(day: Date, selectedDay: Date): string | false {
  return !isSameDay(day, selectedDay) && "hidden md:block";
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

/** Dodatnia liczba całkowita z `?event=` albo `null` — śmieci w adresie nie odpalają zapytania. */
function parseEventIdParam(raw: string | null): number | null {
  if (!raw || !/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/**
 * Siatka tygodnia — zakładka „Tydzień” ekranu „Rozmowy u klienta”.
 *
 * Do 0338 była całą stroną `/calendar`. Zostaje w całości (kolizje, wydarzenia
 * całodniowe, `?event=` z dzwonka), ale jest teraz jednym z trzech widoków.
 */
/** Kolejność legendy: najpierw cykl rozmów u klienta, potem reszta. */
const LEGEND_TYPES = [
  "prep_call",
  "client_interview",
  "interview",
  "screening",
  "meeting",
  "deadline",
] as const;

const SHOW_OUTLOOK_KEY = "nexus:calendar:showOutlook:v1";

/** Wybór jednej osoby w tej przeglądarce; bez dostępu do magazynu = domyślnie schowane. */
function readShowOutlook(): boolean {
  try {
    return window.localStorage.getItem(SHOW_OUTLOOK_KEY) === "1";
  } catch {
    return false;
  }
}

function writeShowOutlook(value: boolean) {
  try {
    window.localStorage.setItem(SHOW_OUTLOOK_KEY, value ? "1" : "0");
  } catch {
    // Brak magazynu (tryb prywatny) — wybór działa do przeładowania.
  }
}

export default function WeekCalendar() {
  // `useSearchParams` wymaga granicy Suspense na prerenderze (jak `/jobs`) —
  // bez niej `next build` wywala się, mimo że strona renderuje się tylko po
  // stronie klienta.
  return (
    <Suspense
      fallback={
        <div className="p-8 text-sm text-muted-foreground">Ładowanie kalendarza...</div>
      }
    >
      <CalendarPageInner />
    </Suspense>
  );
}

// Zamknięcie okna z linku wraca do TEJ zakładki — goły `/calendar` otwiera agendę.
const WEEK_URL = "/calendar?view=week";

function CalendarPageInner() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  // Wybrany dzień — na telefonie widoczna kolumna, na desktopie wyznacza
  // tydzień siatki (poniedziałek liczony z niego).
  const [selectedDay, setSelectedDay] = useState<Date>(() => shiftDay(new Date(), 0));
  const selectedDayTime = selectedDay.getTime();
  const currentMonday = useMemo(() => getMonday(new Date(selectedDayTime)), [selectedDayTime]);
  const [sidePanelOpen, setSidePanelOpen] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [prefilledStart, setPrefilledStart] = useState<string>("");
  // Formularz feedbacku otwierany wprost z linku powiadomienia
  // (`/calendar?event=<id>&action=feedback`, `notification_triggers.py`).
  const [feedbackEventId, setFeedbackEventId] = useState<number | null>(null);
  const [deepLinkFailedId, setDeepLinkFailedId] = useState<number | null>(null);

  // ?event=<id> — link z pulpitu („Moje zadania → Spotkania") i z dzwonka
  // otwiera SZCZEGÓŁY wskazanego wydarzenia i przewija tydzień na jego datę.
  // Do 09.2026 strona parametru nie czytała: adres się zmieniał, a widoczna
  // była wyłącznie siatka bieżącego tygodnia (audyt B39). Efekt zależy od
  // WARTOŚCI parametrów, nie od tożsamości `searchParams` — miękka nawigacja
  // App Routera nie odmontowuje strony (patrz `lib/client-tab.ts`).
  const eventParam = searchParams.get("event");
  const actionParam = searchParams.get("action");
  const requestedEventId = parseEventIdParam(eventParam);
  useEffect(() => {
    if (requestedEventId == null) return;
    let cancelled = false;
    setDeepLinkFailedId(null);
    calendarApi
      .getEvent(requestedEventId)
      .then((r) => {
        if (cancelled) return;
        const event = r.data as CalendarEvent;
        setSelectedDay(shiftDay(new Date(event.start_time), 0));
        if (actionParam === "feedback") {
          setFeedbackEventId(event.id);
        } else {
          setSelectedEvent(event);
        }
      })
      .catch(() => {
        // Awaria ≠ pustka: sama siatka po nieudanym linku wyglądałaby jak
        // „wydarzenia nie ma", a ono może istnieć i tylko chwilowo nie wróciło.
        if (cancelled) return;
        setDeepLinkFailedId(requestedEventId);
        // Zdejmij parametr z adresu: F5 ma wrócić do zwykłego kalendarza,
        // a nie ponawiać nieudany link (komunikat wyżej zostaje na ekranie).
        router.replace(WEEK_URL);
      });
    return () => {
      cancelled = true;
    };
  }, [requestedEventId, actionParam]);

  // Zamknięcie okna otwartego z linku zdejmuje parametr z adresu — inaczej
  // F5 otwierałoby je z powrotem, a ponowny klik w TEN SAM link nie zmieniałby
  // wartości parametru i efekt wyżej nie wchodził.
  const clearEventParam = () => {
    if (eventParam != null) router.replace(WEEK_URL);
  };

  const weekDays = getWeekDays(currentMonday);
  const today = new Date();

  // Fetch events for this week
  const fromDate = currentMonday.toISOString();
  const toDate = new Date(currentMonday.getTime() + 7 * 24 * 60 * 60 * 1000).toISOString();

  const {
    data: eventsData,
    isPending,
    isError,
    error,
    refetch,
  } = useQuery<CalendarEvent[]>({
    queryKey: ["calendar-events", fromDate],
    queryFn: () =>
      calendarApi.listEvents({ from_date: fromDate, to_date: toDate }).then((r) => r.data),
  });

  // Bez domyślnego `= []`: nieudane pobranie musi być odróżnialne od „wolny
  // tydzień". Pusta siatka bez komunikatu to najdroższa cicha awaria w ATS —
  // rekruter skanuje poniedziałek, widzi zero rozmów i odchodzi.
  const allEvents = eventsData ?? [];
  // Zwykłe spotkania z Outlooka są domyślnie schowane (przełącznik nad siatką);
  // prepy, rozmowy i wszystko z kandydatem albo rekrutacją widać zawsze.
  const [showOutlook, setShowOutlook] = useState(false);
  // Po hydracji — serwer nie zna wyboru z tej przeglądarki.
  useEffect(() => setShowOutlook(readShowOutlook()), []);
  const hiddenOutlookCount = allEvents.filter(isOtherOutlookMeeting).length;
  const events = showOutlook ? allEvents : allEvents.filter((ev) => !isOtherOutlookMeeting(ev));
  // `isPending`, nie `isLoading` — przy globalnym `retry: 1` istnieje okno
  // między próbami, w którym isLoading i isError są false, a data undefined;
  // na `isLoading` migał tam pusty tydzień w drodze do stanu błędu.
  const calendarState = resolveViewState({ isLoading: isPending, isError, error });
  const calendarFailed =
    calendarState === "forbidden" ||
    calendarState === "not_found" ||
    calendarState === "error";

  // Phase 5.4 — bulk overlap map for the visible week. One request flags every
  // event with the ids it conflicts with, so we don't have to fan out per-event.
  const { data: conflictPairs, isError: conflictsFailed } = useQuery<
    Record<string, number[]>
  >({
    queryKey: ["calendar-conflicts-summary", fromDate],
    queryFn: () =>
      calendarApi
        .conflictsSummary({ start: fromDate, end: toDate })
        .then((r) => r.data.pairs ?? {}),
  });

  // „Najbliższe" z OSOBNEGO zapytania: lista brana z załadowanego tygodnia
  // w piątek pokazywała pustkę, choć w poniedziałek czekały trzy rozmowy.
  const upcomingQuery = useQuery<CalendarEvent[]>({
    queryKey: ["calendar-upcoming"],
    queryFn: () =>
      calendarApi
        .listEvents({ upcoming: true, mine_only: true, limit: 20 })
        .then((r) => r.data),
    staleTime: 60_000,
  });

  const prevWeek = () => setSelectedDay((d) => shiftDay(d, -7));
  const nextWeek = () => setSelectedDay((d) => shiftDay(d, 7));
  const prevDay = () => setSelectedDay((d) => shiftDay(d, -1));
  const nextDay = () => setSelectedDay((d) => shiftDay(d, 1));

  const goToday = () => {
    setSelectedDay(shiftDay(new Date(), 0));
  };

  const openCreate = () => {
    setPrefilledStart("");
    setShowCreateModal(true);
  };

  const sidebarProps = {
    today,
    events,
    currentMonday,
    upcoming: (upcomingQuery.data ?? []).filter((ev) => showOutlook || !isOtherOutlookMeeting(ev)),
    failed: calendarFailed || upcomingQuery.isError,
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
  const navButton =
    "inline-flex h-10 w-10 md:h-8 md:w-8 items-center justify-center hover:bg-muted rounded-lg transition-colors text-muted-foreground";

  return (
    <div className="flex gap-0 h-[calc(100dvh-220px)] min-h-[520px] overflow-hidden">
      {/* ── Sidebar ── (od xl; węziej panel otwiera przycisk „Panel” w nagłówku) */}
      <CalendarSidebar
        {...sidebarProps}
        className="hidden xl:flex w-64 shrink-0 mr-4"
        onPickDay={(day) => setSelectedDay(shiftDay(day, 0))}
        onEventClick={(ev) => {
          setSelectedDay(shiftDay(new Date(ev.start_time), 0));
          setSelectedEvent(ev);
        }}
        onCreateClick={openCreate}
      />
      <Sheet open={sidePanelOpen} onOpenChange={setSidePanelOpen}>
        {sidePanelOpen && (
          <SheetContent side="right" size="sm">
            <SheetHeader>
              <SheetTitle>Kalendarz</SheetTitle>
            </SheetHeader>
            <SheetBody>
              <CalendarSidebar
                {...sidebarProps}
                onPickDay={(day) => {
                  setSelectedDay(shiftDay(day, 0));
                  setSidePanelOpen(false);
                }}
                onEventClick={(ev) => {
                  setSelectedDay(shiftDay(new Date(ev.start_time), 0));
                  setSidePanelOpen(false);
                  setSelectedEvent(ev);
                }}
                onCreateClick={() => {
                  setSidePanelOpen(false);
                  openCreate();
                }}
              />
            </SheetBody>
          </SheetContent>
        )}
      </Sheet>

      {/* ── Main calendar ── */}
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden bg-card dark:bg-muted border border-border dark:border-border rounded-2xl">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-2 px-3 md:px-5 py-3 border-b border-border dark:border-border shrink-0">
          <div className="flex flex-wrap items-center gap-2 md:gap-3">
            <h2 className="text-lg font-bold text-foreground dark:text-foreground capitalize">{monthLabel}</h2>
            {/* Telefon: widok jednego dnia, strzałki przesuwają dzień. */}
            <div className="flex items-center gap-1 md:hidden">
              <button type="button" onClick={prevDay} aria-label="Poprzedni dzień" className={navButton}>
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button type="button" onClick={nextDay} aria-label="Następny dzień" className={navButton}>
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
            <div className="hidden md:flex items-center gap-1">
              <button type="button" onClick={prevWeek} aria-label="Poprzedni tydzień" className={navButton}>
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button type="button" onClick={nextWeek} aria-label="Następny tydzień" className={navButton}>
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
            <button
              type="button"
              onClick={goToday}
              className="h-10 md:h-8 text-xs font-medium px-3 bg-primary/10 text-primary hover:bg-primary/15 rounded-lg transition-colors"
            >
              Dzisiaj
            </button>
          </div>

          {/* Legenda typów stoi w panelu bocznym („Typy wydarzeń”) — w nagłówku
              ściskała przyciski, odkąd siatka jest zakładką ekranu. Węziej niż
              xl panel jest schowany, więc „Nowe wydarzenie” i sam panel
              otwierają przyciski tutaj. */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={openCreate}
              className="xl:hidden inline-flex h-10 md:h-9 items-center gap-1.5 px-3 bg-primary hover:bg-primary/90 text-white text-sm font-semibold rounded-lg transition-colors"
            >
              <Plus className="w-4 h-4" />
              Nowe wydarzenie
            </button>
            <button
              type="button"
              onClick={() => setSidePanelOpen(true)}
              aria-label="Pokaż panel kalendarza (mini-miesiąc, najbliższe, typy)"
              className="xl:hidden inline-flex h-10 md:h-9 items-center gap-1.5 px-3 border border-border text-sm rounded-lg hover:bg-muted"
            >
              <PanelLeft className="w-4 h-4" />
              <span className="hidden sm:inline">Panel</span>
            </button>
            <ICalImportButton
              onImported={() => {
                queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
              }}
            />
            {/* „Nowe wydarzenie” jest w panelu bocznym — drugi przycisk w
                nagłówku ucinał się przy węższym oknie (test na produkcji 22.09). */}
          </div>
        </div>

        {/* Filtr Outlooka i legenda kolorów — nad siatką, a nie pod listą
            w panelu bocznym, gdzie nikt jej nie widział. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 md:px-5 py-2 border-b border-border shrink-0 text-xs text-muted-foreground">
          <label className="inline-flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={showOutlook}
              onChange={(e) => {
                setShowOutlook(e.target.checked);
                writeShowOutlook(e.target.checked);
              }}
              className="h-4 w-4 accent-primary"
            />
            Pozostałe spotkania z Outlooka
            {hiddenOutlookCount > 0 ? (
              <span className="text-muted-foreground">({hiddenOutlookCount})</span>
            ) : null}
          </label>
          <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 md:ml-auto" aria-label="Legenda">
            {LEGEND_TYPES.map((key) => (
              <li key={key} className="inline-flex items-center gap-1.5">
                <span className={cn("h-2.5 w-2.5 rounded-full", EVENT_TYPE_CONFIG[key].dotColor)} aria-hidden />
                {EVENT_TYPE_CONFIG[key].label}
              </li>
            ))}
            <li className="inline-flex items-center gap-1">
              <AlertTriangle className="h-3 w-3 text-warning" aria-hidden />
              kolizja z innym spotkaniem
            </li>
          </ul>
        </div>

        {/* Day headers */}
        <div className={cn("grid border-b border-border dark:border-border shrink-0", GRID_COLUMNS)}>
          <div className="border-r border-border" />
          {weekDays.map((day, i) => {
            const isToday = isSameDay(day, today);
            return (
              <div
                key={i}
                className={cn(
                  "text-center py-2 border-r border-border last:border-r-0",
                  isToday && "bg-primary/10",
                  dayColumnVisibility(day, selectedDay),
                )}
              >
                <div className="text-xs text-muted-foreground font-medium">{DAY_NAMES[dayNameIndex(day)]}</div>
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

        {/* Mapa kolizji jest jedynym źródłem ostrzeżeń o podwójnej rezerwacji.
            Gdy padnie, siatka renderuje się bez żadnego znacznika konfliktu —
            czyli wygląda tak samo jak tydzień bez kolizji. Rekruter mógłby
            zostać w ten sposób doprowadzony do umówienia zajętego slotu. */}
        {deepLinkFailedId != null && (
          <div
            role="alert"
            className="shrink-0 px-5 py-2 text-xs text-destructive border-b border-destructive/30 bg-destructive/10"
          >
            Nie udało się otworzyć wydarzenia #{deepLinkFailedId} z linku — może
            zostało usunięte albo nie masz do niego dostępu. Siatka poniżej go nie
            wyróżnia.
          </div>
        )}

        {!calendarFailed && conflictsFailed && (
          <div
            role="alert"
            className="shrink-0 px-5 py-2 text-xs text-destructive border-b border-destructive/30 bg-destructive/10"
          >
            Nie udało się sprawdzić kolizji terminów — brak oznaczeń nie znaczy,
            że ich nie ma. Zweryfikuj slot ręcznie przed umówieniem.
          </div>
        )}

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">
          {isPending ? (
            <div className="flex items-center justify-center h-32 text-muted-foreground">
              <div className="w-5 h-5 border-2 border-primary/30 border-t-transparent rounded-full animate-spin mr-2" />
              Ładowanie kalendarza...
            </div>
          ) : calendarFailed ? (
            <QueryStateNotice
              state={calendarState as "forbidden" | "not_found" | "error"}
              className="m-4"
              description={
                calendarState === "forbidden"
                  ? "Twoja rola nie ma dostępu do kalendarza. Ten tydzień NIE jest pusty — nie planuj na podstawie tego widoku."
                  : "Nie udało się wczytać kalendarza. Pusty tydzień poniżej nie znaczy, że nie masz spotkań — ponów próbę przed umówieniem czegokolwiek."
              }
              onRetry={() => void refetch()}
            />
          ) : (
            <>
            <AllDayStrip
              weekDays={weekDays}
              selectedDay={selectedDay}
              events={events}
              onEventClick={setSelectedEvent}
            />
            <WeekGrid
              hours={HOURS}
              weekDays={weekDays}
              selectedDay={selectedDay}
              events={events}
              titleEvents={allEvents}
              today={today}
              conflictPairs={conflictPairs ?? {}}
              onSlotClick={handleSlotClick}
              onEventClick={setSelectedEvent}
            />
            </>
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
            queryClient.invalidateQueries({ queryKey: ["calendar-upcoming"] });
            queryClient.invalidateQueries({ queryKey: ["calendar-conflicts-summary"] });
            setShowCreateModal(false);
          }}
        />
      )}

      {/* ── Detail modal ── */}
      {selectedEvent && (
        <EventDetailModal
          event={selectedEvent}
          onClose={() => {
            setSelectedEvent(null);
            clearEventParam();
          }}
          onDeleted={() => {
            queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
            setSelectedEvent(null);
            clearEventParam();
          }}
          onUpdated={(updated) => setSelectedEvent(updated)}
          onOpenFeedback={(eventId) => {
            // Jedno okno naraz: formularz feedbacku zastępuje szczegóły.
            setSelectedEvent(null);
            setFeedbackEventId(eventId);
          }}
        />
      )}

      {/* ── Feedback z linku `?event=<id>&action=feedback` ── */}
      {feedbackEventId != null && (
        <InterviewFeedbackModal
          open
          onOpenChange={(open) => {
            if (open) return;
            setFeedbackEventId(null);
            clearEventParam();
          }}
          calendarEventId={feedbackEventId}
          onSaved={() => {
            queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
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
  selectedDay,
  events,
  titleEvents,
  today,
  conflictPairs,
  onSlotClick,
  onEventClick,
}: {
  hours: number[];
  weekDays: Date[];
  /** Dzień widoczny na telefonie (pozostałe kolumny chowa CSS poniżej `md`). */
  selectedDay: Date;
  events: CalendarEvent[];
  /** Wszystkie wydarzenia tygodnia, także schowane — nazwy w podpowiedzi kolizji. */
  titleEvents: CalendarEvent[];
  today: Date;
  conflictPairs: Record<string, number[]>;
  onSlotClick: (day: Date, hour: number) => void;
  onEventClick: (ev: CalendarEvent) => void;
}) {
  // Tytuły kolizji także ze spotkań schowanych filtrem Outlooka — inaczej
  // podpowiedź brzmiała „Konflikt z: ” bez nazwy.
  const eventTitleById = new Map(titleEvents.map((ev) => [ev.id, ev.title]));
  const nowMinutes = today.getHours() * 60 + today.getMinutes();
  const nowTop = ((nowMinutes - 8 * 60) / 60) * 56;

  return (
    <div className={cn("grid relative", GRID_COLUMNS)}>
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
        // Wpisy całodniowe mają własny pasek nad siatką — rysowane jako blok
        // 00:00–24:00 zajmowały pas w kolumnie i zwężały rozmowy.
        const dayEvents = events.filter((ev) => {
          if (ev.all_day) return false;
          const evDate = parseTime(ev.start_time);
          return isSameDay(evDate, day);
        });
        // Nachodzące wydarzenia dzielą szerokość dnia na pasy — bez tego
        // kafle o tej samej godzinie leżały dokładnie na sobie (UAT M03-B11).
        // Przedziały w pikselach, z minimalną wysokością kafla (28 px).
        // Odwołane nie biorą pasa: rysujemy je pod spodem na pełną szerokość.
        const overlapInputs = dayEvents.filter((ev) => ev.status !== "cancelled").map((ev) => {
          const evStart = parseTime(ev.start_time);
          const evEnd = ev.end_time ? parseTime(ev.end_time) : null;
          const evTop = getEventTop(evStart);
          return {
            id: ev.id,
            start: evTop,
            end: evTop + Math.max(28, getEventHeight(evStart, evEnd)),
          };
        });
        // Najwyżej dwa pasy — przy trzech i więcej kafle robiły się wąskie
        // jak ikona, a tytuły skracały się do „Sp…” (UAT B08). Reszta grupy
        // trafia do chipa „+N”.
        const { slots: overlapSlots, overflow } = limitVisibleLanes(
          overlapInputs,
          layoutOverlappingEvents(overlapInputs),
        );

        return (
          <div
            key={dayIdx}
            data-testid="calendar-day-column"
            data-selected-day={isSameDay(day, selectedDay) ? "true" : undefined}
            className={cn(
              "relative border-r border-border last:border-r-0",
              isToday && "bg-primary/10",
              dayColumnVisibility(day, selectedDay),
            )}
          >
            {/* Hour slots */}
            {hours.map((h) => (
              <div
                key={h}
                className="h-14 border-b border-gray-50 hover:bg-primary/10 cursor-pointer transition-colors"
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
                  <div className="w-2 h-2 rounded-full bg-destructive -ml-1" />
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
              const overlapIds = conflictPairs[String(ev.id)] ?? [];
              const hasConflict =
                overlapIds.length > 0 && ev.status !== "cancelled";
              const conflictTitles = overlapIds
                .map((id) => eventTitleById.get(id))
                .filter(Boolean) as string[];
              const conflictTooltip = hasConflict
                ? `Konflikt z: ${conflictTitles.join(", ")}`
                : undefined;
              const cancelled = ev.status === "cancelled";
              const slot = (!cancelled && overlapSlots.get(ev.id)) || {
                column: 0,
                columns: 1,
                cluster: -1,
                hidden: false,
              };
              if (slot.hidden) return null;

              return (
                <div
                  key={ev.id}
                  title={conflictTooltip}
                  className={cn(
                    "absolute rounded-lg border px-2 py-1 cursor-pointer overflow-hidden shadow-xs hover:shadow-md transition-shadow",
                    cancelled
                      ? "z-0 bg-muted border-border text-muted-foreground opacity-60 line-through"
                      : cn("z-5", cfg.bgColor, cfg.borderColor),
                    hasConflict &&
                      "ring-2 ring-amber-500 dark:ring-amber-400 ring-offset-1"
                  )}
                  style={{
                    top: `${top}px`,
                    height: `${height}px`,
                    minHeight: "28px",
                    left: `calc(${(slot.column / slot.columns) * 100}% + 4px)`,
                    width: `calc(${100 / slot.columns}% - 8px)`,
                  }}
                  data-testid={`calendar-event-${ev.id}`}
                  data-cancelled={cancelled ? "true" : undefined}
                  onClick={(e) => {
                    e.stopPropagation();
                    onEventClick(ev);
                  }}
                >
                  {ev.needs_attention && !cancelled ? (
                    <span
                      className="absolute bottom-0.5 right-1 text-destructive"
                      aria-label="Brak feedbacku po rozmowie"
                      title="Brak feedbacku po rozmowie"
                    >
                      <AlertTriangle className="w-3 h-3" />
                    </span>
                  ) : null}
                  {hasConflict && (
                    <span
                      className="absolute top-0.5 right-1 text-amber-600 dark:text-amber-400 text-xs leading-none"
                      aria-label="Konflikt z innym wydarzeniem"
                    >
                      ⚠
                    </span>
                  )}
                  <div
                    className={cn(
                      "text-xs font-semibold truncate leading-tight",
                      hasConflict && "pr-3",
                      cancelled ? "text-muted-foreground" : cfg.color,
                    )}
                  >
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

            {overflow.map((group) => (
              <OverflowEventsChip
                key={group.cluster}
                top={group.top}
                events={group.ids
                  .map((id) => dayEvents.find((ev) => ev.id === id))
                  .filter((ev): ev is CalendarEvent => Boolean(ev))}
                onEventClick={onEventClick}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}

// ── Pasek „cały dzień" ──────────────────────────────────────────────────────

function AllDayStrip({
  weekDays,
  selectedDay,
  events,
  onEventClick,
}: {
  weekDays: Date[];
  selectedDay: Date;
  events: CalendarEvent[];
  onEventClick: (ev: CalendarEvent) => void;
}) {
  const allDay = events.filter((ev) => ev.all_day);
  if (allDay.length === 0) return null;
  return (
    <div
      className={cn("grid border-b border-border bg-muted/30", GRID_COLUMNS)}
      data-testid="calendar-all-day-strip"
    >
      <div className="border-r border-border px-1 py-1 text-[10px] leading-tight text-muted-foreground text-right">
        cały dzień
      </div>
      {weekDays.map((day, i) => (
        <div
          key={i}
          className={cn(
            "border-r border-border last:border-r-0 p-1 space-y-0.5 min-w-0",
            dayColumnVisibility(day, selectedDay),
          )}
        >
          {allDay
            .filter((ev) => isAllDayOnDay(ev, day))
            .map((ev) => {
              const cfg = EVENT_TYPE_CONFIG[ev.event_type] || EVENT_TYPE_CONFIG.meeting;
              return (
                <button
                  key={ev.id}
                  type="button"
                  title={`${ev.title} — ${allDayLabel(ev)}`}
                  onClick={() => onEventClick(ev)}
                  className={cn(
                    "block w-full truncate rounded-md border px-1.5 py-0.5 text-left text-[11px] font-medium",
                    ev.status === "cancelled"
                      ? "bg-muted border-border text-muted-foreground line-through opacity-60"
                      : cn(cfg.bgColor, cfg.borderColor, cfg.color),
                  )}
                >
                  {ev.title}
                </button>
              );
            })}
        </div>
      ))}
    </div>
  );
}

function OverflowEventsChip({
  top,
  events,
  onEventClick,
}: {
  top: number;
  events: CalendarEvent[];
  onEventClick: (ev: CalendarEvent) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="absolute right-1 z-10" style={{ top: `${top}px` }}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-expanded={open}
        aria-label={`Pokaż ${events.length} kolejne wydarzenia w tym czasie`}
        title={events.map((ev) => ev.title).join(", ")}
        className="rounded-full border border-border bg-card px-1.5 py-0.5 text-[10px] font-semibold text-foreground shadow-xs hover:bg-muted"
      >
        +{events.length}
      </button>
      {open && (
        // Kotwica dla testów: ten sam tytuł wydarzenia stoi też na liście
        // „Nadchodzące" w szynie (tylko dla wydarzeń w przyszłości), więc
        // zapytanie po samej nazwie przycisku trafia raz w jeden element,
        // a raz w dwa — zależnie od pory dnia i strefy czasowej biegu.
        <ul
          data-testid="calendar-overflow-popover"
          className="absolute right-0 mt-1 w-48 max-w-[calc(100vw-2rem)] space-y-0.5 rounded-lg border border-border bg-card p-1 shadow-lg"
          onClick={(e) => e.stopPropagation()}
        >
          {events.map((ev) => (
            <li key={ev.id}>
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  onEventClick(ev);
                }}
                className="w-full truncate rounded-md px-2 py-1 text-left text-xs hover:bg-muted"
              >
                {parseTime(ev.start_time).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}{" "}
                {ev.title}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function CalendarSidebar({
  today,
  events,
  currentMonday,
  onPickDay,
  upcoming,
  failed,
  onEventClick,
  onCreateClick,
  className,
}: {
  className?: string;
  today: Date;
  /** Wydarzenia widocznego tygodnia (kropki w mini-kalendarzu). */
  events: CalendarEvent[];
  currentMonday: Date;
  onPickDay: (day: Date) => void;
  /** Najbliższe własne wydarzenia — osobne zapytanie, niezależne od tygodnia. */
  upcoming: CalendarEvent[];
  /** Pobranie wydarzeń padło — panel „Najbliższe" nie może po cichu zniknąć. */
  failed: boolean;
  onEventClick: (ev: CalendarEvent) => void;
  onCreateClick: () => void;
}) {
  const upcomingEvents = upcoming
    .filter((ev) => ev.status !== "cancelled" && new Date(ev.start_time) >= today)
    .slice(0, 5);

  return (
    <div className={cn("flex flex-col gap-4", className)}>
      <button
        onClick={onCreateClick}
        className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary hover:bg-primary/90 text-white font-semibold rounded-xl transition-colors shadow-xs"
      >
        <Plus className="w-4 h-4" />
        Nowe wydarzenie
      </button>

      <div className="bg-card dark:bg-muted border border-border dark:border-border rounded-2xl p-4">
        <MiniCalendar
          today={today}
          events={events}
          currentMonday={currentMonday}
          onPickDay={onPickDay}
        />
      </div>

      {failed ? (
        <div
          role="alert"
          className="bg-card dark:bg-muted border border-destructive/40 rounded-2xl p-4"
        >
          <div className="text-xs font-bold text-muted-foreground uppercase tracking-wide mb-2">
            Najbliższe
          </div>
          <p className="text-xs text-destructive">
            Nie udało się wczytać wydarzeń — ta lista jest niekompletna, nie pusta.
          </p>
        </div>
      ) : null}
      {!failed && upcomingEvents.length > 0 && (
        <div className="bg-card dark:bg-muted border border-border dark:border-border rounded-2xl p-4">
          <div className="text-xs font-bold text-muted-foreground dark:text-muted-foreground uppercase tracking-wide mb-3">
            Najbliższe
          </div>
          <div className="space-y-2">
            {upcomingEvents.map((ev) => {
              const cfg = EVENT_TYPE_CONFIG[ev.event_type] || EVENT_TYPE_CONFIG.meeting;
              const d = new Date(ev.start_time);
              return (
                <button
                  key={ev.id}
                  type="button"
                  onClick={() => onEventClick(ev)}
                  className="w-full flex items-start gap-2 rounded-md text-left hover:bg-muted"
                >
                  <div className={cn("w-2 h-2 rounded-full mt-1.5 shrink-0", cfg.dotColor)} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-foreground truncate">{ev.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {ev.all_day
                        ? allDayLabel(ev)
                        : `${d.toLocaleDateString("pl-PL", { weekday: "short", day: "numeric", month: "short" })} ${d.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}`}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      )}

    </div>
  );
}

// ── Mini calendar ─────────────────────────────────────────────────────────────

/**
 * Nawigacja po tygodniach: klik w dzień przewija siatkę na jego tydzień.
 * Do 09.2026 mini-kalendarz był ozdobą — pokazywał zawsze bieżący miesiąc
 * i nie reagował na kliknięcia.
 */
function MiniCalendar({
  today,
  events,
  currentMonday,
  onPickDay,
}: {
  today: Date;
  events: CalendarEvent[];
  currentMonday: Date;
  onPickDay: (day: Date) => void;
}) {
  const [month, setMonth] = useState(
    () => new Date(currentMonday.getFullYear(), currentMonday.getMonth(), 1),
  );
  // Siatka przewinięta strzałkami tygodnia do innego miesiąca → miesiąc idzie za nią.
  useEffect(() => {
    setMonth((m) =>
      m.getFullYear() === currentMonday.getFullYear() && m.getMonth() === currentMonday.getMonth()
        ? m
        : new Date(currentMonday.getFullYear(), currentMonday.getMonth(), 1),
    );
  }, [currentMonday]);

  const year = month.getFullYear();
  const monthIdx = month.getMonth();
  const firstDay = new Date(year, monthIdx, 1).getDay();
  const daysInMonth = new Date(year, monthIdx + 1, 0).getDate();
  const startOffset = firstDay === 0 ? 6 : firstDay - 1;
  const weekEnd = new Date(currentMonday);
  weekEnd.setDate(weekEnd.getDate() + 7);

  const eventDays = new Set(
    events.map((ev) => {
      const d = new Date(ev.start_time);
      return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
    }),
  );

  const cells: (number | null)[] = [
    ...Array(startOffset).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <button
          type="button"
          aria-label="Poprzedni miesiąc"
          onClick={() => setMonth(new Date(year, monthIdx - 1, 1))}
          className="p-0.5 rounded hover:bg-muted text-muted-foreground"
        >
          <ChevronLeft className="w-3.5 h-3.5" />
        </button>
        <div className="text-xs font-bold text-muted-foreground uppercase tracking-wide">
          {month.toLocaleDateString("pl-PL", { month: "long", year: "numeric" })}
        </div>
        <button
          type="button"
          aria-label="Następny miesiąc"
          onClick={() => setMonth(new Date(year, monthIdx + 1, 1))}
          className="p-0.5 rounded hover:bg-muted text-muted-foreground"
        >
          <ChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>
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
          const date = new Date(year, monthIdx, day);
          const isToday = isSameDay(date, today);
          const inWeek = date >= currentMonday && date < weekEnd;
          const hasEvents = eventDays.has(`${year}-${monthIdx}-${day}`);
          return (
            <button
              key={i}
              type="button"
              onClick={() => onPickDay(date)}
              aria-label={date.toLocaleDateString("pl-PL", { day: "numeric", month: "long", year: "numeric" })}
              aria-pressed={inWeek}
              className={cn(
                "text-center text-xs py-0.5 rounded-md font-medium relative",
                isToday
                  ? "bg-primary text-white"
                  : inWeek
                    ? "bg-primary/10 text-foreground"
                    : "text-muted-foreground hover:bg-muted",
              )}
            >
              {day}
              {hasEvents && !isToday && (
                <div className="absolute bottom-0.5 left-1/2 -translate-x-1/2 w-1 h-1 bg-primary/30 rounded-full" />
              )}
            </button>
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
  const [form, setForm] = useState({
    title: "",
    description: "",
    event_type: "meeting",
    start_time: prefilledStart,
    end_time: "",
    all_day: false,
    attendees_raw: "",
    location: "",
    teams_link: "",
    reminder_minutes: "15",
  });
  const [candidate, setCandidate] = useState<CandidateChoice | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);

  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => calendarApi.createEvent(data),
    onSuccess: () => {
      onCreated();
      celebrate({ small: true, message: "Wydarzenie zaplanowane! 📅" });
    },
    onError: (e: unknown) => {
      setError(apiErrorMessage(e, "Błąd tworzenia wydarzenia"));
    },
  });

  const needsRecruitmentWarning =
    !!candidate && jobId == null && FEEDBACK_EVENT_TYPES.has(form.event_type);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title.trim() || !form.start_time) {
      setError("Tytuł i czas rozpoczęcia są wymagane");
      return;
    }
    if (
      !form.all_day &&
      form.end_time &&
      new Date(form.end_time) <= new Date(form.start_time)
    ) {
      setError("Koniec wydarzenia musi być późniejszy niż jego początek.");
      return;
    }

    const attendees = splitAttendeeEmails(form.attendees_raw);
    const invalid = invalidAttendeeEmails(attendees);
    if (invalid.length > 0) {
      setError(`Nieprawidłowy adres e-mail: ${invalid.join(", ")}`);
      return;
    }

    mutation.mutate({
      title: form.title.trim(),
      description: form.description || null,
      event_type: form.event_type,
      start_time: new Date(form.start_time).toISOString(),
      end_time: form.end_time ? new Date(form.end_time).toISOString() : null,
      all_day: form.all_day,
      candidate_id: candidate?.id ?? null,
      job_id: candidate ? jobId : null,
      attendees,
      location: form.location || null,
      teams_link: form.teams_link || null,
      reminder_minutes: parseInt(form.reminder_minutes) || 15,
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-end sm:items-center justify-center sm:p-4">
      <div className="bg-card dark:bg-muted rounded-2xl sm:rounded-2xl rounded-b-none sm:rounded-b-2xl shadow-2xl w-full sm:max-w-lg max-h-[90dvh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border">
          <div className="flex items-center gap-2">
            <Calendar className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-bold text-foreground dark:text-foreground">Nowe wydarzenie</h2>
          </div>
          <button onClick={onClose} aria-label="Zamknij" className="text-muted-foreground hover:text-muted-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} noValidate className="p-6 space-y-4">
          {error && (
            <div role="alert" className="flex items-center gap-2 text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-lg px-3 py-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              {error}
            </div>
          )}

          <div>
            <label htmlFor="calendar-new-title" className="text-xs font-semibold text-muted-foreground block mb-1">Tytuł *</label>
            <input
              id="calendar-new-title"
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              placeholder="np. Rozmowa z kandydatem"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-muted-foreground block mb-1">Typ</label>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
              {Object.entries(EVENT_TYPE_CONFIG).map(([key, cfg]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setForm({ ...form, event_type: key })}
                  className={cn(
                    "min-h-10 px-2 py-1.5 rounded-lg text-xs font-medium border transition-colors text-center break-words",
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

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="calendar-new-start" className="text-xs font-semibold text-muted-foreground block mb-1">Od *</label>
              <input
                id="calendar-new-start"
                required
                type="datetime-local"
                value={form.start_time}
                onChange={(e) => setForm({ ...form, start_time: e.target.value })}
                className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              />
            </div>
            <div>
              <label htmlFor="calendar-new-end" className="text-xs font-semibold text-muted-foreground block mb-1">Do</label>
              <input
                id="calendar-new-end"
                type="datetime-local"
                value={form.end_time}
                onChange={(e) => setForm({ ...form, end_time: e.target.value })}
                className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={form.all_day}
              onChange={(e) => setForm({ ...form, all_day: e.target.checked })}
            />
            Cały dzień
            <span className="text-xs text-muted-foreground">(urlop, nieobecność — nie blokuje slotów)</span>
          </label>

          <div>
            <label
              id="calendar-candidate-label"
              className="text-xs font-semibold text-muted-foreground block mb-1"
            >
              Kandydat (opcjonalnie)
            </label>
            <CandidateCombobox
              labelledBy="calendar-candidate-label"
              value={candidate}
              onChange={(next) => {
                setCandidate(next);
                // Rekrutacja należy do kandydata — zmiana osoby ją zeruje.
                if (next?.id !== candidate?.id) setJobId(null);
              }}
            />
          </div>

          {candidate && (
            <div>
              <label htmlFor="calendar-new-job" className="text-xs font-semibold text-muted-foreground block mb-1">
                Rekrutacja
              </label>
              <RecruitmentSelect
                key={candidate.id}
                id="calendar-new-job"
                candidateId={candidate.id}
                value={jobId}
                onChange={setJobId}
              />
              {needsRecruitmentWarning && (
                <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                  Bez rekrutacji feedback po rozmowie i przypomnienie do Delivery
                  Leada nie zadziałają.
                </p>
              )}
            </div>
          )}

          <div>
            <label htmlFor="calendar-new-location" className="text-xs font-semibold text-muted-foreground block mb-1">Lokalizacja</label>
            <input
              id="calendar-new-location"
              value={form.location}
              onChange={(e) => setForm({ ...form, location: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              placeholder="np. Google Meet, Telefon, Biuro..."
            />
          </div>

          <div>
            <label htmlFor="calendar-new-link" className="text-xs font-semibold text-muted-foreground block mb-1">Link Teams/Meet</label>
            <input
              id="calendar-new-link"
              value={form.teams_link}
              onChange={(e) => setForm({ ...form, teams_link: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              placeholder="https://..."
            />
          </div>

          <div>
            <label htmlFor="calendar-new-attendees" className="text-xs font-semibold text-muted-foreground block mb-1">
              Uczestnicy (e-maile oddzielone przecinkiem, średnikiem lub spacją)
            </label>
            <input
              id="calendar-new-attendees"
              value={form.attendees_raw}
              onChange={(e) => setForm({ ...form, attendees_raw: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
              placeholder="jan@email.com, anna@email.com"
            />
          </div>

          <div>
            <label htmlFor="calendar-new-description" className="text-xs font-semibold text-muted-foreground block mb-1">Opis</label>
            <textarea
              id="calendar-new-description"
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring resize-none"
            />
          </div>

          <div>
            <label htmlFor="calendar-new-reminder" className="text-xs font-semibold text-muted-foreground block mb-1">Przypomnienie</label>
            <select
              id="calendar-new-reminder"
              value={form.reminder_minutes}
              onChange={(e) => setForm({ ...form, reminder_minutes: e.target.value })}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-hidden focus:ring-2 focus-visible:ring-ring"
            >
              {REMINDER_OPTIONS.map((o) => (
                <option key={o.value} value={String(o.value)}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

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

// ── iCal import button (Phase 7b.6) ──────────────────────────────────────────

interface ICalImportSummary {
  events_fetched: number;
  inserted: number;
  updated: number;
  skipped_past: number;
  skipped_conflict?: number;
  errors: number;
}

/** Wynik importu iCal po polsku — do 09.2026 „fetched=12 ins=3 upd=1 skip=0 err=0". */
function icalImportSummary(d: ICalImportSummary): string {
  const parts = [
    `Pobrano ${d.events_fetched} wydarzeń`,
    `dodano ${d.inserted}`,
    `zaktualizowano ${d.updated}`,
  ];
  if (d.skipped_past) parts.push(`pominięto ${d.skipped_past} starszych`);
  if (d.skipped_conflict) parts.push(`pominięto ${d.skipped_conflict} zajętych przez inny import`);
  if (d.errors) parts.push(`błędy: ${d.errors}`);
  return parts.join(", ") + ".";
}

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
      const d = r.data as ICalImportSummary;
      setResult(icalImportSummary(d));
      onImported();
    } catch (e: unknown) {
      const msg = apiErrorMessage(e, "Błąd");
      setResult(`Błąd: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        type="button"
        className="flex h-10 md:h-auto items-center gap-1.5 px-3 py-1.5 border border-border dark:border-border text-sm rounded-lg hover:bg-muted dark:hover:bg-muted"
        title="Importuj z publicznego feedu iCal (Outlook / Google Calendar)"
      >
        <Download className="w-4 h-4" />
        iCal import
      </button>
      {open && (
        // Na telefonie przycisk bywa w drugim wierszu nagłówka po lewej —
        // popover przypięty do jego prawej krawędzi wychodził za ekran.
        <div className="absolute right-0 mt-1 w-96 max-sm:fixed max-sm:inset-x-4 max-sm:top-24 max-sm:mt-0 max-sm:w-auto bg-card dark:bg-muted rounded-lg shadow-xl border border-border dark:border-border p-3 z-30 space-y-2">
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
            <div role="status" className="text-xs text-foreground dark:text-muted-foreground bg-muted dark:bg-card rounded p-2">
              {result}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
