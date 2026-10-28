// Czysta logika widoku panelu (bez DOM i `chrome.*`) — testowana w node.

import { ERROR_KINDS } from "../api.js";

export const SCREENS = Object.freeze({
  CONNECT: "connect",
  LOADING: "loading",
  UNSUPPORTED: "unsupported",
  ERROR: "error",
  LIMIT: "limit",
  ADD: "add", // osoby nie ma w NEXUSIE (także off-limits: pytanie, jak się zgłosiła)
  PERSON: "person", // osoba jest w NEXUSIE
  AMBIGUOUS: "ambiguous", // kilka osób pasuje
  LIST: "list", // wyniki wyszukiwania / projekt
  NOT_READ: "not_read", // strona profilu jeszcze się nie wczytała
});

/**
 * Ekran z odpowiedzi `/lookup`. `off_limits` i `contractor` to flagi na
 * ekranie, nie osobne ekrany: off-limits bez osoby w bazie zmienia ekran
 * „Dodaj” w pytanie „jak się zgłosił”, a przy osobie w bazie dokłada ramkę.
 */
export function chooseScreen(lookup) {
  const flags = { offLimits: lookup.off_limits || null, contractor: lookup.contractor || null };
  if (lookup.status === "found") return { screen: SCREENS.PERSON, ...flags };
  if (lookup.status === "ambiguous") return { screen: SCREENS.AMBIGUOUS, ...flags };
  return { screen: SCREENS.ADD, ...flags };
}

/** Błąd API → ekran. Awaria nigdy nie kończy się ekranem „Nie ma w NEXUSIE”. */
export function screenForError(err) {
  switch (err?.kind) {
    case ERROR_KINDS.NOT_CONNECTED:
    case ERROR_KINDS.KEY_INVALID:
      return { screen: SCREENS.CONNECT, message: err.kind === ERROR_KINDS.KEY_INVALID ? err.message : null };
    case ERROR_KINDS.DAILY_LIMIT:
      return { screen: SCREENS.LIMIT, message: err.message };
    default:
      return {
        screen: SCREENS.ERROR,
        message: err?.message || "Nie udało się połączyć z NEXUSEM. Spróbuj ponownie.",
        retryable: err?.kind !== ERROR_KINDS.FORBIDDEN,
      };
  }
}

const pad = (n) => String(n).padStart(2, "0");

function ymd(value) {
  const m = String(value || "").match(/^(\d{4})-(\d{2})(?:-(\d{2}))?/);
  return m ? { y: +m[1], m: +m[2], d: m[3] ? +m[3] : null } : null;
}

/** "2024-03-02" → "03.2024" */
export function formatMonthYear(value) {
  const p = ymd(value);
  return p ? `${pad(p.m)}.${p.y}` : "";
}

/** "2024-03-02T10:00:00Z" → "02.03.2024" (data z ciągu, bez przesuwania stref) */
export function formatDate(value) {
  const p = ymd(value);
  if (!p) return "";
  return p.d ? `${pad(p.d)}.${pad(p.m)}.${p.y}` : `${pad(p.m)}.${p.y}`;
}

export function inNexusSinceLabel(candidate) {
  const since = formatMonthYear(candidate?.in_nexus_since);
  return since ? `W NEXUSIE od ${since}` : "W NEXUSIE";
}

/** Data dzisiejsza jako "DD.MM.RRRR" w kalendarzu Warszawy. */
export function todayLabel(now = new Date()) {
  const parts = new Intl.DateTimeFormat("pl-PL", { timeZone: "Europe/Warsaw", day: "2-digit", month: "2-digit", year: "numeric" }).formatToParts(now);
  const get = (t) => parts.find((x) => x.type === t)?.value;
  return `${get("day")}.${get("month")}.${get("year")}`;
}

function warsawYearMonth(now) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw", year: "numeric", month: "2-digit" }).formatToParts(now);
  return `${parts.find((x) => x.type === "year").value}-${parts.find((x) => x.type === "month").value}`;
}

const monthIndex = (ym) => {
  const p = ymd(`${ym}-01`.slice(0, 10));
  return p ? p.y * 12 + (p.m - 1) : null;
};

/**
 * Łączny staż w miesiącach z historii pracy. Nakładające się pozycje liczą
 * się raz (dwie role naraz to nie podwójny staż). Miesiąc startu i końca
 * wliczony, jak liczy LinkedIn („sty 2019 – gru 2019” = 12 mies.).
 */
