/**
 * Analityka użycia ekranów i przycisków (PostHog Cloud EU, decyzja Artura 28.11.2026).
 *
 * Cel: wiedzieć, których ekranów i przycisków nikt nie używa (do usunięcia) i czy
 * nowe funkcje są używane. To pomiar pracy zespołu, więc zbieramy tylko tyle:
 * - **ekran** jako wzorzec trasy (`/candidates/[id]`), nigdy adres z id ani query string,
 * - **przycisk** jako `data-track` albo krótka nazwa dostępności, bez treści wpisów,
 * - **osoba** jako `user-<id>` i rola, bez maila i nazwiska.
 *
 * Włącza backend (`USAGE_ANALYTICS_ENABLED` + `POSTHOG_PROJECT_KEY`), a front dostaje
 * klucz z sondy `/api/health/live`. Bez klucza `posthog-js` nie jest nawet ładowany.
 * Autocapture, nagrania sesji, heatmapy, ankiety, flagi i skrypty z CDN PostHog są
 * wyłączone; `before_send` przepuszcza tylko dwa nasze zdarzenia.
 * `docs/claude/podstawy/analityka-uzycia-posthog.md`.
 */
import type { CaptureResult, PostHog, Properties } from "posthog-js";

export const POSTHOG_HOST = "https://eu.i.posthog.com";

/** Jedyne zdarzenia, jakie wychodzą: odsłona ekranu i kliknięcie przycisku. */
const ALLOWED_EVENTS = new Set(["$pageview", "ui_click"]);

type RouteParams = Readonly<Record<string, string | string[] | undefined>>;

// Człony statyczne tras mają małe litery, myślniki i najwyżej kilka cyfr
// (`microsoft365`, `pipeline-v4`). Identyfikator, token i slug spoza parametrów
// trasy tego nie spełniają albo pasują do parametru z `useParams()`.
const STATIC_SEGMENT = /^[a-z][a-z0-9-]{0,39}$/;
const MAX_STATIC_DIGITS = 3;
// Statyczne trasy z samych cyfr (`app/403`).
const NUMERIC_ROUTES = new Set(["403"]);

