/**
 * Routing publicznej strony kariery (`kariera.dynaminds.pl`) — czyste funkcje.
 *
 * Ta sama aplikacja Next.js obsługuje NEXUSA i stronę kariery. O tym, którą
 * z nich widzi odwiedzający, decyduje HOST żądania: na hoście kariery
 * middleware przepisuje widoczne adresy (`/r/<slug>`, `/<slug>`, `/rodo`) na
 * trasy `/kariera/*`, a WSZYSTKO inne zamienia w 404 — łącznie z `/dashboard`,
 * `/candidates` i resztą aplikacji. Granica jest więc „domyślnie zamknięta":
 * nowa trasa aplikacji nie wycieknie na domenę kariery.
 *
 * Host czytamy z `x-forwarded-host` (Traefik/Coolify), dopiero potem z `host`.
 * Lista hostów przychodzi z `NEXT_PUBLIC_CAREER_HOST` (kilka po przecinku).
 * Zmienna MUSI być czytana literałem `process.env.NEXT_PUBLIC_CAREER_HOST` —
 * Next.js wkleja ją w czasie builda (także w middleware), dynamiczny dostęp
 * zwróciłby `undefined`.
 */

/** Prefiks tras strony kariery w drzewie `app/`. */
export const CAREER_PREFIX = "/kariera";

/** Slug stałego linku rekrutera: a-z0-9 i myślnik, 3–40 znaków. */
export const RECRUITER_SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{1,38})[a-z0-9]$/;
/** Slug linku rekrutacji (tytuł + 4 losowe znaki) — dłuższy niż rekrutera. */
export const JOB_SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{1,118})[a-z0-9]$/;

/** Normalizuje wartość nagłówka hosta: pierwszy wpis, małe litery, bez portu. */
export function normalizeHost(value: string | null | undefined): string {
  if (!value) return "";
  const first = value.split(",")[0]?.trim().toLowerCase() ?? "";
  // IPv6 w nawiasach: [::1]:3000 → [::1]
  if (first.startsWith("[")) return first.slice(0, first.indexOf("]") + 1);
  return first.replace(/:\d+$/, "");
}

