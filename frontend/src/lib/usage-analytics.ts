/**
 * Analityka użycia ekranów i przycisków (PostHog Cloud EU, decyzja Artura 28.11.2026).
 *
 * Cel: wiedzieć, których ekranów i przycisków nikt nie używa (do usunięcia) i czy
 * nowe funkcje są używane. To pomiar pracy zespołu, więc zbieramy tylko tyle:
 * - **ekran** jako wzorzec trasy (`/candidates/[id]`), nigdy adres z id ani query string,
 * - **kliknięcie** jako `data-track` z kodu albo wzorzec celu linku; nigdy tekst przycisku,
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

// Statyczne człony tras z `src/app`, policzone przy buildzie (`appRouteSegments`
// w `next.config.ts`). Bez listy wszystko spoza parametrów wychodzi jako `[id]`.
const APP_ROUTE_SEGMENTS: ReadonlySet<string> = new Set(
  (process.env.NEXUS_ROUTE_SEGMENTS ?? "").split(",").filter(Boolean),
);

function decoded(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/**
 * Wzorzec trasy: wartości parametrów z `useParams()` zamienione na `[nazwa]`, człon
 * z katalogów `src/app` bez zmian, każdy inny na `[id]`. Wygląd członu nie decyduje:
 * ręcznie wpisany `/candidates/jan-kowalski` (404, bez parametrów) to `/candidates/[id]`.
 */
export function routePattern(
  pathname: string,
  params: RouteParams = {},
  statics: ReadonlySet<string> = APP_ROUTE_SEGMENTS,
): string {
  const byValue = new Map<string, string>();
  for (const [name, value] of Object.entries(params)) {
    const values = Array.isArray(value) ? value : value === undefined ? [] : [value];
    const label = Array.isArray(value) ? `[...${name}]` : `[${name}]`;
    for (const item of values) if (item) byValue.set(decoded(item), label);
  }
  const path = pathname.split(/[?#]/, 1)[0];
  const segments = path.split("/").filter(Boolean).map(segment => {
    const value = decoded(segment);
    return byValue.get(value) ?? (statics.has(value) ? value : "[id]");
  });
  return `/${segments.join("/")}`;
}

// Nazwa kliknięcia nigdy nie pochodzi z tekstu, `aria-label` ani `title`: po samym
// tekście nie da się odróżnić „Zapisz” od „Nordea” czy „Anna” (przegląd bezpieczeństwa
// 28.11.2026, decyzja Artura: tylko `data-track` i cel linku).
const TRACK_ID = /^[a-z][a-z0-9._-]{0,63}$/;

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

export interface ClickTarget {
  target: string | null;
  source: "data-track" | "link" | "brak";
  element: string;
}

/** Wzorzec trasy linku wewnętrznego (`/clients/[id]`); link na zewnątrz i nie-HTTP to `null`. */
function linkTarget(element: Element, statics: ReadonlySet<string>): string | null {
  if (!(element instanceof HTMLAnchorElement)) return null;
  try {
    const url = new URL(element.href, window.location.href);
    return url.origin === window.location.origin ? routePattern(url.pathname, {}, statics) : null;
  } catch {
    return null;
  }
}

/** Co kliknięto, bez treści: `data-track`, wzorzec celu linku albo sam rodzaj elementu. */
export function describeClick(
  origin: EventTarget | null,
  statics: ReadonlySet<string> = APP_ROUTE_SEGMENTS,
): ClickTarget | null {
  if (!(origin instanceof Element)) return null;
  const tracked = origin.closest("[data-track]");
  const clickable = origin.closest(CLICKABLE) ?? tracked;
  if (!clickable) return null;
  const element = clickable.getAttribute("role") ?? clickable.tagName.toLowerCase();
  const trackId = tracked?.getAttribute("data-track")?.trim() ?? "";
  if (tracked && TRACK_ID.test(trackId)) return { target: trackId, source: "data-track", element };
  const link = linkTarget(clickable, statics);
  return link ? { target: link, source: "link", element } : { target: null, source: "brak", element };
}

// Wszystko, co może nieść adres, tytuł strony (bywa w nim nazwisko), źródło wejścia
// albo treść elementu. Do tego żadnych obiektów i adresów w wartościach.
const PRIVATE_PROPERTY = /url|pathname|referr|host|search|hash|title|utm_|gclid|fbclid|msclkid|elements|el_text|query|person_info|\$set/i;
const ADDRESS_VALUE = /^(?:[a-z][a-z0-9+.-]*:|\/)/i;
// Cel linku z `describeClick` to wzorzec trasy (`/clients/[id]`): małe litery, `[nazwa]`,
// najwyżej trzy cyfry z rzędu (`microsoft365`). Adres z id tego nie spełnia.
const ROUTE_PATTERN_VALUE = /^\/(?:[a-z0-9-]+|\[(?:\.\.\.)?[A-Za-z]+\])(?:\/(?:[a-z0-9-]+|\[(?:\.\.\.)?[A-Za-z]+\]))*$/;

function isPublicValue(key: string, value: unknown): boolean {
  if (value === null || typeof value === "number" || typeof value === "boolean") return true;
  if (typeof value !== "string") return false;
  if (key === "target" && ROUTE_PATTERN_VALUE.test(value) && !/\d{4,}/.test(value)) return true;
  return !ADDRESS_VALUE.test(value);
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
    if (!PRIVATE_PROPERTY.test(key) && isPublicValue(key, value)) kept[key] = value;
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