function decoded(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

function isStaticSegment(segment: string): boolean {
  if (NUMERIC_ROUTES.has(segment)) return true;
  const digits = segment.match(/\d/g)?.length ?? 0;
  return STATIC_SEGMENT.test(segment) && digits <= MAX_STATIC_DIGITS;
}

/**
 * Wzorzec trasy: wartości parametrów z `useParams()` zamienione na `[nazwa]`,
 * a każdy inny człon, który nie wygląda na statyczny, na `[id]` (404, stary link).
 */
export function routePattern(pathname: string, params: RouteParams = {}): string {
  const byValue = new Map<string, string>();
  for (const [name, value] of Object.entries(params)) {
    const values = Array.isArray(value) ? value : value === undefined ? [] : [value];
    const label = Array.isArray(value) ? `[...${name}]` : `[${name}]`;
    for (const item of values) if (item) byValue.set(decoded(item), label);
  }
  const path = pathname.split(/[?#]/, 1)[0];
  const segments = path.split("/").filter(Boolean).map(segment => {
    const value = decoded(segment);
    return byValue.get(value) ?? (isStaticSegment(value) ? value : "[id]");
  });
  return `/${segments.join("/")}`;
}

// Nazwa przycisku idzie do PostHog tylko, gdy wygląda na etykietę z interfejsu,
// a nie na dane: krótka, bez cyfr (liczniki, kwoty, daty, id), bez znaków adresów
// i maili, a po pierwszym słowie bez wyrazów z wielkiej litery (imiona, nazwiska,
// firmy). Skróty do czterech wielkich liter (CV, PDF, DL, B2B) przechodzą.
const MAX_LABEL_LENGTH = 60;
const MAX_LABEL_WORDS = 6;
const SHORT_ACRONYM = /^(?:[A-ZĄĆĘŁŃÓŚŹŻ]{2,4}|B2B)$/;
const UPPERCASE_START = /^[A-ZĄĆĘŁŃÓŚŹŻ]/;
const DATA_CHARS = /[@/\\:#%=?&<>{}[\]|+_]/;
const TRACK_ID = /^[a-z][a-z0-9._-]{0,63}$/;

/** Etykieta przycisku albo `null`, gdy mogłaby nieść dane osoby lub rekordu. */
export function safeLabel(raw: string | null | undefined): string | null {
  const text = (raw ?? "").replace(/\s+/g, " ").trim();
  if (!text || text.length > MAX_LABEL_LENGTH || DATA_CHARS.test(text)) return null;
  const words = text.split(" ");
  if (words.length > MAX_LABEL_WORDS) return null;
  for (const [index, word] of words.entries()) {
    if (SHORT_ACRONYM.test(word)) continue;
    if (/\d/.test(word)) return null;
    if (index > 0 && UPPERCASE_START.test(word)) return null;
  }
  return text;
}

const CLICKABLE = [
  "button",
  "a[href]",
  "summary",
  'input[type="button"]',
  'input[type="submit"]',
  '[role="button"]',
  '[role="link"]',
  '[role="tab"]',
  '[role="menuitem"]',
  '[role="menuitemcheckbox"]',
  '[role="menuitemradio"]',
  '[role="switch"]',
].join(", ");
// Wiersze tabel i listy to dane (kandydat, klient, kwota): tekst przycisku stamtąd
// nie idzie, tylko etykieta wpisana przez programistę (`aria-label`, `title`).
const DATA_CONTEXT = 'tr, li, [role="row"], [role="gridcell"], [role="listitem"], [role="option"]';

export interface ClickTarget {
  target: string | null;
  source: "data-track" | "nazwa" | "brak";
  element: string;
}

function developerLabel(element: Element): string | null {
  return element.getAttribute("aria-label") ?? element.getAttribute("title");
}

/** Co kliknięto, bez treści: `data-track`, krótka nazwa dostępności albo nic. */
export function describeClick(origin: EventTarget | null): ClickTarget | null {
  if (!(origin instanceof Element)) return null;
  const tracked = origin.closest("[data-track]");
  const clickable = origin.closest(CLICKABLE) ?? tracked;
  if (!clickable) return null;
  const element = clickable.getAttribute("role") ?? clickable.tagName.toLowerCase();
  const trackId = tracked?.getAttribute("data-track")?.trim() ?? "";
  if (tracked && TRACK_ID.test(trackId)) return { target: trackId, source: "data-track", element };
  const fromDeveloper = developerLabel(clickable);
  const visible = clickable instanceof HTMLInputElement ? clickable.value : clickable.textContent;
  const raw = fromDeveloper ?? (clickable.closest(DATA_CONTEXT) ? null : visible);
  const target = safeLabel(raw);
  return { target, source: target ? "nazwa" : "brak", element };
}

// Wszystko, co może nieść adres, tytuł strony (bywa w nim nazwisko), źródło wejścia
// albo treść elementu. Do tego żadnych obiektów i adresów w wartościach.
const PRIVATE_PROPERTY = /url|pathname|referr|host|search|hash|title|utm_|gclid|fbclid|msclkid|elements|el_text|query|person_info|\$set/i;
const ADDRESS_VALUE = /^(?:[a-z][a-z0-9+.-]*:|\/)/i;

function isPublicValue(value: unknown): boolean {
  if (value === null || typeof value === "number" || typeof value === "boolean") return true;
  return typeof value === "string" && !ADDRESS_VALUE.test(value);
}

/**
 * `before_send`: tylko nasze dwa zdarzenia, tylko przy aktywnej osobie i ekranie,
 * adres zastąpiony wzorcem trasy, bez `$set_once` i właściwości z adresami.
 */
export function scrubEvent(
  event: CaptureResult | null,
  state: { screen: string | null; active: boolean; origin: string },
): CaptureResult | null {
  if (!event || !state.active || !state.screen || !ALLOWED_EVENTS.has(event.event)) return null;
  if (state.screen.startsWith("/preview")) return null;
  const kept: Properties = {};
  for (const [key, value] of Object.entries(event.properties ?? {})) {
    if (!PRIVATE_PROPERTY.test(key) && isPublicValue(value)) kept[key] = value;
  }
  const scrubbed: CaptureResult = {
    uuid: event.uuid,
    event: event.event,
    timestamp: event.timestamp,
    properties: {
      ...kept,
      $current_url: `${state.origin}${state.screen}`,
      $pathname: state.screen,
      $host: new URL(state.origin).host,
      screen: state.screen,
    },
  };
  return scrubbed;
}

interface Session {
  key: string;
  userId: number;
  role: string;
}

let client: PostHog | null = null;
let identity: string | null = null;
let screen: string | null = null;

function onClick(event: MouseEvent): void {
  const click = describeClick(event.target);
  if (click && identity) client?.capture("ui_click", { ...click });
}

function initOptions(distinctID: string) {
  const origin = window.location.origin;
  return {
    api_host: POSTHOG_HOST,
    // Nic w ciasteczkach ani w pamięci przeglądarki; osobę daje id z sesji.
    persistence: "memory" as const,
    bootstrap: { distinctID, isIdentifiedID: true },
    person_profiles: "identified_only" as const,
    autocapture: false,
    capture_pageview: false,
    capture_pageleave: false,
    capture_dead_clicks: false,
    capture_heatmaps: false,
    capture_performance: false,
    capture_exceptions: false,
    rageclick: false,
    disable_session_recording: true,
    disable_surveys: true,
    disable_product_tours: true,
    disable_conversations: true,
    disable_web_experiments: true,
    // Bez skryptów z CDN PostHog (nagrywanie, ankiety, toolbar) i bez `/flags`
    // ani zdalnej konfiguracji: jedynym celem zapytań jest `eu.i.posthog.com/e/`.
    disable_external_dependency_loading: true,
    advanced_disable_flags: true,
    advanced_disable_toolbar_metrics: true,
    save_referrer: false,
    save_campaign_params: false,
    mask_all_text: true,
    mask_all_element_attributes: true,
    mask_personal_data_properties: true,
    // Nagrania są wyłączone wyżej. Gdyby ktoś je kiedyś włączył, to tylko tak jak
    // Replay w Sentry: cały tekst i pola zamaskowane, media zablokowane.
    session_recording: {
      maskAllInputs: true,
      maskTextSelector: "*",
      blockSelector: "img, video, canvas, svg, iframe",
    },
    before_send: (event: CaptureResult | null) =>
      scrubEvent(event, { screen, active: identity !== null, origin }),
  };
}

/** Ekran zmienił się (wzorzec, nie adres): jedna odsłona na zmianę wzorca. */
export function setUsageScreen(next: string): void {
  if (next === screen) return;
  screen = next;
  if (identity) client?.capture("$pageview");
}

/** Start po kluczu z API. `posthog-js` ładuje się dopiero tutaj. */
export async function startUsageAnalytics({ key, userId, role }: Session): Promise<void> {
  const distinctID = `user-${userId}`;
  if (identity === distinctID && client) return;
  identity = distinctID;
  const { default: posthog } = await import("posthog-js");
  if (identity !== distinctID) return;
  if (client) {
    client.reset();
    client.identify(distinctID);
  } else {
    posthog.init(key, initOptions(distinctID));
    client = posthog;
    document.addEventListener("click", onClick, { capture: true });
  }
  client.register({ role });
  if (screen) client.capture("$pageview");
}

/** Wylogowanie, „Podgląd jako” albo wyłączenie: nic więcej nie wychodzi. */
export function stopUsageAnalytics(): void {
  if (!identity) return;
  identity = null;
  client?.reset();
}

/** Tylko dla testów: stan modułu między przypadkami. */
export function resetUsageAnalyticsForTests(): void {
  identity = null;
  screen = null;
  client = null;
  document.removeEventListener("click", onClick, { capture: true });
}