/** Hosty kariery z env (albo z argumentu — w testach). */
export function careerHosts(
  raw: string | undefined = process.env.NEXT_PUBLIC_CAREER_HOST,
): string[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((h) => normalizeHost(h.replace(/^https?:\/\//, "").replace(/\/.*$/, "")))
    .filter(Boolean);
}

export function isCareerHost(
  host: string | null | undefined,
  hosts: string[] = careerHosts(),
): boolean {
  const h = normalizeHost(host);
  return h !== "" && hosts.includes(h);
}

/** Host żądania: `x-forwarded-host` ma pierwszeństwo przed `host`. */
export function requestHost(headers: { get(name: string): string | null }): string {
  return normalizeHost(headers.get("x-forwarded-host") || headers.get("host"));
}

export type CareerRoute =
  | { kind: "rewrite"; path: string }
  | { kind: "pass" }
  | { kind: "not-found" };

/**
 * Co zrobić z widoczną ścieżką na hoście kariery.
 *
 * - `/` → `/kariera` (strona startowa),
 * - `/rodo` → `/kariera/rodo`,
 * - `/r/<slug>` → `/kariera/r/<slug>` (link rekrutacji),
 * - `/<slug>` → `/kariera/p/<slug>` (stały link rekrutera),
 * - `/kariera/*`, `/_next/*`, `/favicon*` → bez zmian (grafiki OG i assety),
 * - reszta → 404.
 *
 * Slug jest dopasowywany bez względu na wielkość liter (link przepisany ręcznie
 * z posta na LinkedInie bywa „Marta-N"), ale przepisujemy go małymi literami.
 */
export function resolveCareerRoute(pathname: string): CareerRoute {
  if (pathname === "/") return { kind: "rewrite", path: CAREER_PREFIX };
  if (
    pathname === CAREER_PREFIX ||
    pathname.startsWith(`${CAREER_PREFIX}/`) ||
    pathname.startsWith("/_next/") ||
    pathname.startsWith("/favicon")
  ) {
    return { kind: "pass" };
  }
  const lower = pathname.toLowerCase();
  if (lower === "/rodo") return { kind: "rewrite", path: `${CAREER_PREFIX}/rodo` };
  const job = /^\/r\/([^/]+)$/.exec(lower);
  if (job) {
    return JOB_SLUG_RE.test(job[1])
      ? { kind: "rewrite", path: `${CAREER_PREFIX}/r/${job[1]}` }
      : { kind: "not-found" };
  }
  const recruiter = /^\/([^/]+)$/.exec(lower);
  if (recruiter && RECRUITER_SLUG_RE.test(recruiter[1])) {
    return { kind: "rewrite", path: `${CAREER_PREFIX}/p/${recruiter[1]}` };
  }
  return { kind: "not-found" };
}

/** Wewnętrzna trasa, która renderuje terminalowe 404 kariery. */
export const CAREER_NOT_FOUND_PATH = `${CAREER_PREFIX}/nie-znaleziono`;

/**
 * Prefiks linków na stronach kariery.
 *
 * Na hoście kariery strony są pod widocznymi adresami (`/r/x`, `/marta-n`),
 * a w NEXUSIE (dev, podgląd) pod `/kariera/r/x`, `/kariera/p/marta-n`.
 */
export type CareerBase = "" | typeof CAREER_PREFIX;

export function careerBase(onCareerHost: boolean): CareerBase {
  return onCareerHost ? "" : CAREER_PREFIX;
}

export type CareerLinkTarget =
  | { to: "job"; slug: string }
  | { to: "recruiter"; slug: string }
  | { to: "rodo" }
  | { to: "home" };

export function careerHref(base: CareerBase, target: CareerLinkTarget): string {
  switch (target.to) {
    case "job":
      return `${base}/r/${encodeURIComponent(target.slug)}`;
    case "recruiter":
      return base === ""
        ? `/${encodeURIComponent(target.slug)}`
        : `${base}/p/${encodeURIComponent(target.slug)}`;
    case "rodo":
      return `${base}/rodo`;
    case "home":
      return base === "" ? "/" : base;
  }
}

/** Pierwszy host kariery do tekstów typu „kariera.dynaminds.pl/marta-n". */
export function primaryCareerHost(): string {
  return careerHosts()[0] ?? "kariera.dynaminds.pl";
}

type HeaderReader = { get(name: string): string | null };

/** Host lokalny (dev) — tu domyślnym protokołem jest http, nie https. */
function isLocalHost(host: string): boolean {
  return (
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host === "[::1]" ||
    /^127\.\d+\.\d+\.\d+$/.test(host) ||
    /^0\.0\.0\.0$/.test(host)
  );
}

/**
 * Host WIDOCZNY dla odwiedzającego — z portem, jeśli był (dev `localhost:3000`).
 * `requestHost` go obcina, bo służy do porównań z listą hostów kariery.
 */
export function requestDisplayHost(headers: HeaderReader): string {
  const raw = (headers.get("x-forwarded-host") || headers.get("host") || "")
    .split(",")[0]
    ?.trim()
    .toLowerCase();
  // Porty domyślne nic nie mówią kandydatowi („kariera.dynaminds.pl:443").
  return (raw ?? "").replace(/:(80|443)$/, "");
}

/**
 * Pochodzenie żądania (`https://kariera.dynaminds.pl`) z nagłówków proxy.
 *
 * Za Traefikiem Next.js widzi `localhost:3000`, więc bez tego `metadataBase`
 * i adresy grafik Open Graph wskazywały `http://localhost:3000/...` — LinkedIn
 * nie pobierze takiej grafiki. `null` = brak hosta (nie zgadujemy domeny).
 */
export function requestOrigin(headers: HeaderReader): string | null {
  const host = requestDisplayHost(headers);
  if (!host) return null;
  const forwarded = headers.get("x-forwarded-proto")?.split(",")[0]?.trim().toLowerCase();
  const proto =
    forwarded === "http" || forwarded === "https"
      ? forwarded
      : isLocalHost(normalizeHost(host))
        ? "http"
        : "https";
  return `${proto}://${host}`;
}

/** `metadataBase` stron kariery — z nagłówków żądania, nigdy stały adres. */
export function careerMetadataBase(headers: HeaderReader): URL | undefined {
  const origin = requestOrigin(headers);
  if (!origin) return undefined;
  try {
    return new URL(origin);
  } catch {
    return undefined;
  }
}

/**
 * Adres do pokazania kandydatowi (bez protokołu): na hoście kariery
 * `kariera.dynaminds.pl/marta-n`, na hoście aplikacji
 * `nexus.dynaminds.pl/kariera/p/marta-n` — ten sam, pod którym strona działa.
 */
export function careerVisibleUrl(
  host: string,
  base: CareerBase,
  target: CareerLinkTarget,
): string {
  if (target.to === "home") return host;
  return `${host}${careerHref(base, target)}`;
}
