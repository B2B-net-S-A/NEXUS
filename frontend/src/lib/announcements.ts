// „Ogłoszenia” na pulpicie (decyzja Artura 28.10.2026) — reguły formularza
// i etykiety. Lustro walidacji `backend/app/services/announcements.py`
// (serwer i tak sprawdza wszystko jeszcze raz).

import { warsawToday } from "@/lib/warsaw-date"

export const ANNOUNCEMENT_TITLE_MIN = 3
export const ANNOUNCEMENT_TITLE_MAX = 160
export const ANNOUNCEMENT_BODY_MAX = 4000
export const ANNOUNCEMENT_MAX_DAYS_AHEAD = 90
/** Ile ogłoszeń panel pokazuje od razu, reszta pod „Pokaż wszystkie”. */
export const ANNOUNCEMENTS_VISIBLE = 3

/** Role do wyboru w „Odbiorcy”, w kolejności na ekranie. */
export const AUDIENCE_ROLE_LABELS: Record<string, string> = {
  recruiter: "Rekruterzy",
  delivery_lead: "Delivery Leadzi",
  head_of_recruitment: "Head of Recruitment",
  talent_community_manager: "Talent Community Manager",
  admin: "Administratorzy",
  finance: "Finanse",
  employee: "Konsultanci/Kontraktorzy",
  board: "Rada nadzorcza",
  automation: "Automatyzacje",
  trainee: "Praktykanci",
}

export function audienceLabel(roles: readonly string[]): string {
  if (roles.length === 0) return "wszyscy"
  return roles.map((role) => AUDIENCE_ROLE_LABELS[role] ?? role).join(", ")
}

export interface AnnouncementForm {
  title: string
  body: string
  /** `YYYY-MM-DD`, ostatni dzień widoczności (włącznie). */
  visibleUntil: string
  audience: "all" | "roles"
  roles: string[]
  pinned: boolean
  important: boolean
}

export type AnnouncementFormErrors = Partial<Record<"title" | "body" | "visibleUntil" | "roles", string>>

const HTML_TAG = /<\s*\/?\s*[a-zA-Z][^<>]*>/

function addDays(isoDate: string, days: number): string {
  const moment = new Date(`${isoDate}T12:00:00Z`)
  moment.setUTCDate(moment.getUTCDate() + days)
  return moment.toISOString().slice(0, 10)
}

/** Domyślne „widoczne do”: tydzień od dziś (kalendarz firmy). */
export function defaultVisibleUntil(now: Date = new Date()): string {
  return addDays(warsawToday(now), 7)
}

export function maxVisibleUntil(now: Date = new Date()): string {
  return addDays(warsawToday(now), ANNOUNCEMENT_MAX_DAYS_AHEAD)
}

export function validateAnnouncement(form: AnnouncementForm, now: Date = new Date()): AnnouncementFormErrors {
  const errors: AnnouncementFormErrors = {}
  const title = form.title.replace(/\s+/g, " ").trim()
  if (title.length < ANNOUNCEMENT_TITLE_MIN || title.length > ANNOUNCEMENT_TITLE_MAX) {
    errors.title = `Tytuł: od ${ANNOUNCEMENT_TITLE_MIN} do ${ANNOUNCEMENT_TITLE_MAX} znaków.`
  }
  const body = form.body.trim()
  if (!body || body.length > ANNOUNCEMENT_BODY_MAX) {
    errors.body = `Treść: od 1 do ${ANNOUNCEMENT_BODY_MAX} znaków.`
  }
  if (!errors.title && !errors.body && (HTML_TAG.test(title) || HTML_TAG.test(body))) {
    errors.body = "Ogłoszenie to zwykły tekst — usuń znaczniki HTML (<…>)."
  }
  const today = warsawToday(now)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.visibleUntil)) {
    errors.visibleUntil = "Wybierz datę „widoczne do”."
  } else if (form.visibleUntil < today) {
    errors.visibleUntil = "„Widoczne do” nie może być w przeszłości."
  } else if (form.visibleUntil > maxVisibleUntil(now)) {
    errors.visibleUntil = `„Widoczne do” najdalej ${ANNOUNCEMENT_MAX_DAYS_AHEAD} dni od dziś.`
  }
  if (form.audience === "roles" && form.roles.length === 0) {
    errors.roles = "Wybierz co najmniej jedną rolę albo „Wszyscy”."
  }
  return errors
}

/** `12.11` z `2026-11-12`. */
export function shortDay(isoDate: string): string {
  const [, month, day] = isoDate.split("-")
  return `${day}.${month}`
}

const TIME_FORMAT = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  hour: "2-digit",
  minute: "2-digit",
})

/** „dziś 17:41”, „wczoraj 9:05” albo „27.10” — kiedy opublikowano. */
export function publishedLabel(createdAt: string, now: Date = new Date()): string {
  const moment = new Date(createdAt)
  const day = warsawToday(moment)
  const today = warsawToday(now)
  if (day === today) return `dziś ${TIME_FORMAT.format(moment)}`
  if (day === addDays(today, -1)) return `wczoraj ${TIME_FORMAT.format(moment)}`
  return shortDay(day)
}