export function tenureMonths(experience, now = new Date()) {
  const nowIdx = monthIndex(warsawYearMonth(now));
  const ranges = [];
  for (const e of experience || []) {
    const s = monthIndex(e.start);
    if (s === null) continue;
    const end = e.current || !e.end ? nowIdx : monthIndex(e.end);
    if (end === null || end < s) continue;
    ranges.push([s, Math.min(end, nowIdx)]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  let total = 0;
  let cur = null;
  for (const [s, e] of ranges) {
    if (!cur || s > cur[1] + 1) {
      if (cur) total += cur[1] - cur[0] + 1;
      cur = [s, e];
    } else {
      cur[1] = Math.max(cur[1], e);
    }
  }
  if (cur) total += cur[1] - cur[0] + 1;
  return total;
}

export function pluralYears(n) {
  if (n === 1) return "rok";
  const last = n % 10;
  const lastTwo = n % 100;
  if (last >= 2 && last <= 4 && !(lastTwo >= 12 && lastTwo <= 14)) return "lata";
  return "lat";
}

/** 87 → "7 lat 3 mies.", 12 → "1 rok", 5 → "5 mies.", 0 → "" */
export function formatTenure(months) {
  if (!months || months < 1) return "";
  const y = Math.floor(months / 12);
  const m = months % 12;
  const parts = [];
  if (y) parts.push(`${y} ${pluralYears(y)}`);
  if (m) parts.push(`${m} mies.`);
  return parts.join(" ");
}

/** „Fikcyjna Software · od 03.2022” z bieżącej pozycji. */
export function companySinceLabel(profile) {
  const company = profile?.current_company;
  if (!company) return "";
  const cur = (profile.experience || []).find((e) => e.current && e.start && (!e.company || e.company === company));
  return cur ? `${company} · od ${formatMonthYear(cur.start)}` : company;
}

export function scoreTone(score) {
  return Number(score) >= 70 ? "success" : "warning";
}

export function addButtonLabel(selectedCount) {
  return selectedCount > 0 ? `Dodaj do NEXUSA i do ${selectedCount} rekrutacji` : "Dodaj do NEXUSA";
}

export function firstName(fullName) {
  return String(fullName || "").trim().split(/\s+/)[0] || "";
}

export function initialsOf(user) {
  if (user?.initials) return user.initials;
  return String(user?.name || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0].toUpperCase())
    .join("");
}

export function usageLabel(usage) {
  if (!usage || usage.reads_limit == null) return "";
  return `Dziś: ${usage.reads_today ?? 0} / ${usage.reads_limit} odczytów`;
}

function versionParts(v) {
  return typeof v === "string" && /^\d+(\.\d+){0,3}$/.test(v) ? v.split(".").map(Number) : null;
}

/**
 * Baner „Jest nowa wersja” — wtyczka z ZIP-a nie aktualizuje się sama.
 * `me.latest_version` z NEXUSA, `current` z manifestu. Link na stronę pobrania
 * NEXUSA z połączenia (frontUrl sprawdzony przy łączeniu). `updateUrl` =
 * `update_url` manifestu: ma go wersja ze sklepu i .crx z polityki Intune —
 * te Chrome aktualizuje sam, więc baner z linkiem do ZIP-a tylko by mylił.
 */
export function updateNotice(me, current, connection, updateUrl) {
  const latest = versionParts(me?.latest_version);
  const mine = versionParts(current);
  if (updateUrl || !latest || !mine || !connection?.frontUrl) return null;
  for (let i = 0; i < Math.max(latest.length, mine.length); i += 1) {
    const d = (latest[i] || 0) - (mine[i] || 0);
    if (d < 0) return null;
    if (d > 0) return { version: me.latest_version, url: `${connection.frontUrl}/wtyczka` };
  }
  return null;
}

/** Pill etapu w rekrutacji. Zamknięte: „Odrzucona · powód”. */
export function processPill(process) {
  if (process.closed) {
    return { text: process.close_label ? `Odrzucona · ${process.close_label}` : "Odrzucona", tone: "error" };
  }
  return { text: process.stage_label || "W procesie", tone: "info" };
}

export function rodoTone(rodo) {
  if (!rodo) return "muted";
  if (rodo.status === "valid") return "success";
  if (rodo.status === "expired") return "warning";
  return "muted";
}

export function rodoLabel(rodo) {
  if (!rodo) return "brak danych";
  if (rodo.label) return rodo.label;
  return { valid: "zgoda ważna", expired: "zgoda wygasła", none: "brak zgody" }[rodo.status] || "brak danych";
}

/** Rekrutacja domyślna dla wiadomości: otwarty proces, potem najlepsze dopasowanie. */
export function defaultJobId(lookup) {
  const open = (lookup?.processes || []).find((p) => !p.closed);
  if (open) return open.job_id;
  const best = [...(lookup?.matches || [])].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0];
  return best ? best.job_id : null;
}

// Klucze z NEXUSA (kontrakt z backendem). `skip` = „to my chcieliśmy napisać”
// → osoba trafia do bazy bez rekrutacji.
export const OFF_LIMITS_SKIP = "skip";
export const OFF_LIMITS_HOW = Object.freeze([
  { value: "linkedin_inbound", label: "Napisał(a) do nas na LinkedInie" },
  { value: "sent_cv_before", label: "Wcześniej sam(a) przysłał(a) CV" },
  { value: "job_ad", label: "Zaaplikował(a) na ogłoszenie" },
  { value: "phone_or_email", label: "Zadzwonił(a) albo napisał(a) maila" },
  { value: "referral", label: "Polecenie innej osoby" },
  { value: "left_company", label: "Już tam nie pracuje" },
  { value: OFF_LIMITS_SKIP, label: "Nie, to my chcieliśmy napisać" },
]);

export function offLimitsButtonLabel(how) {
  return how === OFF_LIMITS_SKIP ? "Dodaj tylko do bazy, bez rekrutacji" : "Dodaj: sam się zgłosił";
}

/** Rekrutacje, do których faktycznie dopisujemy przy danej odpowiedzi off-limits. */
export function jobIdsForHow(how, jobIds) {
  return how === OFF_LIMITS_SKIP ? [] : jobIds;
}

export function offLimitsText(offLimits) {
  const company = offLimits?.company || offLimits?.client_name || "tej firmie";
  const client = offLimits?.client_name || "klient";
  return `Pracuje w ${company}, a ${client} ma aktywne zamówienia. Umowa z klientem zabrania nam odzywać się pierwszym. Jeśli sam napisał do nas, dodaj go i wskaż, jak się zgłosił.`;
}

export function contractorText(contractor) {
  const dl = contractor?.delivery_lead_name || "Delivery Leadem";
  const end = contractor?.end_date ? ` do ${formatDate(contractor.end_date)}` : "";
  return `To nasz kontraktor. Pracuje przez B2B Network w ${contractor?.client_name || "u klienta"}${end}. Delivery Lead: ${dl}. Nie proponuj mu innych projektów bez rozmowy z ${dl}.`;
}

export function ownerText(owner) {
  const last = owner?.last_contact_at ? `Ostatni kontakt ${formatDate(owner.last_contact_at)}.` : "Brak zapisanego kontaktu.";
  return `Prowadzi ją ${owner?.name || "ktoś z zespołu"}. ${last} Zanim napiszesz, daj jej znać.`;
}

// ── Lista wyników ─────────────────────────────────────────────────────────

export const BATCH_STATUS = Object.freeze({
  new: { label: "Nowi", pill: "Nowa", tone: "success" },
  in_process: { label: "W procesie", pill: "W procesie", tone: "info" },
  in_base: { label: "W bazie", pill: "W bazie", tone: "muted" },
  off_limits: { label: "Off-limits", pill: "Off-limits", tone: "error" },
  contractor: { label: "Kontraktorzy", pill: "Kontraktor", tone: "warning" },
});

export function batchCounters(items) {
  const counts = { new: 0, in_process: 0, in_base: 0, off_limits: 0, contractor: 0 };
  for (const it of items || []) if (it.status in counts) counts[it.status] += 1;
  return counts;
}

/** Off-limits i kontraktora nie da się zaznaczyć do dodania z listy. */
export function isSelectable(item) {
  return item.status !== "off_limits" && item.status !== "contractor";
}

/** Domyślnie zaznaczeni są tylko nowi. */
export function defaultSelected(item) {
  return item.status === "new";
}

/** ProfileRead z pozycji listy — tylko to, co widać w wynikach. */
export function profileFromListPerson(person, pageUrl, source) {
  return {
    page_kind: source === "search" ? "profile" : "recruiter_profile",
    page_url: pageUrl,
    public_url: person.public_url || null,
    full_name: person.full_name,
    headline: person.headline || null,
    location: null,
    current_company: person.current_company || null,
    current_title: null,
    experience: [],
    skills: [],
    about: null,
  };
}

export const MESSAGE_KINDS = Object.freeze([
  { value: "inmail", label: "InMail", channel: "inmail" },
  { value: "invitation", label: "Zaproszenie · 300 zn.", channel: "invitation", limit: 300 },
  { value: "linkedin_message", label: "Wiadomość", channel: "linkedin_message" },
]);

export const CONTACT_CHANNELS = Object.freeze([
  { value: "inmail", label: "InMail" },
  { value: "invitation", label: "Zaproszenie" },
  { value: "linkedin_message", label: "Wiadomość" },
  { value: "phone", label: "Telefon" },
]);

// Etykiety kanałów na osi „Kontakty zespołu” — te same, które zwraca NEXUS
// (`CHANNEL_LABELS` w backend/app/services/linkedin_extension_lookup.py).
export const TIMELINE_CHANNEL_LABELS = Object.freeze({
  inmail: "InMail",
  invitation: "zaproszenie na LinkedInie",
  linkedin_message: "wiadomość na LinkedInie",
  phone: "telefon",
});

/**
 * Kontakt zapisany w panelu → od razu na osi osoby, bez ponownego odczytu
 * strony (odczyt liczy się do limitu dziennego).
 */
export function withLocalContact(lookup, { channel, note, userName, at = new Date().toISOString() }) {
  if (!lookup) return lookup;
  const entry = { at, user_name: userName || null, channel_label: TIMELINE_CHANNEL_LABELS[channel] || "kontakt", note: note || null };
  return { ...lookup, contacts: [entry, ...(lookup.contacts || [])].slice(0, 4) };
}

export const FIELD_LABELS = Object.freeze({
  full_name: "Osoba",
  current_title: "Stanowisko",
  current_company: "Firma",
  location: "Miasto",
  headline: "Nagłówek",
});
